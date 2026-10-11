from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest

from app.ml.strategies import (
    AdaptiveMomentumModel, AdaptiveParameters, MarketRegime,
    classify_market_regime, VolatilityTrendModel, BreakoutLiquidityModel,
    DefensiveMeanReversionModel,
)
from app.ml.strategy_factory import (generated_candidates, promotion_decision,
    shadow_promotion_decision, candidate_id, candidate_parameters, definition_from_parameters,
    derived_candidates)
from app.models.portfolio import (StrategyCandidate, Trade, MarketCandle, ShadowRun,
    ShadowTrade, ShadowEquity, ExecutionOrder)
from app.services.strategy_research import (approved_parameters, review_live_canary,
    research_status, advance_shadow_candidates, research_next_candidate,
    RESEARCH_REFRESH_CANDLES)
from app.services.research_metadata import export_metadata, import_metadata
from app.services.bot_service import canary_entry_budget, CANARY_MAX_POSITIONS, CANARY_MAX_EXPOSURE_PCT
from app.ml.backtest import PortfolioBacktestEngine
from app.services.risk_service import risk_manager_from_config
from app.exchanges.base import OHLCV
from tests.test_autonomous import setup_bot


def history(hourly_return, count=25, volume=1000.):
    price=100.
    rows=[]
    for _ in range(count):
        price*=1+hourly_return
        rows.append(SimpleNamespace(close=price,volume=volume))
    return rows


def test_regime_requires_coverage_and_detects_acceleration():
    strong={f'C{i}':history(.01) for i in range(10)}
    regime=classify_market_regime(strong,list(strong),cost=.005)
    assert regime.name=='acceleration' and regime.breadth==1 and regime.coverage==1
    assert classify_market_regime({'C0':history(.01)},list(strong)).name=='insufficient'
    flat={f'C{i}':history(0.) for i in range(10)}
    assert classify_market_regime(flat,list(flat)).name=='defensive'


def test_adaptive_model_stays_in_cash_defensively_and_uses_trend_when_approved():
    rows=history(.002)
    defensive=AdaptiveMomentumModel(MarketRegime('defensive',.2,-.01,1.,10,8)).fit(rows)
    assert defensive.predict(rows)['action']!='BUY'
    trend=AdaptiveMomentumModel(MarketRegime('trend',.7,.01,1.,10,8)).fit(rows)
    result=trend.predict(rows)
    assert result['action']=='BUY' and result['active_strategy']=='momentum'


def test_generated_strategies_are_bounded_and_cannot_self_authorize_live():
    candidates=generated_candidates()
    assert len(candidates)==24 and len({candidate_id(p) for p in candidates})==24
    assert candidate_id(AdaptiveParameters())=='adaptive-'+'-'.join(
        f'{key}={value:g}' for key,value in sorted(asdict(AdaptiveParameters()).items()))
    assert all(definition_from_parameters(candidate_parameters(p))==p for p in candidates)
    positive=dict(expectancy=1.,total_return_pct=.1,max_drawdown_pct=-.02,closed_trades=40)
    benchmark={**positive,'total_return_pct':.05}
    decision=promotion_decision(positive,positive,positive,benchmark)
    assert decision['decision']=='PAPER_APPROVED'
    assert decision['live_authorized'] is False
    rejected=promotion_decision({**positive,'expectancy':-1},positive,positive,benchmark)
    assert rejected['decision']=='REJECTED'


def test_second_generation_is_bounded_and_only_changes_declared_parameters():
    evaluated=[SimpleNamespace(candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        metrics={'holdout':{'expectancy':index,'total_return_pct':0}})
        for index,p in enumerate(generated_candidates())]
    children=derived_candidates(evaluated)
    assert 1<=len(children)<=8
    assert all(candidate_id(child) not in {candidate_id(p) for p in generated_candidates()} for child in children)
    assert all(definition_from_parameters(candidate_parameters(child))==child for child in children)


def test_shadow_promotion_requires_evidence_but_no_calendar_minimum():
    good=dict(expectancy=1.,total_return_pct=.08,max_drawdown_pct=-.03,
              closed_trades=40,risk_halted=False,top_five_profit_share=.25)
    benchmark={**good,'total_return_pct':.03}
    immature=shadow_promotion_decision({**good,'closed_trades':29},good,benchmark,observed_days=2)
    assert immature['decision']=='PAPER_APPROVED' and not immature['live_authorized']
    approved=shadow_promotion_decision(good,good,benchmark,observed_days=.1)
    assert approved['decision']=='LIVE_APPROVED_CANARY' and approved['live_authorized']
    assert approved['minimum_days']==0
    assert not shadow_promotion_decision(good,{**good,'expectancy':-1},benchmark,.1)['live_authorized']
    rejected=shadow_promotion_decision({**good,'expectancy':-1},good,benchmark,observed_days=31)
    assert rejected['decision']=='REJECTED' and not rejected['live_authorized']


@pytest.mark.parametrize('development_expectancy,validation_expectancy,expected_runs,stopped_stage',[
    (-1,1,1,'development'), (1,-1,2,'validation'), (1,1,7,None),
])
def test_research_stops_at_failed_gate_without_evaluating_holdout(
        setup_bot,monkeypatch,development_expectancy,validation_expectancy,expected_runs,stopped_stage):
    c=setup_bot
    import app.services.strategy_research as research
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=i),100.,100.,100.,100.,10000.) for i in range(1000)]
    monkeypatch.setattr(research,'_research_data',lambda db:{f'C{i}/EUR':rows for i in range(3)})
    calls=[]
    class FakeEngine:
        def __init__(self,*args,**kwargs): calls.append(kwargs)
        def run(self):
            expectancy=(development_expectancy if len(calls)==1 else validation_expectancy)
            return dict(expectancy=expectancy,total_return_pct=.1,max_drawdown_pct=-.01,
                        closed_trades=40,experiment={'data_sha256':'verified'})
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)
    candidate=research_next_candidate(c.db,c.user.id)
    assert len(calls)==expected_runs
    assert candidate.metrics['stopped_stage']==stopped_stage
    assert candidate.metrics['protocol']['data_sha256']=='verified'
    if stopped_stage:
        assert candidate.status=='REJECTED'
        assert candidate.metrics['holdout'] is None
        assert candidate.metrics['stress'] is None
        assert candidate.metrics['momentum_benchmark'] is None
        assert (candidate.metrics['validation'] is None)==(stopped_stage=='development')
    status=research_status(c.db,c.user.id)
    assert status['candidates'][0]['shadow_days_required']==0
    assert status['learning_policy']['cadence_minutes']==5


@pytest.mark.asyncio
async def test_automatic_rechecks_same_candle_after_liquidity_clears_without_duplicate_orders(setup_bot,monkeypatch):
    from tests.test_autonomous import run
    from app.models.portfolio import Position, Signal
    from app.services.memecoin_service import LiquidityLimitError
    c=setup_bot
    c.risk.entry_strategy='auto'; c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='recheck',
        parameters=asdict(AdaptiveParameters()),status='PAPER_APPROVED',metrics={},
        tested_at=datetime.now(timezone.utc)))
    c.db.commit()
    predictions=[]
    class RuleModel:
        def set_regime(self,regime): pass
        def fit(self,*args,**kwargs): return self
        def predict(self,rows):
            predictions.append(rows[-1].timestamp)
            return dict(action='BUY',active_strategy='momentum')
    monkeypatch.setattr('app.services.bot_service.candidate_factory',lambda definition:lambda symbol:RuleModel())
    checks=[]
    async def liquidity(*args):
        checks.append(1)
        if len(checks)==1: raise LiquidityLimitError('Spread too wide')
        return None
    monkeypatch.setattr('app.services.bot_service.check_liquidity',liquidity)
    await run(c)
    assert c.db.query(Trade).count()==0
    signals=c.db.query(Signal).count()
    latest=c.db.query(Signal).order_by(Signal.id.desc()).first()
    c.state.entry_decisions={'BTC/EUR':{'retryable':True,'retry_signal_id':latest.id,
        'retry_attempts':1,'retry_after':(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()}}
    c.db.commit()
    await run(c)
    assert c.db.query(Trade).count()==0 and len(checks)==1
    assert c.state.entry_decisions['BTC/EUR']['code']=='retry_wait'
    retry=dict(c.state.entry_decisions['BTC/EUR'])
    retry['retry_after']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    c.state.entry_decisions={'BTC/EUR':retry}; c.db.commit()
    await run(c)
    assert len(predictions)==3 and len(set(predictions))==1
    assert c.db.query(Trade).count()==1
    assert c.db.query(Position).one().symbol=='BTC/EUR'
    assert c.db.query(Signal).count()==signals
    await run(c)
    assert c.db.query(Trade).count()==1
    assert c.db.query(Signal).count()==signals
    from app.services.trading_service import record_fill
    from app.exchanges.base import OrderSide
    position=c.db.query(Position).one()
    record_fill(c.db,c.portfolio,'BTC/EUR',OrderSide.SELL,position.quantity,100.,.01,100.)
    await run(c)
    assert c.db.query(Trade).count()==2
    assert c.db.query(Position).count()==0
    assert c.state.entry_decisions['BTC/EUR']['code']=='waiting_new_evidence'


def test_only_promotion_matching_book_is_selectable(setup_bot):
    c=setup_bot
    params=asdict(AdaptiveParameters())
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='candidate',parameters=params,
        status='PAPER_APPROVED',metrics={},tested_at=datetime.now(timezone.utc)))
    c.db.commit()
    assert approved_parameters(c.db,c.user.id,'PAPER')==params
    assert approved_parameters(c.db,c.user.id,'LIVE') is None


def test_paper_automatic_mode_has_safe_baseline_but_live_fails_closed(setup_bot):
    c=setup_bot
    assert approved_parameters(c.db,c.user.id,'PAPER')==asdict(AdaptiveParameters())
    assert approved_parameters(c.db,c.user.id,'LIVE') is None


def test_best_approved_candidate_wins_instead_of_newest(setup_bot):
    c=setup_bot
    weak={**asdict(AdaptiveParameters()),'momentum_threshold':.02}
    strong=asdict(AdaptiveParameters())
    now=datetime.now(timezone.utc)
    c.db.add_all([
        StrategyCandidate(user_id=c.user.id,candidate_id='strong',parameters=strong,
            status='PAPER_APPROVED',metrics={'validation':{'sharpe_ratio':1.2,'total_return_pct':.1,
            'max_drawdown_pct':-.03},'stress':{'expectancy':2.}},tested_at=now),
        StrategyCandidate(user_id=c.user.id,candidate_id='newer-weak',parameters=weak,
            status='PAPER_APPROVED',metrics={'validation':{'sharpe_ratio':.3,'total_return_pct':.02,
            'max_drawdown_pct':-.01},'stress':{'expectancy':.1}},tested_at=now),
    ])
    c.db.commit()
    assert approved_parameters(c.db,c.user.id,'PAPER')==strong


def test_rejected_candidate_relearns_after_new_completed_candles(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    parameters=AdaptiveParameters()
    identity=candidate_id(parameters)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    data={}
    for symbol_index in range(3):
        price=100.+symbol_index
        rows=[]
        for index in range(720+RESEARCH_REFRESH_CANDLES):
            price*=1.001
            rows.append(OHLCV(start+timedelta(hours=index),price,price,price,price,10000.))
        data[f'C{symbol_index}/EUR']=rows
    old_end=start+timedelta(hours=719)
    candidate=StrategyCandidate(user_id=c.user.id,candidate_id=identity,
        parameters=asdict(parameters),status='REJECTED',metrics={
            'protocol':{'end':old_end.isoformat()},'checks':{'old':False},
            'holdout':{'expectancy':-1},'stress':{'expectancy':-1}},tested_at=old_end)
    c.db.add(candidate); c.db.commit()

    result={'total_return_pct':-.01,'max_drawdown_pct':-.02,'num_trades':2,
        'closed_trades':1,'win_rate':0.,'sharpe_ratio':-1.,'expectancy':-1.,
        'total_fees':1.,'turnover':100.,'top_five_profit_share':0.,
        'experiment':{'data_sha256':'new-data'}}
    class FakeEngine:
        def __init__(self,*args,**kwargs): pass
        def run(self): return dict(result)
    monkeypatch.setattr(research,'_research_data',lambda db:data)
    monkeypatch.setattr(research,'generated_candidates',lambda:[parameters])
    monkeypatch.setattr(research,'derived_candidates',lambda evaluated:[])
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)

    refreshed=research_next_candidate(c.db,c.user.id)
    assert refreshed.id==candidate.id
    assert refreshed.metrics['revisions'][-1]['protocol']['end']==old_end.isoformat()
    assert refreshed.metrics['protocol']['end']==data['C0/EUR'][-1].timestamp.isoformat()
    assert datetime.fromisoformat(refreshed.metrics['protocol']['holdout_start'])>old_end
    assert refreshed.metrics['protocol']['manual_live_approval_required'] is False
    assert c.db.query(StrategyCandidate).count()==1


def test_rejected_candidate_does_not_retest_without_enough_new_data(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    parameters=AdaptiveParameters(); identity=candidate_id(parameters)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=index),100.,100.,100.,100.,10000.) for index in range(900)]
    end=rows[-1].timestamp
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=identity,
        parameters=asdict(parameters),status='REJECTED',metrics={
            'protocol':{'end':(end-timedelta(hours=RESEARCH_REFRESH_CANDLES-1)).isoformat()}},tested_at=end))
    c.db.commit()
    monkeypatch.setattr(research,'_research_data',lambda db:{f'C{i}/EUR':rows for i in range(3)})
    monkeypatch.setattr(research,'generated_candidates',lambda:[parameters])
    monkeypatch.setattr(research,'derived_candidates',lambda evaluated:[])
    assert research_next_candidate(c.db,c.user.id) is None


def test_metadata_import_cannot_grant_live_authority(setup_bot):
    c=setup_bot
    params=asdict(AdaptiveParameters())
    payload={'schema_version':1,'kind':'trading-bot-research-metadata',
        'exported_at':datetime.now(timezone.utc).isoformat(),
        'candidates':[{'candidate_id':'adaptive-'+'-'.join(
            f'{key}={params[key]:g}' for key in sorted(params)),
            'parameters':params,'status':'LIVE_APPROVED','metrics':{'expectancy':999},
            'tested_at':datetime.now(timezone.utc).isoformat()}], 'shadow_runs':[]}
    result=import_metadata(c.db,c.user.id,payload)
    row=c.db.query(StrategyCandidate).one()
    assert result['live_authorized'] is False
    assert row.status=='IMPORTED_UNVERIFIED'
    assert export_metadata(c.db,c.user.id)['candidates'][0]['status']=='IMPORTED_UNVERIFIED'


def test_shadow_backtest_does_not_create_artificial_terminal_sell(setup_bot):
    c=setup_bot
    c.risk.entry_strategy='momentum'; c.risk.memecoins_enabled=False
    c.risk.max_open_positions=1; c.risk.max_total_exposure_pct=1
    c.risk.max_correlated_exposure_pct=1; c.risk.max_position_pct=.2
    c.risk.take_profit_pct=10
    risk=risk_manager_from_config(c.risk)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[]; price=100.
    for index in range(60):
        price*=1.01
        rows.append(OHLCV(start+timedelta(hours=index),price,price,price,price,1000.))
    result=PortfolioBacktestEngine({'BTC/EUR':rows},100.,risk=risk,
        select_assets=False,liquidate_end=False).run()
    assert result['open_positions']
    assert not any(trade['side']=='SELL' for trade in result['trades'])


def test_generated_family_models_are_bounded_and_regime_aware():
    candles=[]; price=100.; start=datetime(2026,1,1,tzinfo=timezone.utc)
    for index in range(180):
        price*=1.002
        candles.append(OHLCV(start+timedelta(hours=index),price,price,price,price,1000+index*20))
    trend=MarketRegime('trend',.8,.01,1.,10,8)
    for model in (VolatilityTrendModel(trend,48,.01),BreakoutLiquidityModel(trend,24,1.05)):
        result=model.fit(candles,fee_pct=.001,slippage_pct=.001).predict(candles)
        assert result['active_strategy'] in {'volatility_trend','breakout_liquidity'}
        assert result['action'] in {'BUY','HOLD','SELL'}
    defensive=DefensiveMeanReversionModel(MarketRegime('defensive',.2,-.01,1.,10,8),48,-1.5)
    assert defensive.fit(candles).predict(candles)['active_strategy']=='defensive_mean_reversion'


def test_canary_promotes_on_reconciled_trades_and_suspends_on_risk_halt(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc); started=now-timedelta(days=1)
    c.portfolio.mode=c.portfolio.book_type='LIVE'
    candidate=StrategyCandidate(user_id=c.user.id,candidate_id='canary',
        parameters=asdict(AdaptiveParameters()),status='LIVE_APPROVED_CANARY',
        metrics={'canary_started_at':started.isoformat()},tested_at=started)
    c.db.add(candidate)
    for index in range(10):
        c.db.add(Trade(portfolio_id=c.portfolio.id,symbol='BTC/EUR',side='SELL',quantity=.01,
            price=100.,fee=.01,slippage=0.,total_cost=1.,pnl=.10,mode='LIVE',
            created_at=started+timedelta(hours=index+1)))
    c.db.commit()
    assert review_live_canary(c.db,c.user.id,now)[0]['status']=='LIVE_APPROVED'
    candidate.status='LIVE_APPROVED_CANARY'; c.portfolio.risk_halted=True; c.db.commit()
    assert review_live_canary(c.db,c.user.id,now)[0]['status']=='LIVE_SUSPENDED'
    assert research_status(c.db,c.user.id,now)['counts']['LIVE_SUSPENDED']==1


def test_duplicate_live_canaries_are_repaired_to_one_controller(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc); c.portfolio.mode=c.portfolio.book_type='LIVE'
    params=asdict(AdaptiveParameters())
    c.db.add_all([
        StrategyCandidate(user_id=c.user.id,candidate_id='weak',parameters=params,
            status='LIVE_APPROVED_CANARY',metrics={'validation':{'sharpe_ratio':.2},
            'stress':{'expectancy':.1},'canary_started_at':now.isoformat()},tested_at=now),
        StrategyCandidate(user_id=c.user.id,candidate_id='strong',parameters=params,
            status='LIVE_APPROVED_CANARY',metrics={'validation':{'sharpe_ratio':1.},
            'stress':{'expectancy':1.},'canary_started_at':now.isoformat()},tested_at=now),
    ])
    c.db.commit()
    review_live_canary(c.db,c.user.id,now)
    statuses={row.candidate_id:row.status for row in c.db.query(StrategyCandidate).all()}
    assert statuses=={'weak':'PAPER_APPROVED','strong':'LIVE_APPROVED_CANARY'}


def test_canary_budget_is_one_position_and_5_percent_total_exposure():
    portfolio=SimpleNamespace(equity=100.)
    positions=[SimpleNamespace(quantity=.02,current_price=100.)]
    assert CANARY_MAX_POSITIONS==1 and CANARY_MAX_EXPOSURE_PCT==.05
    assert canary_entry_budget(portfolio,positions,50.)==3.
    assert canary_entry_budget(portfolio,positions,2.)==2.
    positions.append(SimpleNamespace(quantity=.03,current_price=100.))
    assert canary_entry_budget(portfolio,positions,50.)==0.


def test_shadow_ledger_is_restart_idempotent_and_never_creates_exchange_orders(setup_bot):
    c=setup_bot; c.risk.entry_strategy='auto'; c.risk.max_open_positions=1
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    records=[]
    for symbol_index in range(10):
        price=100.+symbol_index
        for index in range(730):
            price*=1.003
            records.append(MarketCandle(symbol=f'C{symbol_index}/EUR',timeframe='1h',
                timestamp=start+timedelta(hours=index),open=price,high=price,low=price,
                close=price,volume=100000.))
    c.db.bulk_save_objects(records)
    tested=start+timedelta(hours=700,minutes=1)
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='shadow-restart',
        parameters=asdict(AdaptiveParameters()),status='PAPER_APPROVED',metrics={},tested_at=tested))
    c.db.commit()
    now=start+timedelta(hours=731)
    assert advance_shadow_candidates(c.db,c.user.id,now)
    first=(c.db.query(ShadowRun).count(),c.db.query(ShadowTrade).count(),c.db.query(ShadowEquity).count())
    assert first[0]==1 and first[2]>0 and c.db.query(ExecutionOrder).count()==0
    assert advance_shadow_candidates(c.db,c.user.id,now)
    assert (c.db.query(ShadowRun).count(),c.db.query(ShadowTrade).count(),
            c.db.query(ShadowEquity).count())==first


def test_mutations_ignore_holdout_and_wait_for_complete_parent_pool():
    evaluated=[SimpleNamespace(candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        metrics={'development':{'expectancy':index,'total_return_pct':0},
                 'holdout':{'expectancy':-index}})
        for index,p in enumerate(generated_candidates())]
    assert derived_candidates(evaluated[:-1])==[]
    original=derived_candidates(evaluated)
    for index,row in enumerate(evaluated):
        row.metrics['generation_development']=row.metrics['development']
        row.metrics['development']={'expectancy':-1000*index}
        row.metrics['holdout']={'expectancy':1000*index}
    assert derived_candidates(evaluated)==original


def test_zero_drawdown_does_not_fail_forward_gate():
    good=dict(expectancy=1.,total_return_pct=.08,max_drawdown_pct=0.,
              closed_trades=40,risk_halted=False,top_five_profit_share=.25)
    assert shadow_promotion_decision(good,good,{'total_return_pct':0},8)['checks']['drawdown_within_5pct']


def test_shadow_rejects_concentrated_or_missing_profit_evidence():
    good=dict(expectancy=1.,total_return_pct=.08,max_drawdown_pct=-.01,
              closed_trades=40,risk_halted=False,top_five_profit_share=.25)
    for concentration in (.81,float('nan'),-1.):
        result=shadow_promotion_decision({**good,'top_five_profit_share':concentration},good,
                                        {'total_return_pct':0},.1)
        assert not result['live_authorized']
    del good['top_five_profit_share']
    assert not shadow_promotion_decision(good,good,{'total_return_pct':0},.1)['live_authorized']


def test_validation_window_failure_preserves_final_test_data(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=i),100.,100.,100.,100.,10000.) for i in range(1000)]
    calls=[]
    class FakeEngine:
        def __init__(self,*args,**kwargs): calls.append(kwargs)
        def run(self):
            return dict(expectancy=-1 if len(calls)==3 else 1,total_return_pct=.1,
                max_drawdown_pct=-.01,closed_trades=40,experiment={'data_sha256':'verified'})
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)
    result=research_next_candidate(c.db,c.user.id,data_snapshot={f'C{i}/EUR':rows for i in range(3)})
    assert len(calls)==3
    assert result.status=='REJECTED' and result.metrics['stopped_stage']=='validation_windows'
    assert result.metrics['holdout'] is None
    assert not result.metrics['checks']['validation_windows_positive']


def test_benchmark_cache_reuses_only_identical_snapshot_and_costs(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    calls=[]
    class FakeEngine:
        def __init__(self,*args,**kwargs): calls.append(kwargs)
        def run(self): return {'total_return_pct':len(calls)}
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)
    from dataclasses import replace
    risk=risk_manager_from_config(c.risk)
    data={}; cache={}; start=datetime(2026,1,1,tzinfo=timezone.utc); end=start+timedelta(days=2)
    first=research._momentum_benchmark(data,risk,500,start,end,cache)
    assert research._momentum_benchmark(data,risk,500,start,end,cache) is first
    assert len(calls)==1
    research._momentum_benchmark(data,replace(risk,fee_pct=risk.fee_pct*2),500,start,end,cache)
    research._momentum_benchmark(data,risk,500,start,end,cache,liquidate_end=False)
    research._momentum_benchmark({'other':[]},risk,500,start,end,cache)
    assert len(calls)==4


def test_live_pilot_suspends_at_loss_limit_before_ten_exits(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc); started=now-timedelta(minutes=5)
    c.portfolio.mode=c.portfolio.book_type='LIVE'
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='pilot-loss',
        parameters=asdict(AdaptiveParameters()),status='LIVE_APPROVED_CANARY',
        metrics={'canary_started_at':started.isoformat(),'canary_start_equity':500},tested_at=started))
    c.db.add(Trade(portfolio_id=c.portfolio.id,symbol='BTC/EUR',side='SELL',quantity=.1,
        price=100.,fee=.01,slippage=0.,total_cost=10.,pnl=-5.,mode='LIVE',created_at=now))
    c.db.commit()
    result=review_live_canary(c.db,c.user.id,now)[0]
    assert result['closed_round_trips']==1 and result['status']=='LIVE_SUSPENDED'
    assert '1%' in result['suspension_reason']


def test_shadow_rejections_are_retained_not_retested(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    parameters=AdaptiveParameters(); identity=candidate_id(parameters)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=i),100.,100.,100.,100.,10000.) for i in range(1100)]
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=identity,parameters=asdict(parameters),
        status='REJECTED',metrics={'protocol':{'end':start.isoformat()}},tested_at=start))
    c.db.add(ShadowRun(user_id=c.user.id,candidate_id=identity,version='retained',status='REJECTED',
        started_at=start,initial_cash=100,cash=99,equity=99,peak_equity=100,open_positions={},metrics={}))
    c.db.commit()
    monkeypatch.setattr(research,'_research_data',lambda db:{f'C{i}/EUR':rows for i in range(3)})
    monkeypatch.setattr(research,'generated_candidates',lambda:[parameters])
    monkeypatch.setattr(research,'derived_candidates',lambda evaluated:[])
    assert research_next_candidate(c.db,c.user.id) is None
    assert c.db.query(ShadowRun).one().version=='retained'


def test_new_forward_winner_promotes_automatically_even_with_legacy_manual_flag(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=i),100.,100.,100.,100.,10000.) for i in range(1000)]
    candidate=StrategyCandidate(user_id=c.user.id,candidate_id='manual-winner',parameters=asdict(AdaptiveParameters()),
        status='PAPER_APPROVED',metrics={'protocol':{'manual_live_approval_required':True}},tested_at=start)
    c.db.add(candidate); c.db.commit()
    good=dict(expectancy=1.,total_return_pct=.08,max_drawdown_pct=-.01,closed_trades=40,
              final_equity=108,ending_cash=108,trades=[],equity_curve=[],top_five_profit_share=.25)
    class FakeEngine:
        def __init__(self,*args,**kwargs): self.benchmark=kwargs['risk'].entry_strategy=='momentum'
        def run(self): return {**good,'total_return_pct':0 if self.benchmark else .08}
    monkeypatch.setattr(research,'_research_data',lambda db:{f'C{i}/EUR':rows for i in range(3)})
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)
    result=advance_shadow_candidates(c.db,c.user.id,start+timedelta(hours=1001))
    assert result[0]['status']=='LIVE_APPROVED_CANARY'
    assert candidate.metrics['shadow_promotion']['live_authorized'] is True
    assert approved_parameters(c.db,c.user.id,'LIVE')==asdict(AdaptiveParameters())
    assert c.db.query(ExecutionOrder).count()==0


def test_fresh_data_creates_and_resumes_bounded_next_generation(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    old_end=start+timedelta(hours=719)
    rows=[OHLCV(start+timedelta(hours=i),100.,100.,100.,100.,10000.) for i in range(1056)]
    for i in range(research.MAX_STRATEGY_IDENTITIES):
        c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=f'legacy-{i}',parameters=asdict(AdaptiveParameters()),
            status='REJECTED',metrics={'protocol':{'end':old_end.isoformat()}},tested_at=old_end))
    c.db.commit()
    children=[AdaptiveParameters(momentum_threshold=.033),AdaptiveParameters(momentum_threshold=.034)]
    monkeypatch.setattr(research,'derived_candidates',lambda evaluated,successive=False:children if successive else [])
    monkeypatch.setattr(research,'_research_data',lambda db:{f'C{i}/EUR':rows for i in range(3)})
    class FakeEngine:
        def __init__(self,*args,**kwargs): pass
        def run(self): return dict(expectancy=-1.,total_return_pct=-.01,max_drawdown_pct=-.02,
            closed_trades=40,experiment={'data_sha256':'fresh'})
    monkeypatch.setattr(research,'PortfolioBacktestEngine',FakeEngine)
    first=research_next_candidate(c.db,c.user.id)
    second=research_next_candidate(c.db,c.user.id)
    assert first.candidate_id==candidate_id(children[0])
    assert second.candidate_id==candidate_id(children[1])
    for candidate in (first,second):
        assert candidate.metrics['protocol']['generation']==1
        assert datetime.fromisoformat(candidate.metrics['protocol']['holdout_start'])>old_end
        assert candidate.status=='REJECTED'
    assert c.db.query(StrategyCandidate).count()==research.MAX_STRATEGY_IDENTITIES+2


def test_losing_live_canary_is_suspended(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc); started=now-timedelta(days=1)
    c.portfolio.mode=c.portfolio.book_type='LIVE'
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='losing',parameters=asdict(AdaptiveParameters()),
        status='LIVE_APPROVED_CANARY',metrics={'canary_started_at':started.isoformat()},tested_at=started))
    for i in range(10):
        c.db.add(Trade(portfolio_id=c.portfolio.id,symbol='BTC/EUR',side='SELL',quantity=.01,
            price=100.,fee=.01,slippage=0.,total_cost=1.,pnl=-.1,mode='LIVE',created_at=now))
    c.db.commit()
    assert review_live_canary(c.db,c.user.id,now)[0]['status']=='LIVE_SUSPENDED'
