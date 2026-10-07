from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

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
    assert len(candidates)==21 and len({candidate_id(p) for p in candidates})==21
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


def test_shadow_promotion_requires_forward_duration_trades_and_stress():
    good=dict(expectancy=1.,total_return_pct=.08,max_drawdown_pct=-.03,
              closed_trades=40,risk_halted=False)
    benchmark={**good,'total_return_pct':.03}
    immature=shadow_promotion_decision(good,good,benchmark,observed_days=2)
    assert immature['decision']=='PAPER_APPROVED' and not immature['live_authorized']
    approved=shadow_promotion_decision(good,good,benchmark,observed_days=8)
    assert approved['decision']=='LIVE_APPROVED_CANARY' and approved['live_authorized']
    rejected=shadow_promotion_decision({**good,'expectancy':-1},good,benchmark,observed_days=31)
    assert rejected['decision']=='REJECTED' and not rejected['live_authorized']


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


def test_canary_budget_is_two_positions_and_25_percent_total_exposure():
    portfolio=SimpleNamespace(equity=100.)
    positions=[SimpleNamespace(quantity=.1,current_price=100.)]
    assert CANARY_MAX_POSITIONS==2 and CANARY_MAX_EXPOSURE_PCT==.25
    assert canary_entry_budget(portfolio,positions,50.)==15.
    assert canary_entry_budget(portfolio,positions,5.)==5.
    positions.append(SimpleNamespace(quantity=.15,current_price=100.))
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
