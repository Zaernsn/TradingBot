from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from tests.test_autonomous import setup_bot, run
from tests.test_settings import client, _auth_header
from app.services.kraken_overview import value_holdings, account_overview
from app.services.exchange_service import encrypt_value
from app.services.risk_service import entry_budget, risk_manager_from_config
from app.models.portfolio import Trade, KrakenSnapshot


@pytest.mark.asyncio
async def test_values_balances_and_preserves_unpriced_assets():
    client = SimpleNamespace(fetch_balance=AsyncMock(return_value={'total': {'EUR': 50, 'DOGE': 10, 'UNKNOWN': 2}}),
        load_markets=AsyncMock(return_value={'DOGE/EUR': {}}), fetch_ticker=AsyncMock(return_value={'last': .1}))
    rows = await value_holdings(client)
    assert [r['value'] for r in rows] == [50, 1, None]
    assert rows[-1]['quantity'] == 2


@pytest.mark.asyncio
async def test_overview_caches_and_separates_credentials(setup_bot, monkeypatch):
    c = setup_bot
    assert (await account_overview(c.db, c.user))['connected'] is False
    c.user.kraken_api_key_encrypted = encrypt_value('first-key')
    c.user.kraken_api_secret_encrypted = encrypt_value('secret')
    adapter = SimpleNamespace(client=SimpleNamespace(fetch_balance=AsyncMock(return_value={'total': {'EUR': 123}}), load_markets=AsyncMock(return_value={})), close=AsyncMock())
    monkeypatch.setattr('app.services.kraken_overview.KrakenExchange', lambda **kwargs: adapter)
    first = await account_overview(c.db, c.user)
    assert first['equity'] == 123 and len(first['history']) == 1
    await account_overview(c.db, c.user)
    adapter.client.fetch_balance.assert_awaited_once()
    assert c.portfolio.equity == 500
    c.user.kraken_api_key_encrypted = encrypt_value('second-key')
    assert len((await account_overview(c.db, c.user))['history']) == 1
    assert c.db.query(KrakenSnapshot).count() == 2


def test_maximum_investment_validation_and_isolation(client):
    headers = _auth_header(client, 'cap@example.com', 'pass')
    response = client.put('/api/v1/settings/risk', headers=headers, json={'max_invest_per_trade_eur': 12.5})
    assert response.status_code == 200 and response.json()['max_invest_per_trade_eur'] == 12.5
    assert client.put('/api/v1/settings/risk', headers=headers, json={'max_invest_per_trade_eur': -1}).status_code == 422
    assert client.get('/api/v1/portfolio/kraken-overview').status_code == 401
    assert client.get('/api/v1/portfolio/kraken-overview', headers=headers).json()['connected'] is False


@pytest.mark.asyncio
async def test_paper_entry_cap_includes_costs(setup_bot):
    c = setup_bot
    c.risk.max_invest_per_trade_eur = 12.5
    c.db.commit()
    risk = risk_manager_from_config(c.risk)
    assert entry_budget(c.portfolio, risk, 'BTC/EUR', [], {}) == 12.5
    await run(c)
    trades = c.db.query(Trade).filter(Trade.side == 'BUY').all()
    assert trades and all(t.total_cost <= 12.5 + 1e-8 for t in trades)


@pytest.mark.asyncio
async def test_updated_cap_is_checked_before_execution(setup_bot, monkeypatch):
    from app.exchanges.base import OrderSide
    c = setup_bot
    old_risk = risk_manager_from_config(c.risk)
    c.risk.max_invest_per_trade_eur = 5
    c.db.commit()
    monkeypatch.setattr(c.bot, '_running', lambda *args: True)
    with pytest.raises(ValueError, match='Maximum investment'):
        await c.bot._execution(c.db, c.portfolio, c.user, c.exchange, 'BTC/EUR', OrderSide.BUY,
                               .1, 100, old_risk, None, 'test')
    assert c.db.query(Trade).count() == 0
