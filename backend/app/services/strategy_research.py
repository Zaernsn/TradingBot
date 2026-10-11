"""Automatic bounded strategy research. This module never places orders."""
from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta

from app.exchanges.base import OHLCV
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.strategy_factory import (
    generated_candidates, candidate_id, candidate_factory, promotion_decision,
    shadow_promotion_decision, candidate_parameters, definition_from_parameters,
    derived_candidates, candidate_timeframe, candidate_warmup, candidate_risk,
)
from app.ml.strategies import AdaptiveParameters
from app.models.portfolio import (
    MarketCandle, Portfolio, RiskConfig, StrategyCandidate,
    ShadowRun, ShadowTrade, ShadowEquity, Trade, ExecutionOrder, BotState,
)
from app.services.live_execution import TERMINAL
from app.services.risk_service import risk_manager_from_config
from app.services.research_service import candidate_identity
from app.services.market_data import utc, INTERVALS, candle_boundary
from app.ml.evaluation import digest


SUMMARY_FIELDS=('total_return_pct','max_drawdown_pct','num_trades','closed_trades',
                'win_rate','sharpe_ratio','expectancy','total_fees','turnover',
                'top_five_profit_share')
MIN_RESEARCH_SYMBOLS=3
MIN_RESEARCH_CANDLES=720
RESEARCH_REFRESH_CANDLES=336
MAX_RESEARCH_REVISIONS=12
MAX_STRATEGY_IDENTITIES=32
MAX_LEARNING_GENERATIONS=12
RESEARCH_INTERVAL_MINUTES=5
RESEARCH_BATCH_SIZE=3
VALIDATION_WINDOW_MIN_TRADES=5
CANARY_MAX_REALIZED_LOSS_PCT=.01


def _summary(result):
    if result is None:
        return None
    return {key:result.get(key) for key in SUMMARY_FIELDS}


def _candidate_score(row):
    """Rank approved controllers with stress evidence ahead of headline return."""
    validation=(row.metrics or {}).get('validation',{})
    stress=(row.metrics or {}).get('stress',{})
    return (float(stress.get('expectancy') or 0.),
            float(validation.get('sharpe_ratio') or 0.),
            float(validation.get('total_return_pct') or 0.),
            float(validation.get('max_drawdown_pct') or -1.))


def _protocol_end(row):
    raw=((row.metrics or {}).get('protocol') or {}).get('end')
    try:
        return utc(datetime.fromisoformat(raw)) if raw else None
    except (TypeError,ValueError):
        return None


def _research_revision(row):
    """Keep compact, bounded evidence when a rejected candidate learns again."""
    metrics=row.metrics or {}
    return {'tested_at':utc(row.tested_at).isoformat(),'status':row.status,
            'protocol':metrics.get('protocol'),'checks':metrics.get('checks'),
            'development':metrics.get('development'),'validation':metrics.get('validation'),
            'holdout':metrics.get('holdout'),'stress':metrics.get('stress'),
            'momentum_benchmark':metrics.get('momentum_benchmark')}


def _data_for_timeframe(db,timeframe):
    rows=(db.query(MarketCandle).filter(MarketCandle.timeframe==timeframe)
          .order_by(MarketCandle.symbol,MarketCandle.timestamp).all())
    data={}
    for row in rows:
        data.setdefault(row.symbol,[]).append(OHLCV(
            utc(row.timestamp),row.open,row.high,row.low,row.close,row.volume))
    return {symbol:values for symbol,values in data.items() if len(values)>=720}


def _research_data(db):
    return _data_for_timeframe(db,'1h')


def research_snapshots(db):
    return {'1h':_research_data(db),'15m':_data_for_timeframe(db,'15m')}


def _research_context(db,user_id):
    config=db.query(RiskConfig).filter(RiskConfig.user_id==user_id).one()
    risk=replace(risk_manager_from_config(config),entry_strategy='auto',
                 fee_pct=max(float(config.fee_pct),float(config.verified_taker_fee_pct or 0),.004))
    portfolio=(db.query(Portfolio).filter(Portfolio.user_id==user_id,
               Portfolio.is_active.is_(True)).first())
    initial=max(1.,float(portfolio.initial_equity if portfolio else 500.))
    return config,risk,initial


def approved_candidate(db,user_id,book_type):
    allowed=(('LIVE_APPROVED_CANARY','LIVE_APPROVED') if book_type=='LIVE' else
             ('PAPER_APPROVED','LIVE_APPROVED_CANARY','LIVE_APPROVED'))
    rows=(db.query(StrategyCandidate).filter(StrategyCandidate.user_id==user_id,
          StrategyCandidate.status.in_(allowed)).all())
    # Never replace a stronger approved controller merely because a weaker one
    # finished research later.  JSON metrics are ranked in Python for database
    # portability (SQLite in development, PostgreSQL in production).
    return max(rows,key=_candidate_score) if rows else None


def approved_parameters(db,user_id,book_type):
    row=approved_candidate(db,user_id,book_type)
    if row: return row.parameters
    # Paper trading is itself part of validation, so it may begin with the
    # conservative declared baseline. Live trading never receives this fallback.
    return asdict(AdaptiveParameters()) if book_type=='PAPER' else None


def _momentum_benchmark(data,risk,initial,start,end,cache=None,liquidate_end=True,timeframe='1h',warmup=None):
    """Reuse identical benchmarks only within a batch's immutable data snapshot."""
    benchmark_risk=replace(risk,entry_strategy='momentum')
    key=digest({'snapshot':id(data),'risk':asdict(benchmark_risk),'initial':initial,
                'start':start,'end':end,'liquidate_end':liquidate_end,'timeframe':timeframe,'warmup':warmup})
    if cache is not None and key in cache:
        return cache[key]
    result=PortfolioBacktestEngine(data,initial_cash=initial,risk=benchmark_risk,
        select_assets=False,start_date=start,end_date=end,liquidate_end=liquidate_end,
        timeframe=timeframe,allow_no_trade_gaps=timeframe=='15m').run(**({'warmup':warmup} if warmup is not None else {}))
    if cache is not None:
        cache[key]=result
    return result


def research_next_candidate(db,user_id,data_snapshot=None,benchmark_cache=None,timeframe_snapshots=None):
    """Evaluate one bounded candidate, then revisit rejections on enough new data."""
    evaluated=(db.query(StrategyCandidate).filter(
        StrategyCandidate.user_id==user_id,
        StrategyCandidate.status!='IMPORTED_UNVERIFIED').all())
    existing={row.candidate_id for row in evaluated}
    queue=generated_candidates()+derived_candidates(evaluated)
    snapshots=(timeframe_snapshots if timeframe_snapshots is not None else
               {'1h':data_snapshot} if data_snapshot is not None else research_snapshots(db))
    available={frame:data for frame,data in snapshots.items() if len(data)>=MIN_RESEARCH_SYMBOLS and
               len({row.timestamp for values in data.values() for row in values})>=MIN_RESEARCH_CANDLES}
    if not available:
        return None
    end=max(row.timestamp for data in available.values() for values in data.values() for row in values)
    # At most 32 strategy identities: 24 diverse baselines plus eight bounded
    # children. Once all are seen, only rejected identities may be refreshed,
    # and only after two weeks of genuinely new completed hourly evidence.
    previous=None
    generation=0
    fresh_test_start=None
    parameters=(next((p for p in queue if candidate_id(p) not in existing and candidate_timeframe(p) in available),None)
                if len(existing)<MAX_STRATEGY_IDENTITIES else None)
    if parameters is None and len(existing)>=MAX_STRATEGY_IDENTITIES:
        generation=max(int((row.metrics or {}).get('protocol',{}).get('generation',0)) for row in evaluated)
        parents=[row for row in evaluated if int((row.metrics or {}).get('protocol',{}).get('generation',0))==generation]
        cutoff=max((_protocol_end(row) for row in parents if _protocol_end(row)),default=None)
        # One bounded child batch per genuinely new two-week evidence window.
        # Persist the cohort so hourly calls finish the SAME batch before waiting.
        cohort=next(((row.metrics or {}).get('protocol',{}).get('generation_queue') for row in parents
                     if (row.metrics or {}).get('protocol',{}).get('generation_queue')),None)
        pending=[definition_from_parameters(value) for value in cohort or []]
        parameters=next((p for p in pending if candidate_id(p) not in existing and candidate_timeframe(p) in available),None)
        if parameters:
            raw=(parents[0].metrics or {}).get('protocol',{}).get('generation_test_start')
            fresh_test_start=utc(datetime.fromisoformat(raw)) if raw else None
        elif any(candidate_id(p) not in existing for p in pending):
            return None  # Resume the persisted cohort once its timeframe has data.
        elif cutoff and generation<MAX_LEARNING_GENERATIONS and end-cutoff>=timedelta(hours=RESEARCH_REFRESH_CANDLES):
            base_ids={candidate_id(p) for p in generated_candidates()}
            mutation_parents=[row for row in parents if row.candidate_id not in base_ids] or parents
            children=[p for p in derived_candidates(mutation_parents,successive=True) if candidate_id(p) not in existing][:8]
            if children:
                generation+=1
                cohort=[candidate_parameters(p) for p in children]
                parameters=next((p for p in children if candidate_timeframe(p) in available),None)
                if parameters is None:
                    return None
                fresh_test_start=cutoff+INTERVALS[candidate_timeframe(parameters)]
        if parameters is not None:
            generation_queue=cohort
    if parameters is None:
        shadowed={value[0] for value in db.query(ShadowRun.candidate_id).filter_by(user_id=user_id)}
        due=[row for row in evaluated if row.status=='REJECTED' and _protocol_end(row)
             and candidate_timeframe(definition_from_parameters(row.parameters)) in available
             and row.candidate_id not in shadowed
             and len((row.metrics or {}).get('revisions',[]))<MAX_RESEARCH_REVISIONS
             and max(c.timestamp for values in available[candidate_timeframe(definition_from_parameters(row.parameters))].values()
                     for c in values)-_protocol_end(row)>=timedelta(hours=RESEARCH_REFRESH_CANDLES)]
        if not due:
            return None
        previous=min(due,key=lambda row:_protocol_end(row))
        parameters=definition_from_parameters(previous.parameters)
    timeframe=candidate_timeframe(parameters); interval=INTERVALS[timeframe]
    data=available[timeframe]
    stamps=sorted({row.timestamp for values in data.values() for row in values})
    end=stamps[-1]
    warmup=candidate_warmup(parameters)
    start=stamps[warmup]
    # Chronological development -> embargo -> validation -> embargo -> untouched
    # holdout. No candidate decision is allowed to train on later observations.
    dev_end=stamps[int(len(stamps)*.45)]
    validation_start=dev_end+timedelta(hours=12)
    validation_end=stamps[int(len(stamps)*.70)]
    holdout_start=validation_end+timedelta(hours=12)
    if previous is not None:
        # A refreshed candidate must earn approval on NEW observations, not
        # repeatedly shop the same final test until it happens to pass.
        holdout_start=max(holdout_start,_protocol_end(previous)+interval)
    if fresh_test_start is not None:
        holdout_start=max(holdout_start,fresh_test_start)
    if holdout_start>=end:
        return None
    _,risk,initial=_research_context(db,user_id)
    risk=candidate_risk(risk,parameters)
    factory=candidate_factory(parameters)
    common=dict(candles_by_symbol=data,initial_cash=initial,risk=risk,
                select_assets=False,model_factory=factory,strategy_id=candidate_id(parameters),
                timeframe=timeframe,allow_no_trade_gaps=timeframe=='15m')
    run_settings={'warmup':warmup} if timeframe=='15m' else {}
    development=PortfolioBacktestEngine(**common,start_date=start,end_date=dev_end).run(**run_settings)
    validation=holdout=stress=benchmark=None
    validation_windows=[]
    # Reject at the first failed mandatory gate. Untested stages remain absent,
    # rather than storing fabricated zero results or consuming final-test data.
    stopped_stage='development'
    decision={'decision':'REJECTED','live_authorized':False,
              'checks':{'development_expectancy_positive':False}}
    if development['expectancy']>0:
        validation=PortfolioBacktestEngine(**common,start_date=validation_start,end_date=validation_end).run(**run_settings)
        stopped_stage='validation'
        decision['checks']={'development_expectancy_positive':True,
                            'validation_expectancy_positive':False}
        if validation['expectancy']>0:
            # A positive aggregate may hide a single lucky period. Require
            # two separately simulated chronological windows before final tests.
            middle=validation_start+(validation_end-validation_start)/2
            windows=((validation_start,middle),(middle,validation_end))
            decision['checks']['validation_expectancy_positive']=True
            stopped_stage='validation_windows'
            for window_start,window_end in windows:
                result=PortfolioBacktestEngine(**common,start_date=window_start,end_date=window_end).run(**run_settings)
                passed=(result['expectancy']>0 and result.get('closed_trades',0)>=VALIDATION_WINDOW_MIN_TRADES)
                validation_windows.append({'start':window_start.isoformat(),'end':window_end.isoformat(),
                    'metrics':_summary(result),'passed':passed})
                decision['checks']['validation_windows_positive']=passed
                if not passed:
                    break
        if len(validation_windows)==2 and all(window['passed'] for window in validation_windows):
            stopped_stage=None
            holdout=PortfolioBacktestEngine(**common,start_date=holdout_start,end_date=end).run(**run_settings)
            stressed=replace(risk,fee_pct=risk.fee_pct*2,slippage_pct=risk.slippage_pct*2)
            stress=PortfolioBacktestEngine(data,initial_cash=initial,risk=stressed,
                select_assets=False,model_factory=factory,strategy_id=candidate_id(parameters),
                start_date=holdout_start,end_date=end,timeframe=timeframe,allow_no_trade_gaps=timeframe=='15m').run(**run_settings)
            benchmark=_momentum_benchmark(data,risk,initial,holdout_start,end,benchmark_cache,
                                         timeframe=timeframe,warmup=warmup if timeframe=='15m' else None)
            decision=promotion_decision(development,validation,stress,benchmark,holdout)
            decision['checks']['validation_windows_positive']=True
    identity=candidate_id(parameters)
    row=db.query(StrategyCandidate).filter_by(user_id=user_id,candidate_id=identity).first()
    imported=list((row.metrics or {}).get('imports') or []) if row else []
    revisions=list((row.metrics or {}).get('revisions') or []) if row else []
    if row:
        revisions.append(_research_revision(row))
    values={'development':_summary(development),'validation':_summary(validation),
            'holdout':_summary(holdout),
            'stress':_summary(stress),'momentum_benchmark':_summary(benchmark),
            'checks':decision['checks'],'live_authorized':False,
            'stopped_stage':stopped_stage,
            'validation_windows':validation_windows,
            'generation_development':((row.metrics or {}).get('generation_development',
                (row.metrics or {}).get('development',_summary(development))) if row else _summary(development)),
            'protocol':{'embargo_hours':12,'development_end':dev_end.isoformat(),
                'timeframe':timeframe,'warmup_bars':warmup,
                'validation_start':validation_start.isoformat(),'validation_end':validation_end.isoformat(),
                'holdout_start':holdout_start.isoformat(),'end':end.isoformat(),
                'data_sha256':development['experiment']['data_sha256'],
                'candidate_source':'baseline' if identity in {candidate_id(p) for p in generated_candidates()} else 'bounded_derived',
                'maximum_strategy_identities':MAX_STRATEGY_IDENTITIES,
                'generation':((previous.metrics or {}).get('protocol',{}).get('generation',0) if previous else generation),
                **({'generation_queue':generation_queue,'generation_test_start':fresh_test_start.isoformat()}
                   if fresh_test_start is not None else {}),
                'manual_live_approval_required':False,
                'frozen_version':candidate_identity(risk,identity),
                'fee_pct':risk.fee_pct,'slippage_pct':risk.slippage_pct,
                'refresh_candles':RESEARCH_REFRESH_CANDLES}}
    if imported: values['imports']=imported
    if revisions: values['revisions']=revisions
    if row:
        row.parameters=candidate_parameters(parameters); row.status=decision['decision']
        row.metrics=values; row.tested_at=datetime.now(timezone.utc)
    else:
        row=StrategyCandidate(user_id=user_id,candidate_id=identity,
            parameters=candidate_parameters(parameters),status=decision['decision'],metrics=values,
            tested_at=datetime.now(timezone.utc)); db.add(row)
    db.commit(); db.refresh(row)
    return row


def advance_shadow_candidates(db,user_id,now=None,data_snapshot=None,benchmark_cache=None,timeframe_snapshots=None):
    """Advance frozen candidates on candles that arrived after their test time.

    This is a virtual portfolio calculation. It never calls an exchange and
    never submits an order, so the user's active book can remain LIVE.
    """
    now=now or datetime.now(timezone.utc)
    rows=(db.query(StrategyCandidate).filter(StrategyCandidate.user_id==user_id,
          StrategyCandidate.status=='PAPER_APPROVED').all())
    if not rows:
        return []
    snapshots=(timeframe_snapshots if timeframe_snapshots is not None else
               {'1h':data_snapshot} if data_snapshot is not None else research_snapshots(db))
    _,base_risk,initial=_research_context(db,user_id)
    updates=[]
    promotion_candidates=[]
    for row in rows:
        parameters=definition_from_parameters(row.parameters)
        timeframe=candidate_timeframe(parameters); interval=INTERVALS[timeframe]
        data=snapshots.get(timeframe,{})
        if len(data)<MIN_RESEARCH_SYMBOLS:
            continue
        risk=candidate_risk(base_risk,parameters)
        warmup=candidate_warmup(parameters)
        run_settings={'warmup':warmup} if timeframe=='15m' else {}
        last_stamp=max(value.timestamp for values in data.values() for value in values)
        tested=row.tested_at
        if tested.tzinfo is None:
            tested=tested.replace(tzinfo=timezone.utc)
        start=candle_boundary(tested,timeframe,ceil=True)
        end=last_stamp+interval
        observed=max(0.,(min(now,end)-start).total_seconds()/86400)
        if last_stamp<start:
            continue
        factory=candidate_factory(parameters)
        version=candidate_identity(risk,row.candidate_id)
        run=db.query(ShadowRun).filter_by(user_id=user_id,candidate_id=row.candidate_id).first()
        frozen=(row.metrics or {}).get('protocol',{}).get('frozen_version')
        if (run and run.version!=version) or (frozen and frozen!=version):
            row.status='REJECTED'
            row.metrics={**(row.metrics or {}),'shadow_rejection':'Frozen strategy or risk version changed'}
            if run: run.status='INVALIDATED'
            updates.append({'candidate_id':row.candidate_id,'status':row.status,
                            'reason':'version_changed'})
            continue
        if not run:
            run=ShadowRun(user_id=user_id,candidate_id=row.candidate_id,version=version,
                status='ACTIVE',started_at=start,initial_cash=initial,cash=initial,
                equity=initial,peak_equity=initial,open_positions={},metrics={})
            db.add(run); db.flush()
        common=dict(candles_by_symbol=data,initial_cash=initial,risk=risk,
                    select_assets=False,model_factory=factory,
                    strategy_id=row.candidate_id,start_date=start,end_date=end,
                    liquidate_end=False,timeframe=timeframe,allow_no_trade_gaps=timeframe=='15m')
        shadow=PortfolioBacktestEngine(**common).run(**run_settings)
        stressed=replace(risk,fee_pct=risk.fee_pct*2,slippage_pct=risk.slippage_pct*2)
        stress=PortfolioBacktestEngine(data,initial_cash=initial,risk=stressed,
            select_assets=False,model_factory=factory,strategy_id=row.candidate_id,
            start_date=start,end_date=end,liquidate_end=False,timeframe=timeframe,
            allow_no_trade_gaps=timeframe=='15m').run(**run_settings)
        benchmark=_momentum_benchmark(data,risk,initial,start,end,benchmark_cache,liquidate_end=False,
                                     timeframe=timeframe,warmup=warmup if timeframe=='15m' else None)
        decision=shadow_promotion_decision(shadow,stress,benchmark,observed)
        requested_status=decision['decision']
        # Arbitration below guarantees that only one controller can own live
        # canary evidence. Other qualified challengers remain in paper shadow.
        row.status='PAPER_APPROVED' if requested_status=='LIVE_APPROVED_CANARY' else requested_status
        row.metrics={**(row.metrics or {}),'shadow':_summary(shadow),
                     'shadow_stress':_summary(stress),'shadow_momentum_benchmark':_summary(benchmark),
                     'shadow_promotion':decision,'shadow_updated_at':now.isoformat()}
        existing_intents={value[0] for value in db.query(ShadowTrade.intent_key).filter_by(run_id=run.id)}
        for trade in shadow.get('trades',[]):
            intent=digest({'candidate':row.candidate_id,'symbol':trade['symbol'],
                           'side':trade['side'],'timestamp':trade['timestamp']})
            if intent in existing_intents: continue
            db.add(ShadowTrade(run_id=run.id,intent_key=intent,symbol=trade['symbol'],
                side=trade['side'],quantity=trade['quantity'],price=trade['price'],
                fee=trade['fee'],pnl=trade.get('pnl'),candle_timestamp=trade['timestamp']))
            existing_intents.add(intent)
        existing_equity={utc(value[0]) for value in db.query(ShadowEquity.candle_timestamp).filter_by(run_id=run.id)}
        peak=initial
        for point in shadow.get('equity_curve',[]):
            stamp=point['timestamp']
            peak=max(peak,float(point['equity']))
            if stamp in existing_equity: continue
            db.add(ShadowEquity(run_id=run.id,candle_timestamp=stamp,
                cash=float(point['cash']),equity=float(point['equity']),
                drawdown_pct=float(point['equity'])/peak-1))
            existing_equity.add(stamp)
        positions={symbol:{**values,'opened_at':values['opened_at'].isoformat()
                          if hasattr(values.get('opened_at'),'isoformat') else values.get('opened_at')}
                   for symbol,values in (shadow.get('open_positions') or {}).items()}
        run.status='REJECTED' if row.status=='REJECTED' else 'ACTIVE'
        run.last_candle_at=last_stamp
        run.cash=float(shadow.get('ending_cash',initial))
        run.equity=float(shadow.get('final_equity',initial))
        run.peak_equity=max(peak,run.equity)
        run.open_positions=positions
        run.metrics={'shadow':_summary(shadow),'stress':_summary(stress),
                     'benchmark':_summary(benchmark),'promotion':decision}
        update={'candidate_id':row.candidate_id,'status':row.status,
                'observed_days':observed,'closed_trades':shadow.get('closed_trades',0)}
        updates.append(update)
        if requested_status=='LIVE_APPROVED_CANARY':
            promotion_candidates.append((row,run,update,shadow,stress))
    active_live=db.query(StrategyCandidate).filter(StrategyCandidate.user_id==user_id,
        StrategyCandidate.status.in_(('LIVE_APPROVED_CANARY','LIVE_APPROVED'))).first()
    if promotion_candidates and not active_live:
        def score(item):
            _,_,_,shadow,stress=item
            return (float(stress.get('expectancy') or 0.),float(shadow.get('expectancy') or 0.),
                    float(shadow.get('total_return_pct') or 0.),
                    float(shadow.get('max_drawdown_pct') or -1.))
        winner=max(promotion_candidates,key=score)
        for row,run,update,_,_ in promotion_candidates:
            metrics=dict(row.metrics or {})
            if row is winner[0]:
                row.status='LIVE_APPROVED_CANARY'; run.status='APPROVED'
                metrics['canary_started_at']=metrics.get('canary_started_at') or now.isoformat()
                live_portfolio=db.query(Portfolio).filter_by(user_id=user_id,is_active=True,book_type='LIVE').first()
                if live_portfolio:
                    metrics['canary_start_equity']=float(live_portfolio.equity)
                metrics['canary_selection']={'selected':True,'selected_at':now.isoformat(),
                    'reason':'Strongest stress-adjusted qualified shadow candidate'}
            else:
                metrics['canary_selection']={'selected':False,'selected_at':now.isoformat(),
                    'reason':'Another qualified shadow candidate won the single canary slot'}
            row.metrics=metrics; update['status']=row.status
    elif promotion_candidates:
        for row,_,update,_,_ in promotion_candidates:
            row.metrics={**(row.metrics or {}),'canary_selection':{'selected':False,
                'selected_at':now.isoformat(),'reason':'An active live controller already owns the canary slot'}}
            update['status']=row.status
    db.commit()
    return updates


def review_live_canary(db,user_id,now=None,critical_reason=None):
    """Promote or suspend the one bounded live canary using reconciled evidence."""
    now=now or datetime.now(timezone.utc)
    rows=(db.query(StrategyCandidate).filter_by(user_id=user_id,
          status='LIVE_APPROVED_CANARY').all())
    if not rows: return []
    # Repair any legacy/mutated state that contains multiple canaries. Only the
    # strongest locally evaluated controller may consume subsequent live proof.
    if len(rows)>1:
        winner=max(rows,key=_candidate_score)
        for extra in rows:
            if extra is winner: continue
            extra.status='PAPER_APPROVED'
            extra.metrics={**(extra.metrics or {}),'canary_selection':{'selected':False,
                'selected_at':now.isoformat(),'reason':'Duplicate canary repaired automatically'}}
        rows=[winner]
    portfolio=(db.query(Portfolio).filter(Portfolio.user_id==user_id,
               Portfolio.is_active.is_(True),Portfolio.book_type=='LIVE').first())
    state=db.query(BotState).filter_by(user_id=user_id).first()
    updates=[]
    for row in rows:
        metrics=dict(row.metrics or {})
        started_raw=metrics.get('canary_started_at')
        try: started=datetime.fromisoformat(started_raw) if started_raw else now
        except (TypeError,ValueError): started=now
        if started.tzinfo is None: started=started.replace(tzinfo=timezone.utc)
        reason=critical_reason
        if not portfolio: reason=reason or 'No active reconciled live portfolio'
        elif portfolio.risk_halted: reason=reason or 'Live drawdown risk halt'
        elif db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id==portfolio.id,
                ExecutionOrder.status.notin_(TERMINAL)).count():
            reason=reason or 'Unresolved live order'
        elif state and state.health in {'ERROR','RISK_HALTED'} and state.last_error and any(
                marker in state.last_error.lower() for marker in
                ('balance differs','reconciliation','unmanaged exchange','unresolved live order','drawdown')):
            reason=reason or state.last_error[:300]
        trades=(db.query(Trade).filter(Trade.portfolio_id==portfolio.id,
                Trade.created_at>=started).all() if portfolio else [])
        closed=sum(trade.side=='SELL' for trade in trades)
        pnl=sum(float(trade.pnl or 0.) for trade in trades if trade.side=='SELL')
        turnover=sum(float(trade.total_cost or 0.) for trade in trades)
        fees=sum(float(trade.fee or 0.) for trade in trades)
        fee_ratio=fees/turnover if turnover>0 else 0.
        configured=float(db.query(RiskConfig).filter_by(user_id=user_id).one().verified_taker_fee_pct or 0.)
        if portfolio:
            baseline=float(metrics.get('canary_start_equity') or portfolio.equity)
            metrics['canary_start_equity']=baseline
            if baseline>0 and pnl<=-baseline*CANARY_MAX_REALIZED_LOSS_PCT:
                reason=reason or 'Live pilot realized loss reached 1% of starting equity'
        if turnover and configured and fee_ratio>configured*1.25:
            reason=reason or 'Canary execution costs exceeded the verified fee by more than 25%'
        if closed>=10 and pnl<=0:
            reason=reason or 'Canary failed profitability after 10 reconciled exits'
        canary={'started_at':started.isoformat(),'closed_round_trips':closed,
                'realized_pnl':pnl,'fee_ratio':fee_ratio,'reviewed_at':now.isoformat(),
                'realized_loss_limit_pct':CANARY_MAX_REALIZED_LOSS_PCT}
        if reason:
            row.status='LIVE_SUSPENDED'; canary['suspension_reason']=reason
        elif closed>=10 and pnl>0:
            row.status='LIVE_APPROVED'; canary['promotion_reason']='10 reconciled profitable live exits'
        metrics['canary']=canary; row.metrics=metrics
        updates.append({'candidate_id':row.candidate_id,'status':row.status,**canary})
    db.commit()
    return updates


def research_status(db,user_id,now=None):
    """Compact, user-facing observability without exposing exchange secrets."""
    now=now or datetime.now(timezone.utc)
    candidates=(db.query(StrategyCandidate).filter_by(user_id=user_id)
                .order_by(StrategyCandidate.tested_at.desc()).all())
    runs={run.candidate_id:run for run in db.query(ShadowRun).filter_by(user_id=user_id).all()}
    config=db.query(RiskConfig).filter_by(user_id=user_id).first()
    state=db.query(BotState).filter_by(user_id=user_id).first()
    items=[]
    for row in candidates:
        run=runs.get(row.candidate_id); metrics=row.metrics or {}
        started=run.started_at if run else None
        if started and started.tzinfo is None: started=started.replace(tzinfo=timezone.utc)
        days=max(0.,(now-started).total_seconds()/86400) if started else 0.
        promotion=metrics.get('shadow_promotion') or {}
        closed=int((metrics.get('shadow') or {}).get('closed_trades') or 0)
        failed=[name for name,value in (promotion.get('checks') or metrics.get('checks') or {}).items() if value is False]
        items.append({'candidate_id':row.candidate_id,'family':row.parameters.get('family','adaptive_momentum'),
            'timeframe':row.parameters.get('timeframe','1h'),
            'status':row.status,'tested_at':row.tested_at,'shadow_days':round(days,2),
            'shadow_days_required':0,
            'shadow_closed_trades':closed,'shadow_trades_required':int(promotion.get('minimum_closed_trades') or 30),
            'failed_checks':failed,'canary':metrics.get('canary'),
            'promotion_reason':(metrics.get('canary_selection') or {}).get('reason'),
            'shadow_rejection':metrics.get('shadow_rejection'),
            'research_revisions':len(metrics.get('revisions',[])),
            'stopped_stage':metrics.get('stopped_stage'),
            'validation_windows':metrics.get('validation_windows',[]),
            'validation':metrics.get('validation'),'holdout':metrics.get('holdout'),
            'stress':metrics.get('stress')})
    counts={}
    for row in candidates: counts[row.status]=counts.get(row.status,0)+1
    return {'counts':counts,'candidates':items,
        'learning_policy':{'maximum_strategy_identities':MAX_STRATEGY_IDENTITIES+8*MAX_LEARNING_GENERATIONS,
            'initial_generation_budget':MAX_STRATEGY_IDENTITIES,'maximum_followup_generations':MAX_LEARNING_GENERATIONS,
            'maximum_refreshes_per_candidate':MAX_RESEARCH_REVISIONS,
            'parent_selection':'frozen_development_only','discard_policy':'reject_and_retain_evidence',
            'new_candidates_require_manual_live_approval':False,
            'enabled':bool(config and config.entry_strategy=='auto'),
            'cadence_hours':RESEARCH_INTERVAL_MINUTES/60,
            'cadence_minutes':RESEARCH_INTERVAL_MINUTES,'batch_size':RESEARCH_BATCH_SIZE,
            'minimum_forward_days':0,'minimum_closed_trades':30,
            'signal_timeframes':['1h','15m'],'minimum_research_bars':MIN_RESEARCH_CANDLES},
        'live_candidate':next((item for item in items if item['status'] in
            {'LIVE_APPROVED_CANARY','LIVE_APPROVED'}),None),
        'verified_taker_fee_pct':float(config.verified_taker_fee_pct) if config and config.verified_taker_fee_pct is not None else None,
        'verified_taker_fee_at':config.verified_taker_fee_at if config else None,
        'watchlist_age_seconds':(state.discovery_stats or {}).get('watchlist_age_seconds') if state else None,
        'research':(state.discovery_stats or {}).get('strategy_research') if state else None}
