from dataclasses import asdict, replace
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from app.exchanges.base import OHLCV
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.strategies import MarketRegime, IntradayBreakoutModel, classify_market_regime
from app.ml.strategy_factory import (StrategyDefinition, candidate_id, candidate_parameters,
    definition_from_parameters, candidate_factory, candidate_timeframe, candidate_risk,
    generated_candidates, derived_candidates)
from app.services.market_data import completed_candles, candle_boundary, archive, load_history
from app.services.strategy_research import research_next_candidate, advance_shadow_candidates, research_status
from app.services.research_market_data import collect_intraday_history
from app.models.portfolio import StrategyCandidate, MarketCandle, ShadowRun, ExecutionOrder, Signal, Trade
from tests.test_autonomous import setup_bot, run
from tests.test_research import risk, Buyer


def definition(**overrides):
    return StrategyDefinition(**{'family':'intraday_breakout','lookback':24,'threshold':.01,
                                'volume_ratio':1.5,'timeframe':'15m',**overrides})


def quarter_rows(count=120,start=None,drift=0.,volume=10000.):
    start=start or datetime(2025,1,1,tzinfo=timezone.utc)
    return [OHLCV(start+timedelta(minutes=15*i),100*(1+drift)**i,100*(1+drift)**i,
                  100*(1+drift)**i,100*(1+drift)**i,volume) for i in range(count)]


def test_quarter_hour_completion_boundary_and_unfinished_rejection():
    now=datetime(2025,1,1,12,22,tzinfo=timezone.utc)
    rows=quarter_rows(3,start=now.replace(minute=0))
    assert len(completed_candles(rows,'15m',now))==1
    assert candle_boundary(now,'15m')==now.replace(minute=15)
    assert candle_boundary(now,'15m',ceil=True)==now.replace(minute=30)
    assert candle_boundary(now.replace(minute=15),'15m',ceil=True)==now.replace(minute=15)
    with pytest.raises(ValueError,match='incomplete'):
        PortfolioBacktestEngine({'BTC/EUR':[OHLCV(candle_boundary(datetime.now(timezone.utc),'15m'),100,100,100,100,1)]},
            model_factory=lambda _:Buyer(),select_assets=False,timeframe='15m')


def test_intraday_definition_has_distinct_identity_and_preserves_hourly_exports():
    p=definition()
    assert candidate_timeframe(p)=='15m' and 'timeframe=15m' in candidate_id(p)
    assert definition_from_parameters(candidate_parameters(p))==p
    hourly=StrategyDefinition('breakout_liquidity',24,volume_ratio=1.5)
    assert 'timeframe' not in candidate_parameters(hourly)
    assert 'timeframe' not in candidate_id(hourly)
    assert definition_from_parameters(candidate_parameters(hourly))==hourly
    assert isinstance(candidate_factory(p)('BTC/EUR'),IntradayBreakoutModel)
    assert len([p for p in generated_candidates() if candidate_timeframe(p)=='15m'])==3


@pytest.mark.parametrize('overrides',[{'timeframe':'1h'},{'lookback':7},{'lookback':97},
                                    {'threshold':0},{'volume_ratio':3.1}])
def test_intraday_grammar_rejects_unsupported_parameters(overrides):
    with pytest.raises(ValueError): definition(**overrides)


def test_intraday_mutations_remain_bounded_and_receive_a_slot():
    evaluated=[SimpleNamespace(candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        metrics={'development':{'expectancy':i}}) for i,p in enumerate(generated_candidates())]
    children=derived_candidates(evaluated)
    assert len(children)<=8
    assert any(candidate_timeframe(p)=='15m' for p in children)
    assert all(definition_from_parameters(candidate_parameters(p))==p for p in children)


def test_regime_keeps_three_and_24_hour_meaning_on_quarter_hour_data():
    quarters=quarter_rows(97,drift=.0005)
    hourly=quarters[::4]
    a=classify_market_regime({f'C{i}':quarters for i in range(3)},timeframe='15m')
    b=classify_market_regime({f'C{i}':hourly for i in range(3)})
    assert a.name==b.name=='trend'
    assert a.median_three_hour_return==pytest.approx(b.median_three_hour_return)
    assert classify_market_regime({f'C{i}':quarters[-25:] for i in range(3)},timeframe='15m').name=='insufficient'


def test_intraday_entry_requires_regime_volume_strength_and_cost_margin():
    rows=quarter_rows(97,drift=.001,volume=100.)
    rows[-1].volume=500.
    model=IntradayBreakoutModel(MarketRegime('trend',1,.01,1,3,3)).fit(rows,fee_pct=.001,slippage_pct=.001)
    assert model.predict(rows)['action']=='BUY'
    assert model.predict(rows)['signal_timeframe']=='15m'
    assert model.fit(rows,fee_pct=.01,slippage_pct=.001).predict(rows)['action']=='HOLD'
    model.fit(rows,fee_pct=.001,slippage_pct=.001)
    rows[-1].volume=100.
    assert model.predict(rows)['action']=='HOLD'
    rows[-1].volume=500.
    model.set_regime(MarketRegime('defensive',0,0,1,3,3))
    assert model.predict(rows)['action']=='HOLD'


def test_quarter_hour_replay_uses_past_evidence_next_bar_and_actual_close_times():
    rows=quarter_rows(5)
    rows[2]=OHLCV(rows[2].timestamp,100,110,90,100,10000)
    seen=[]
    class Spy(Buyer):
        def predict(self,past):
            seen.append(past[-1].timestamp)
            return super().predict(past)
    result=PortfolioBacktestEngine({'BTC/EUR':rows},model_factory=lambda _:Spy(),select_assets=False,
        timeframe='15m',risk=risk()).run(warmup=2)
    assert result['trades'][0]['timestamp']==rows[2].timestamp
    assert seen[0]+timedelta(minutes=15)==result['trades'][0]['timestamp']
    assert result['trades'][1]['timestamp']==rows[2].timestamp+timedelta(minutes=15)
    assert result['trades'][1]['price']==97
    assert result['evaluation_end']==rows[-1].timestamp+timedelta(minutes=15)
    assert result['timeframe']=='15m' and 'bar_mean_return_interval' in result
    assert 'hourly_mean_return_interval' not in result
    assert result['experiment']['configuration']['timeframe']=='15m'
    assert result['final_equity']==pytest.approx(500+sum(t['pnl'] or 0 for t in result['trades']))


def test_intraday_daily_aggregation_requires_96_real_bars():
    engine=PortfolioBacktestEngine({'BTC/EUR':quarter_rows(120)},model_factory=lambda _:Buyer(),select_assets=False,timeframe='15m')
    assert len(engine.daily['BTC/EUR'])==1
    assert engine.daily['BTC/EUR'][0].volume==960000
    assert engine._daily(quarter_rows(24))==[]


def test_intraday_loss_windows_and_volatility_horizon_keep_real_duration():
    configured=risk(daily_loss_pct=.05)
    engine=PortfolioBacktestEngine({},model_factory=lambda _:Buyer(),select_assets=False,timeframe='15m',risk=configured)
    engine.curve=[100.]*30+[94.]*80; engine.halted=False
    engine._rolling_loss_halt(90.)
    assert engine.halted  # 24 hours ago was 100, not the 94 from six hours ago.
    assert candidate_risk(configured,definition()).prediction_horizon==configured.prediction_horizon*4


def test_intraday_sharpe_annualization_matches_96_bars_per_day():
    engine=PortfolioBacktestEngine({},model_factory=lambda _:Buyer(),select_assets=False,timeframe='15m',risk=risk())
    returns=np.array([.001,.002,-.001,.003])
    engine.curve=np.r_[500.,500*np.cumprod(1+returns)].tolist()
    engine.trades=[]; engine.fees=0; engine.turnover=0; engine.exposures=[]; engine.halted=False
    result=engine._result([],{}, {})
    assert result['sharpe_ratio']==pytest.approx(returns.mean()/returns.std(ddof=1)*np.sqrt(365*96))


def test_intraday_gaps_are_preserved_and_restart_signal_warmup():
    rows=quarter_rows(12)
    sparse=rows[:3]+rows[6:]
    with pytest.raises(ValueError,match='contiguous'):
        PortfolioBacktestEngine({'BTC/EUR':sparse},model_factory=lambda _:Buyer(),select_assets=False,timeframe='15m')
    result=PortfolioBacktestEngine({'BTC/EUR':sparse},model_factory=lambda _:Buyer(),select_assets=False,
        timeframe='15m',allow_no_trade_gaps=True,risk=risk()).run(warmup=2)
    assert not any(rows[3].timestamp<=t['timestamp']<rows[6].timestamp for t in result['trades'])
    assert any('No-trade gaps preserved' in reason for reason in result['data_limitations'])


@pytest.mark.asyncio
async def test_intraday_collection_is_completed_idempotent_and_avoids_repeated_fetches(setup_bot):
    c=setup_bot
    end=candle_boundary(datetime.now(timezone.utc),'15m')
    rows=quarter_rows(721,start=end-timedelta(minutes=15*720))
    exchange=SimpleNamespace(get_ohlcv=AsyncMock(return_value=rows))
    first=await collect_intraday_history(c.db,exchange,['BTC/EUR','BTC/EUR'])
    assert first['updated']==['BTC/EUR'] and not first['errors']
    assert c.db.query(MarketCandle).filter_by(timeframe='15m').count()==720
    second=await collect_intraday_history(c.db,exchange,['BTC/EUR'])
    assert second['current']==['BTC/EUR'] and exchange.get_ohlcv.await_count==1
    history=await load_history(c.db,exchange,'BTC/EUR',timeframe='15m',refresh_if_needed=True)
    assert len(history)==720 and exchange.get_ohlcv.await_count==1
    assert c.db.query(ExecutionOrder).count()==0


def test_intraday_research_uses_its_own_dataset_and_sizing_horizon(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    quarters={f'C{i}/EUR':quarter_rows(1000) for i in range(3)}
    calls=[]
    class Engine:
        def __init__(self,*args,**kwargs): calls.append(kwargs)
        def run(self,**kwargs):
            assert kwargs['warmup']==97
            return {'expectancy':-1,'experiment':{'data_sha256':'quarters'}}
    monkeypatch.setattr(research,'PortfolioBacktestEngine',Engine)
    candidate=research_next_candidate(c.db,c.user.id,timeframe_snapshots={'15m':quarters,'1h':{}})
    assert candidate.parameters['timeframe']=='15m' and candidate.status=='REJECTED'
    assert calls[0]['timeframe']=='15m' and calls[0]['candles_by_symbol'] is quarters
    assert calls[0]['risk'].prediction_horizon==c.risk.prediction_horizon*4
    assert candidate.metrics['protocol']['timeframe']=='15m'
    assert research_status(c.db,c.user.id)['candidates'][0]['timeframe']=='15m'


def test_intraday_shadow_starts_at_next_quarter_hour_and_never_uses_hourly_data(setup_bot,monkeypatch):
    c=setup_bot
    import app.services.strategy_research as research
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    tested=start+timedelta(minutes=15*990+1)
    p=definition()
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        status='PAPER_APPROVED',metrics={},tested_at=tested)); c.db.commit()
    data={f'C{i}/EUR':quarter_rows(1000) for i in range(3)}
    calls=[]
    class Engine:
        def __init__(self,*args,**kwargs): calls.append(kwargs)
        def run(self,**kwargs):
            return dict(expectancy=0.,total_return_pct=0.,max_drawdown_pct=0.,closed_trades=0,
                        final_equity=500,ending_cash=500,trades=[],equity_curve=[],top_five_profit_share=0.)
    monkeypatch.setattr(research,'PortfolioBacktestEngine',Engine)
    result=advance_shadow_candidates(c.db,c.user.id,start+timedelta(minutes=15*1001),timeframe_snapshots={'15m':data})
    assert result and all(call['timeframe']=='15m' for call in calls)
    assert all(call['start_date']==candle_boundary(tested,'15m',ceil=True) for call in calls)
    assert c.db.query(ShadowRun).one().started_at.replace(tzinfo=timezone.utc)==candle_boundary(tested,'15m',ceil=True)
    assert c.db.query(ExecutionOrder).count()==0


@pytest.mark.asyncio
async def test_runtime_selects_approved_intraday_timeframe_and_records_it(setup_bot,monkeypatch):
    c=setup_bot; c.risk.entry_strategy='auto'; c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc)
    p=definition()
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        status='PAPER_APPROVED',metrics={},tested_at=datetime.now(timezone.utc))); c.db.commit()
    end=candle_boundary(datetime.now(timezone.utc),'15m')
    rows=quarter_rows(120,start=end-timedelta(minutes=15*120))
    async def ohlcv(symbol,timeframe='1h',limit=720):
        assert timeframe=='15m'
        return rows
    c.exchange.get_ohlcv.side_effect=ohlcv
    await run(c)
    assert c.state.health=='HEALTHY',c.state.last_error
    signal=c.db.query(Signal).one()
    assert signal.features['signal_timeframe']=='15m'
    assert signal.features['diagnostics']['signal_timeframe']=='15m'
    assert signal.action=='HOLD' and c.db.query(Trade).count()==0
    assert c.state.candidate_status['BTC/EUR']['history_eligible']
    await run(c)
    assert c.exchange.get_ohlcv.await_count==1
    assert c.db.query(Signal).count()==1


@pytest.mark.asyncio
async def test_qualified_intraday_buy_can_enter_without_hourly_candles_and_cannot_duplicate(setup_bot):
    c=setup_bot; c.risk.entry_strategy='auto'; c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR','ETH/EUR','SOL/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc)
    p=definition()
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id=candidate_id(p),parameters=candidate_parameters(p),
        status='PAPER_APPROVED',metrics={},tested_at=datetime.now(timezone.utc))); c.db.commit()
    end=candle_boundary(datetime.now(timezone.utc),'15m')
    rows=quarter_rows(120,start=end-timedelta(minutes=15*120),drift=.0015)
    rows[-1].volume=30000
    async def ohlcv(symbol,timeframe='1h',limit=720):
        assert timeframe=='15m'
        return rows
    c.exchange.get_ohlcv.side_effect=ohlcv
    await run(c)
    assert c.state.health=='HEALTHY',c.state.last_error
    assert c.db.query(Trade).count()==1
    assert all(signal.action=='BUY' for signal in c.db.query(Signal).all())
    assert c.db.query(MarketCandle).filter_by(timeframe='1h').count()==0
    await run(c)
    assert c.db.query(Trade).count()==1
    assert c.exchange.get_ohlcv.await_count==3


def test_offline_intraday_protocol_preserves_timeframe_and_seals_holdout(tmp_path):
    import csv, hashlib, json
    from app.ml.research import register, run_experiment, freeze, load_dataset
    rows=quarter_rows(300)
    source=tmp_path/'quarters.csv'
    with source.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['timestamp','open','high','low','close','volume'])
        writer.writeheader()
        for row in rows: writer.writerow(vars(row))
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'timeframe':'15m','assets':[{'symbol':'BTC/EUR','file':source.name,
        'source':'Synthetic fixture only','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    with pytest.raises(ValueError,match='agree'):
        load_dataset(manifest,timeframe='1h')
    protocol=tmp_path/'protocol-input.json'
    protocol.write_text(json.dumps({'timeframe':'15m','risk':asdict(risk()),
        'development_start':rows[120].timestamp.isoformat(),'holdout_start':rows[240].timestamp.isoformat(),
        'end':(rows[-1].timestamp+timedelta(minutes=15)).isoformat(),
        'candidates':['intraday-breakout'],'select_assets':False,'warmup':97}))
    directory=tmp_path/'registered'
    register(manifest,protocol,directory)
    result=json.loads(run_experiment(directory,candidate='intraday-breakout').read_text())['result']
    assert result['timeframe']=='15m'
    assert result['strategy_parameters']['timeframe']=='15m'
    assert result['experiment']['configuration']['risk']['prediction_horizon']==risk().prediction_horizon*4
    assert result['evaluation_end']==str(rows[240].timestamp)
    assert not (directory/'holdout-consumed.json').exists()
    freeze(directory,'intraday-breakout')
    run_experiment(directory,stage='holdout',candidate='intraday-breakout')
    with pytest.raises(FileExistsError):
        run_experiment(directory,stage='holdout',candidate='intraday-breakout')
