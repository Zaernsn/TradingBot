"""Opt-in entry halts. Funding changes use the verified initial-equity adjustment.

Five-minute equity checkpoints are observations, not an exact boundary valuation.
No threshold is enabled on upgrade. Halts survive config changes and restarts.
"""
import math
from datetime import datetime, timedelta, timezone
from app.models.portfolio import EquityCheckpoint, ExecutionOrder
from app.services.execution_evidence import report
from app.services.market_data import utc


def evaluate(db, portfolio, config, now=None):
    now = now or datetime.now(timezone.utc)
    status = dict(portfolio.entry_halt or {})
    if status.get('halted'):
        return status
    daily = float(config.daily_loss_pct or 0)
    weekly = float(config.weekly_loss_pct or 0)
    slippage = float(config.max_realized_slippage_pct or 0)
    failures = int(config.max_order_failures or 0)
    if not any((daily, weekly, slippage, failures)):
        return status
    resumed = datetime.fromisoformat(status['resumed_at']) if status.get('resumed_at') else None
    reasons, evidence = [], {}
    if daily or weekly:
        if not all(math.isfinite(v) for v in (portfolio.equity, portfolio.initial_equity)) or portfolio.equity < 0:
            reasons.append('Equity could not be validated')
        else:
            query = db.query(EquityCheckpoint).filter(EquityCheckpoint.portfolio_id == portfolio.id,
                                                     EquityCheckpoint.captured_at <= now)
            if resumed:
                query = query.filter(EquityCheckpoint.captured_at >= resumed)
            latest = query.order_by(EquityCheckpoint.captured_at.desc()).first()
            for label, days, limit in (('24h', 1, daily), ('7d', 7, weekly)):
                if not limit:
                    continue
                boundary = now-timedelta(days=days)
                baseline = query.filter(EquityCheckpoint.captured_at <= boundary).order_by(EquityCheckpoint.captured_at.desc()).first()
                baseline = baseline or query.order_by(EquityCheckpoint.captured_at.asc()).first()
                if baseline:
                    pnl = (portfolio.equity-portfolio.initial_equity)-(baseline.equity-baseline.funding_basis)
                    loss = max(0., -pnl/baseline.equity) if baseline.equity > 0 else (1. if pnl < 0 else 0.)
                    evidence[label] = {'loss_pct': loss, 'limit': limit, 'baseline_at': utc(baseline.captured_at).isoformat(),
                                       'coverage_hours': (now-utc(baseline.captured_at)).total_seconds()/3600,
                                       'adjusted_pnl_eur': pnl}
                    if loss >= limit:
                        reasons.append(f'{label} funding-adjusted loss limit reached')
            if latest is None or (now-utc(latest.captured_at)).total_seconds() >= 300:
                db.add(EquityCheckpoint(portfolio_id=portfolio.id, captured_at=now,
                    equity=portfolio.equity, funding_basis=portfolio.initial_equity))
    orders = db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id == portfolio.id,
                                             ExecutionOrder.created_at >= now-timedelta(days=1))
    if resumed:
        orders = orders.filter(ExecutionOrder.created_at > resumed)
    if slippage:
        # Include orders that filled today even when their intent was older.
        filled = db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id == portfolio.id,
                                                 ExecutionOrder.updated_at >= now-timedelta(days=1),
                                                 ExecutionOrder.filled_quantity > 0)
        if resumed:
            filled = filled.filter(ExecutionOrder.created_at > resumed)
        for order in filled.all():
            actual = report(order)['realized_slippage_pct']
            if actual is not None and actual >= slippage:
                evidence['slippage'] = {'order_id': order.id, 'actual': actual, 'limit': slippage}
                reasons.append('Realized slippage limit reached')
                break
    if failures:
        recent = orders.order_by(ExecutionOrder.id.desc()).limit(failures).all()
        if len(recent) == failures and all(o.status in ('REJECTED', 'UNKNOWN') for o in recent):
            evidence['order_failures'] = [o.id for o in recent]
            reasons.append('Repeated failed or uncertain orders')
    if reasons:
        status = {**status, 'halted': True, 'started_at': now.isoformat(), 'reasons': reasons, 'evidence': evidence,
                  'recovery': 'Stop the bot, reconcile orders, review the cause, then explicitly reset entry guards.'}
        portfolio.entry_halt = status
    return status


def resume(db, portfolio, now=None):
    from app.services.live_execution import unresolved
    if unresolved(db, portfolio):
        raise ValueError('Reconcile unresolved orders before resetting entry guards')
    now = now or datetime.now(timezone.utc)
    old = portfolio.entry_halt or {}
    portfolio.entry_halt = {'halted': False, 'resumed_at': now.isoformat(),
                            'previous_halt': {k: old[k] for k in ('started_at','reasons','evidence') if k in old}}
    db.add(EquityCheckpoint(portfolio_id=portfolio.id, captured_at=now,
                            equity=portfolio.equity, funding_basis=portfolio.initial_equity))
