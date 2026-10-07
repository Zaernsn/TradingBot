from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
import pytest
from app.services.momentum_policy import depth_capacity, fast_meme_preset
from app.ml.strategies import FastMomentumModel, rank_entries
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.evaluation import PromotionPolicy, promotion_report
from app.services.risk_service import RiskManager
from app.exchanges.base import OHLCV
from tests.test_autonomous import setup_bot, run, candles
from app.models.portfolio import Signal, Trade
from unittest.mock import AsyncMock


def test_depth_capacity_uses_exit_liquidity_and_rejects_bad_data():
    book={'asks':[[100,100],[110,10000]],'bids':[[99.9,20],[90,10000]]}
    assert depth_capacity(book,100,99.9,.003)==1
    assert depth_capacity({'asks':book['asks'],'bids':[]},100,99.9,.003)==0
    with pytest.raises(ValueError):
        depth_capacity({'asks':[[100,float('nan')]],'bids':[]},100,99,.003)


def test_preset_preserves_capital_and_stricter_liquidity_limits():
    config=SimpleNamespace(max_invest_per_trade_eur=20,max_position_pct=.25,
        memecoin_min_daily_volume_eur=1e6,memecoin_max_spread_pct=.001,max_holding_hours=12)
    fast_meme_preset(config)
    assert config.entry_strategy=='fast_momentum' and config.buy_probability_threshold==.4
    assert config.max_invest_per_trade_eur==20 and config.max_position_pct==.25
    assert config.memecoin_min_daily_volume_eur==1e6 and config.memecoin_max_spread_pct==.001
    assert config.max_holding_hours==12


def test_ranking_prefers_current_opportunity_not_watchlist_order():
    assert rank_entries(['A','B','C'],{'A':{'opportunity_score':1},'B':{'opportunity_score':3},
        'C':{'opportunity_score':float('nan')}})==['B','A','C']


def test_saved_fast_strategy_is_used_by_backtest_and_core_entries_excluded():
    start=datetime(2024,1,1,tzinfo=timezone.utc)
    rows=[OHLCV(start+timedelta(hours=i),100,103,99,102 if i%2 else 100,10000) for i in range(40)]
    risk=RiskManager(.2,.03,.06,.0026,10,None,12,entry_strategy='fast_momentum')
    engine=PortfolioBacktestEngine({'BTC/EUR':rows},risk=risk,select_assets=False)
    assert isinstance(engine.model_factory('BTC/EUR'),FastMomentumModel)
    assert engine.run(warmup=30)['num_trades']==0


def test_no_calendar_wait_does_not_skip_evidence_requirements():
    assert PromotionPolicy().min_forward_days==0
    good=dict(expectancy=1.,hourly_mean_return_interval={'low':.001},max_drawdown_pct=-.02,
        closed_trades=200,candidate_id='same',stage='holdout',stress_passed=True,benchmark_advantage=True,
        observed_days=1,version_consistent=True,cost_overrun_pct=0.,unresolved_orders=0)
    assert promotion_report(good,good)['decision']=='READY_FOR_SUPERVISED_ACCEPTANCE'
    assert promotion_report(good,{**good,'closed_trades':0})['decision']=='NO_GO'
    assert not promotion_report(good,good)['live_authorized']


@pytest.mark.asyncio
async def test_runtime_switches_from_model_to_fast_on_same_candle(setup_bot,monkeypatch):
    c=setup_bot
    rows=candles(drift=0,swing=0,count=40,objects=True)
    rows[-1].close=102.; rows[-1].high=103.; rows[-1].volume=2000.
    c.risk.entry_strategy='fast_momentum'
    c.risk.buy_probability_threshold=.95  # Must not affect rule-based entries.
    c.risk.memecoins_enabled=True
    c.state.watchlist=['DOGE/EUR']
    c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.db.add(Signal(portfolio_id=c.portfolio.id,symbol='DOGE/EUR',model='old-model',
        action='HOLD',probability=.5,confidence=0,features={'candle_timestamp':rows[-1].timestamp.isoformat()}))
    c.db.commit()
    monkeypatch.setattr('app.services.bot_service.load_history',AsyncMock(return_value=rows))
    monkeypatch.setattr('app.services.bot_service.check_liquidity',AsyncMock(return_value=(1000000,.001)))
    await run(c)
    buys=c.db.query(Trade).filter_by(side='BUY').all()
    assert len(buys)==1 and buys[0].symbol=='DOGE/EUR',c.state.last_error
    assert 'fast_momentum' in buys[0].reason
    await run(c)
    assert c.db.query(Trade).filter_by(side='BUY').count()==1
