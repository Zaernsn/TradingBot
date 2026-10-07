from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import ccxt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.models.user import User
from app.models.portfolio import Portfolio, Position, Trade, Signal, BotState, RiskConfig
from app.services.asset_selector import AssetSelector
from app.services.risk_service import risk_manager_from_config
from app.services.bot_service import BotOrchestrator
from app.exchanges.universe import CURATED_PAIRS


def candles(drift=0.01, swing=0.02, count=31, objects=False, timeframe="1h"):
    price = 100.0
    result = []
    for i in range(count):
        price *= 1 + drift + (swing if i % 2 else -swing)
        period=timedelta(days=1) if timeframe=='1d' else timedelta(hours=1)
        end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
        if timeframe=='1d': end=end.replace(hour=0)
        row = dict(timestamp=end-period*(count-i),open=price,high=price+1,low=max(.001,price-1),close=price,volume=1000.0)
        result.append(SimpleNamespace(**row) if objects else row)
    return result


def test_selector_ranks_and_filters():
    selector = AssetSelector()
    data = {'slow': candles(.003, .005), 'fast': candles(.02, objects=True),
            'flat': candles(0, 0), 'wild': candles(0, .4), 'short': candles(count=5),
            'invalid': [{'close': float('nan'), 'volume': 1}] * 31}
    assert selector.select(data) == ['fast', 'slow']
    assert selector.select(data, 1) == ['fast']
    assert selector.select({}) == []


def test_automatic_watchlist_monitors_flat_markets_without_approving_entries():
    selector=AssetSelector()
    data={'BTC/EUR':candles(0,0),'ETH/EUR':candles(0,0)}
    assert selector.select_watchlist(data,2,False,limit=2)==[]
    assert selector.select_watchlist(data,2,False,limit=2,monitor_all=True)==['BTC/EUR','ETH/EUR']


@pytest.fixture
def setup_bot(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr('app.db.session.SessionLocal', factory)
    db = factory()
    user = User(email='bot@example.com', hashed_password='unused')
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, cash=500, equity=500, mode='PAPER')
    risk = RiskConfig(user_id=user.id, memecoins_enabled=False, max_position_pct=1, max_open_positions=3, max_total_exposure_pct=1, max_correlated_exposure_pct=1)
    state = BotState(user_id=user.id, is_running=True)
    db.add_all([portfolio, risk, state]); db.commit()
    async def ohlcv(symbol,timeframe='1h',limit=100):
        return candles(objects=True,timeframe=timeframe,count=61)
    exchange = SimpleNamespace(get_ohlcv=AsyncMock(side_effect=ohlcv),
                               get_ticker=AsyncMock(return_value=SimpleNamespace(last=100.0,bid=100.,ask=100.)), close=AsyncMock())
    actions = {}
    class Model:
        def __init__(self, name): self.name, self.is_fitted = name, True
        def load(self): pass
        def needs_retrain(self,*args): return False
        def predict(self, data):
            symbol = next((s for s in CURATED_PAIRS if s.replace('/', '_') in self.name), '')
            return dict(action=actions.get(symbol, 'BUY'), probability=.8, confidence=.6)
    monkeypatch.setattr('app.services.bot_service.SignalModel', Model)
    bot = BotOrchestrator()
    monkeypatch.setattr(bot, '_get_exchange', lambda mode: exchange)
    yield SimpleNamespace(db=db, factory=factory, user=user, portfolio=portfolio, risk=risk, state=state,
                          exchange=exchange, bot=bot, actions=actions)
    db.close(); engine.dispose()


async def run(ctx):
    await ctx.bot._run_iteration(ctx.user.id, ctx.portfolio.id, ctx.risk.id)
    ctx.db.expire_all()


@pytest.mark.asyncio
async def test_multi_asset_limits_equity_fees_and_no_duplicate_entries(setup_bot):
    c = setup_bot
    await run(c)
    positions = c.db.query(Position).all()
    assert len(positions) == 3
    assert len(c.state.watchlist) == 3
    assert c.state.health == 'HEALTHY', c.state.last_error
    assert c.portfolio.cash >= 0
    assert c.portfolio.equity == pytest.approx(c.portfolio.cash + sum(p.quantity * p.current_price for p in positions))
    assert all(t.total_cost <= 500 / 3 + 1e-9 for t in c.db.query(Trade).all())
    await run(c)
    assert c.db.query(Trade).count() == 3
    daily_calls = [call for call in c.exchange.get_ohlcv.call_args_list if call.kwargs.get('timeframe') == '1d']
    assert len(daily_calls) == 5
    assert all(key[0] == c.user.id for key in c.bot.models)


@pytest.mark.asyncio
async def test_daily_limit_is_shared_across_symbols(setup_bot):
    c=setup_bot; c.risk.max_daily_trades=1; c.db.commit()
    await run(c)
    assert c.db.query(Trade).count() == 1


@pytest.mark.asyncio
async def test_rotated_out_position_is_closed_and_frees_slot(setup_bot):
    c=setup_bot
    c.risk.max_open_positions=1
    c.state.watchlist=['ETH/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.db.add(Position(portfolio_id=c.portfolio.id, symbol='BTC/EUR', quantity=1, avg_entry_price=120, current_price=120))
    c.portfolio.cash=380; c.db.commit()
    await run(c)
    trades=c.db.query(Trade).order_by(Trade.id).all()
    assert [(t.symbol,t.side) for t in trades] == [('BTC/EUR','SELL'),('ETH/EUR','BUY')], c.state.last_error
    assert c.db.query(Position).one().symbol == 'ETH/EUR'


@pytest.mark.asyncio
async def test_stop_exit_does_not_reenter_same_cycle(setup_bot):
    c=setup_bot
    c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.db.add(Position(portfolio_id=c.portfolio.id, symbol='BTC/EUR', quantity=1, avg_entry_price=120, current_price=120))
    c.portfolio.cash=380; c.db.commit()
    await run(c)
    assert c.db.query(Trade).one().side == 'SELL'
    assert c.db.query(Position).count() == 0


@pytest.mark.asyncio
async def test_symbol_failure_does_not_block_other_assets(setup_bot):
    c=setup_bot
    async def ticker(symbol):
        if symbol == 'ADA/EUR': raise RuntimeError('ticker unavailable')
        return SimpleNamespace(last=100.0,bid=100.,ask=100.)
    c.exchange.get_ticker.side_effect=ticker
    await run(c)
    assert c.db.query(Position).count() == 2
    assert c.state.health == 'DEGRADED'
    assert 'ADA/EUR' in c.state.last_error


@pytest.mark.asyncio
async def test_emergency_stop_during_fetch_prevents_entries(setup_bot):
    c=setup_bot
    c.state.watchlist=['BTC/EUR']; c.state.watchlist_updated_at=datetime.now(timezone.utc); c.db.commit()
    async def ticker(symbol):
        with c.factory() as other:
            state=other.query(BotState).one(); state.is_running=False; other.commit()
        return SimpleNamespace(last=100.0,bid=100.,ask=100.)
    c.exchange.get_ticker.side_effect=ticker
    await run(c)
    assert c.db.query(Trade).count() == 0
    assert not c.state.is_running


@pytest.mark.asyncio
async def test_live_mode_cannot_create_simulated_live_trades(setup_bot):
    c=setup_bot; c.portfolio.mode='LIVE'; c.db.commit()
    await run(c)
    assert c.state.health == 'ERROR'
    assert c.db.query(Trade).count() == 0
    c.exchange.get_ticker.assert_not_called()


@pytest.mark.asyncio
async def test_stale_watchlist_refreshes_and_retains_on_total_failure(setup_bot):
    c=setup_bot
    c.state.watchlist=['ETH/EUR']; old=datetime.now(timezone.utc)-timedelta(days=2)
    c.state.watchlist_updated_at=old; c.db.commit()
    c.exchange.get_ohlcv.side_effect=RuntimeError('offline')
    await run(c)
    assert c.state.watchlist == ['ETH/EUR']
    assert c.state.watchlist_updated_at.replace(tzinfo=timezone.utc) == old
    assert c.state.health == 'DEGRADED'


@pytest.mark.asyncio
async def test_recent_verified_watchlist_remains_available_during_refresh_failure(setup_bot):
    c=setup_bot
    c.risk.memecoins_enabled=True
    recent=datetime.now(timezone.utc)-timedelta(hours=1)
    c.state.watchlist=['ETH/EUR']; c.state.watchlist_updated_at=recent; c.db.commit()
    c.exchange.get_ohlcv.side_effect=RuntimeError('offline')
    await run(c)
    assert c.state.watchlist==['ETH/EUR']
    assert c.state.watchlist_updated_at.replace(tzinfo=timezone.utc)==recent
    assert c.state.discovery_stats['selection_available'] is True
    assert c.state.discovery_stats['selection_refreshed'] is False


def test_slot_budget_and_position_cap(setup_bot):
    c=setup_bot; c.risk.max_open_positions=5; c.risk.max_position_pct=.5
    risk=risk_manager_from_config(c.risk)
    assert risk.slot_budget(500)==100
    assert risk.position_size(500,100)==1
    risk.max_position_pct=.1
    assert risk.position_size(500,100)==.5
    assert risk.position_size(500,0)==0

def test_database_rejects_duplicate_open_position(setup_bot):
    from sqlalchemy.exc import IntegrityError
    c=setup_bot
    def position(quantity):
        return Position(portfolio_id=c.portfolio.id,symbol='BTC/EUR',quantity=quantity,avg_entry_price=100,current_price=100)
    c.db.add_all([position(0),position(0),position(1)]); c.db.commit()
    c.db.add(position(1))
    with pytest.raises(IntegrityError): c.db.commit()
    c.db.rollback()


@pytest.mark.asyncio
async def test_buy_marks_equity_at_market_including_slippage(setup_bot):
    c=setup_bot
    await run(c)
    positions=c.db.query(Position).all()
    assert all(p.current_price==100 for p in positions)
    assert all(p.unrealized_pnl < 0 for p in positions)
    assert c.portfolio.equity == pytest.approx(500-sum(t.fee+t.slippage*t.quantity for t in c.db.query(Trade).all()))


@pytest.mark.asyncio
async def test_same_candle_buy_retries_after_transient_pre_submission_failure(setup_bot, monkeypatch):
    c=setup_bot
    c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR']
    c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.db.commit()
    original=c.bot._execution
    attempts=0

    async def flaky(*args, **kwargs):
        nonlocal attempts
        if args[5].value == 'BUY' and attempts == 0:
            attempts += 1
            raise ccxt.NetworkError('temporary private preflight failure')
        attempts += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(c.bot,'_execution',flaky)
    await run(c)
    assert c.db.query(Trade).count()==0
    assert c.state.entry_decisions['BTC/EUR']['retryable'] is True
    assert c.state.entry_decisions['BTC/EUR']['code']=='execution_retry'
    first_signal_count=c.db.query(Signal).count()

    decisions=dict(c.state.entry_decisions)
    decision=dict(decisions['BTC/EUR'])
    decision['retry_after']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    decisions['BTC/EUR']=decision
    c.state.entry_decisions=decisions
    c.db.commit()
    await run(c)

    assert c.db.query(Trade).count()==1
    assert c.db.query(Position).one().symbol=='BTC/EUR'
    assert c.db.query(Signal).count()==first_signal_count


@pytest.mark.asyncio
async def test_positive_scoring_hold_cannot_enter(setup_bot):
    c=setup_bot
    c.risk.max_open_positions=1
    c.state.watchlist=['BTC/EUR']
    c.state.watchlist_updated_at=datetime.now(timezone.utc)
    c.actions['BTC/EUR']='HOLD'
    c.db.commit()
    await run(c)
    assert c.db.query(Trade).count()==0
    assert c.db.query(Position).count()==0
