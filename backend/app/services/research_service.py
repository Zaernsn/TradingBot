"""Forward evidence collected from bot books, never from deposits/account totals."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.ml.evaluation import digest, curve_metrics
from app.models.portfolio import ResearchSnapshot, Trade, ExecutionOrder
from app.services.market_data import utc


def code_identity():
    root = Path(__file__).resolve().parents[1]
    files = [p for folder in ('ml', 'services', 'exchanges') for p in (root/folder).glob('*.py')]
    return digest({p.relative_to(root).as_posix(): p.read_text(encoding='utf-8') for p in sorted(files)})


def candidate_identity(risk, strategy_id='signal-v2'):
    return digest({'risk': asdict(risk), 'strategy': strategy_id, 'code': code_identity()})


def record_snapshot(db, portfolio, risk, errors, duration_seconds):
    now = datetime.now(timezone.utc)
    latest = db.query(ResearchSnapshot).filter(ResearchSnapshot.portfolio_id == portfolio.id).order_by(ResearchSnapshot.id.desc()).first()
    identity = candidate_identity(risk, 'signal-v2' if risk.entry_strategy == 'model' else risk.entry_strategy.replace('_','-'))
    # Keep five-minute evidence; configuration changes are always recorded.
    if latest and latest.candidate_id == identity and now-utc(latest.captured_at) < timedelta(minutes=5):
        return
    db.add(ResearchSnapshot(portfolio_id=portfolio.id, captured_at=now, candidate_id=identity,
        payload={'equity': portfolio.equity, 'cash': portfolio.cash, 'book_type': portfolio.book_type,
                 'risk': asdict(risk), 'errors': list(errors), 'cycle_seconds': duration_seconds,
                 'risk_halted': portfolio.risk_halted}))
    db.commit()


def forward_report(db, portfolio_id, since=None):
    query = db.query(ResearchSnapshot).filter(ResearchSnapshot.portfolio_id == portfolio_id)
    if since: query = query.filter(ResearchSnapshot.captured_at >= since)
    rows = query.order_by(ResearchSnapshot.captured_at).all()
    if not rows:
        return {'data_limitations': ['No forward snapshots collected'], 'observed_days': 0}
    start, end = utc(rows[0].captured_at), utc(rows[-1].captured_at)
    # Hourly series avoids calling 5-minute returns hourly returns.
    hours = {}
    for row in rows:
        hours[utc(row.captured_at).replace(minute=0, second=0, microsecond=0)] = row.payload['equity']
    times = sorted(hours)
    limitations = []
    if abs(rows[0].payload.get('cash',0)-rows[0].payload['equity']) > 1e-7:
        limitations.append('Observation starts with existing exposure; initial entry costs may precede the window')
    if any(b-a != timedelta(hours=1) for a,b in zip(times,times[1:])):
        limitations.append('Missing hourly forward observations')
    if any(row.payload.get('errors') for row in rows):
        limitations.append('Recorded runtime errors need review')
    if any(row.payload.get('book_type') != 'PAPER' for row in rows):
        limitations.append('Report requires a separate review of actual live execution costs')
    if datetime.now(timezone.utc)-end > timedelta(minutes=10):
        limitations.append('Forward observations are stale')
    trades = db.query(Trade).filter(Trade.portfolio_id == portfolio_id, Trade.created_at >= start,
                                  Trade.created_at <= end, Trade.side == 'SELL').all()
    pnl = [t.pnl for t in trades if t.pnl is not None]
    from app.services.live_execution import TERMINAL
    unresolved = db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id == portfolio_id,
        ExecutionOrder.status.notin_(TERMINAL)).count()
    # No fabricated live slippage evidence from paper fills.
    limitations.append('Actual execution cost comparison has not been supplied')
    return {'candidate_id': rows[0].candidate_id, 'observed_days': (end-start).total_seconds()/86400,
            'version_consistent': len({r.candidate_id for r in rows}) == 1,
            'closed_trades': len(pnl), 'expectancy': sum(pnl)/len(pnl) if pnl else 0.,
            'cost_overrun_pct': None, 'unresolved_orders': unresolved,
            'data_limitations': limitations, 'observation_start': start, 'observation_end': end,
            'max_cycle_seconds': max(r.payload.get('cycle_seconds', 0) for r in rows),
            **curve_metrics([hours[t] for t in times])}
