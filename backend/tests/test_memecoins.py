from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from tests.test_autonomous import setup_bot, candles, run
from tests.test_settings import client, _auth_header
from app.services.memecoin_service import eligible_universe, check_liquidity, memecoin_budget
from app.services.risk_service import risk_manager_from_config, entry_budget
from app.exchanges.universe import CURATED_PAIRS, MEMECOIN_PAIRS
from app.models.portfolio import Position


def test_memecoin_watchlist_is_independent_of_position_slots():
    from app.services.asset_selector import AssetSelector
    assert len(MEMECOIN_PAIRS) == len(set(MEMECOIN_PAIRS)) == 30
    data = {s: candles() for s in CURATED_PAIRS + MEMECOIN_PAIRS}
    selected = AssetSelector().select_watchlist(data, 2, True)
    assert len([s for s in selected if s in MEMECOIN_PAIRS]) == 28
    assert len([s for s in selected if s in CURATED_PAIRS]) == 2
    assert len(AssetSelector().select_watchlist(data, 2, False)) == 2
    assert all(s in MEMECOIN_PAIRS for s in selected[:28])
    limited = {s: candles() for s in CURATED_PAIRS + MEMECOIN_PAIRS[:12]}
    assert sum(s in MEMECOIN_PAIRS for s in AssetSelector().select_watchlist(limited, 20, True)) == 12


def test_twenty_position_risk_budget(setup_bot):
    c = setup_bot
    c.risk.max_open_positions = 20
    risk = risk_manager_from_config(c.risk)
    assert risk.max_open_positions == 20
    assert risk.slot_budget(1000) == 50
    c.risk.max_open_positions = 21
    assert risk_manager_from_config(c.risk).max_open_positions == 20


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled,age_minutes,refresh', [(True, 4, False), (True, 6, True), (False, 6, False)])
async def test_memecoin_refresh_cadence(setup_bot, monkeypatch, enabled, age_minutes, refresh):
    from datetime import datetime, timedelta, timezone
    c = setup_bot
    c.risk.memecoins_enabled = enabled
    c.state.watchlist = ['BTC/EUR']
    c.state.watchlist_updated_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    c.db.commit()
    eligibility = AsyncMock(return_value=CURATED_PAIRS + (MEMECOIN_PAIRS if enabled else []))
    monkeypatch.setattr('app.services.bot_service.eligible_universe', eligibility)
    monkeypatch.setattr('app.services.bot_service.check_liquidity', AsyncMock())
    await run(c)
    assert eligibility.await_count == int(refresh)
    if refresh:
        assert sum(s in MEMECOIN_PAIRS for s in c.state.watchlist) == 27
        assert c.db.query(Position).count() <= c.risk.max_open_positions


@pytest.mark.asyncio
async def test_disabling_memecoins_prunes_stale_watchlist_and_forces_core_refresh(setup_bot, monkeypatch):
    from datetime import datetime, timezone
    c = setup_bot
    c.risk.memecoins_enabled = False
    c.state.watchlist = ['DOGE/EUR', 'PEPE/EUR', 'BTC/EUR']
    c.state.entry_decisions = {
        'DOGE/EUR': {'code': 'pending', 'message': 'old', 'checked_at': datetime.now(timezone.utc).isoformat()},
        'BTC/EUR': {'code': 'pending', 'message': 'old', 'checked_at': datetime.now(timezone.utc).isoformat()},
    }
    c.state.watchlist_updated_at = datetime.now(timezone.utc)
    c.db.commit()
    eligibility = AsyncMock(return_value=CURATED_PAIRS)
    monkeypatch.setattr('app.services.bot_service.eligible_universe', eligibility)

    await run(c)

    assert eligibility.await_count == 1
    assert c.state.watchlist
    assert all(symbol in CURATED_PAIRS for symbol in c.state.watchlist)
    assert 'DOGE/EUR' not in c.state.entry_decisions
    assert set(c.state.entry_decisions) == set(c.state.watchlist)


def adapter():
    ticker={'bid':.1000,'ask':.1001,'last':.1,'quoteVolume':2000000}
    return SimpleNamespace(client=SimpleNamespace(load_markets=AsyncMock(return_value={'DOGE/EUR':{'base':'DOGE','spot':True,'active':True,'quote':'EUR'}}),fetch_ticker=AsyncMock(return_value=ticker)))


@pytest.mark.asyncio
async def test_disabled_memecoin_universe_does_not_fetch(setup_bot, monkeypatch):
    monkeypatch.setattr('app.services.meme_discovery.meme_symbols', AsyncMock(return_value={'DOGE'}))
    c=setup_bot;exchange=adapter()
    assert await eligible_universe(exchange,c.risk)==CURATED_PAIRS
    exchange.client.load_markets.assert_not_called()
    c.risk.memecoins_enabled=True
    assert await eligible_universe(exchange,c.risk)==CURATED_PAIRS+['DOGE/EUR']
    exchange.client.load_markets.return_value['DOGE/EUR']['active']=False
    assert await eligible_universe(exchange,c.risk)==CURATED_PAIRS


@pytest.mark.asyncio
async def test_memecoin_liquidity_fails_closed(setup_bot):
    c=setup_bot;c.risk.memecoins_enabled=True;exchange=adapter()
    await check_liquidity(exchange,'DOGE/EUR',c.risk)
    exchange.client.fetch_ticker.return_value['ask']=.11
    with pytest.raises(ValueError,match='Spread is currently.*your maximum'): await check_liquidity(exchange,'DOGE/EUR',c.risk)
    exchange.client.fetch_ticker.return_value={'bid':.1,'ask':.1001,'last':.1,'quoteVolume':1}
    with pytest.raises(ValueError,match='turnover'): await check_liquidity(exchange,'DOGE/EUR',c.risk)
    exchange.client.fetch_ticker.return_value={}
    with pytest.raises(ValueError,match='unavailable'): await check_liquidity(exchange,'DOGE/EUR',c.risk)


def test_memecoin_caps_and_disable(setup_bot):
    c=setup_bot
    assert memecoin_budget(c.portfolio,c.risk,'DOGE/EUR',[])==0
    c.risk.memecoins_enabled=True
    assert memecoin_budget(c.portfolio,c.risk,'DOGE/EUR',[])==25
    positions=[SimpleNamespace(symbol='PEPE/EUR',quantity=1,current_price=40)]
    assert memecoin_budget(c.portfolio,c.risk,'DOGE/EUR',positions)==10
    risk=risk_manager_from_config(c.risk)
    assert entry_budget(c.portfolio,risk,'DOGE/EUR',positions,{})==10


def test_memecoin_settings_are_persisted_and_validated(client):
    headers=_auth_header(client,'meme@example.com','password')
    assert client.get('/api/v1/settings/risk',headers=headers).json()['memecoins_enabled'] is True
    response=client.put('/api/v1/settings/risk',headers=headers,json={'memecoins_enabled':True,'memecoin_max_exposure_pct':.15})
    assert response.status_code==200
    assert response.json()['memecoins_enabled'] is True
    assert response.json()['memecoin_max_exposure_pct']==.15
    assert client.put('/api/v1/settings/risk',headers=headers,json={'memecoin_max_position_pct':1}).status_code==422


@pytest.mark.asyncio
async def test_disabled_memecoin_holdings_still_get_stop_exit(setup_bot):
    c=setup_bot
    c.db.add(Position(portfolio_id=c.portfolio.id,symbol='DOGE/EUR',quantity=1,avg_entry_price=120,current_price=120))
    c.db.commit()
    await run(c)
    assert c.db.query(Position).filter(Position.symbol=='DOGE/EUR').count()==0
