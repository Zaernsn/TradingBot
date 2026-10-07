from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import httpx
import pytest
from tests.test_settings import client, _auth_header
from tests.test_autonomous import setup_bot
from app.core.config import settings
from app.services.meme_discovery import MemeCategoryParser
from app.services.memecoin_service import eligible_universe, memecoin_budget
from app.services.asset_selector import AssetSelector
from app.services.password_reset import send_reset


def test_category_parser_excludes_unrelated_links():
    parser=MemeCategoryParser()
    parser.feed('<a href="/prices/fresh-meme" class="row NEWMEME">New</a><a href="/prices/bitcoin" class="hover:underline">BTC</a><a href="/other" class="FAKE">Ignore</a>')
    assert parser.symbols == {'NEWMEME'}


@pytest.mark.asyncio
async def test_dynamic_discovery_rank_and_risk(setup_bot, monkeypatch):
    c=setup_bot; c.risk.memecoins_enabled=True
    monkeypatch.setattr('app.services.meme_discovery.meme_symbols', AsyncMock(return_value={'NEW1','NEW2'}))
    markets={s+'/EUR': {'base':s,'spot':True,'active':True,'quote':'EUR'} for s in ['NEW1','NEW2','NOTMEME']}
    async def ticker(s): return {'bid':1, 'ask':1.001, 'last':1, 'quoteVolume':2000000 if s=='NEW1/EUR' else 5000000, 'percentage':5}
    adapter=SimpleNamespace(client=SimpleNamespace(load_markets=AsyncMock(return_value=markets),fetch_ticker=AsyncMock(side_effect=ticker)))
    result=await eligible_universe(adapter,c.risk)
    assert result[-2:] == ['NEW2/EUR','NEW1/EUR']
    assert 'NOTMEME/EUR' not in result
    assert memecoin_budget(c.portfolio,c.risk,'NEW1/EUR',[]) == 25
    assert AssetSelector().select_watchlist({'NEW1/EUR':[]},20,True)==['NEW1/EUR']
    c.risk.memecoins_enabled=False
    assert memecoin_budget(c.portfolio,c.risk,'NEW1/EUR',[])==0


@pytest.mark.asyncio
async def test_tracking_does_not_bypass_entry_liquidity(setup_bot, monkeypatch):
    from app.services.memecoin_service import check_liquidity
    c=setup_bot; c.risk.memecoins_enabled=True
    monkeypatch.setattr('app.services.meme_discovery.meme_symbols', AsyncMock(return_value={'FRESH'}))
    adapter=SimpleNamespace(client=SimpleNamespace(
        load_markets=AsyncMock(return_value={'FRESH/EUR': {'base':'FRESH','spot':True,'active':True,'quote':'EUR'}}),
        fetch_ticker=AsyncMock(return_value={'bid':1,'ask':1.001,'last':1,'quoteVolume':50000})))
    assert 'FRESH/EUR' in await eligible_universe(adapter,c.risk)
    with pytest.raises(ValueError,match='turnover'):
        await check_liquidity(adapter,'FRESH/EUR',c.risk)


def test_server_keys_not_reported_as_personal(client,monkeypatch):
    monkeypatch.setattr(settings,'KRAKEN_API_KEY','server-key')
    monkeypatch.setattr(settings,'KRAKEN_API_SECRET','server-secret')
    headers=_auth_header(client,'personal@example.com','pass')
    assert client.get('/api/v1/settings/exchange',headers=headers).json()['connected'] is False
    assert client.get('/api/v1/settings/safety',headers=headers).json()['credential_status']=='missing'
    client.post('/api/v1/settings/exchange',headers=headers,json={'api_key':'own-key','api_secret':'own-secret'})
    assert client.get('/api/v1/settings/exchange',headers=headers).json()['connected'] is True
    assert client.get('/api/v1/settings/safety',headers=headers).json()['credential_status']=='saved'


def test_resend_delivery(monkeypatch):
    monkeypatch.setattr(settings,'RESEND_API_KEY','test-secret')
    monkeypatch.setattr(settings,'RESEND_FROM','WACG <reset@example.com>')
    captured=[]
    def handle(request):
        captured.append(request)
        return httpx.Response(200,json={'id':'test-email'})
    real_client=httpx.Client
    monkeypatch.setattr('app.services.password_reset.httpx.Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    assert send_reset('user@example.com','test-token') is True
    assert captured[0].url==httpx.URL('https://api.resend.com/emails')
    assert captured[0].headers['Authorization']=='Bearer test-secret'
    assert 'test-token' not in captured[0].headers['Idempotency-Key']
    assert b'reset-password#token=test-token' in captured[0].content


def test_resend_enabled_without_smtp(client,monkeypatch):
    monkeypatch.setattr(settings,'RESEND_API_KEY','test-secret')
    monkeypatch.setattr(settings,'RESEND_FROM','reset@example.com')
    send=Mock(return_value=True)
    monkeypatch.setattr('app.services.password_reset.send_reset',send)
    _auth_header(client,'reset-api@example.com','pass')
    result=client.post('/api/v1/auth/forgot-password',json={'email':'reset-api@example.com'})
    assert result.status_code==200
    send.assert_called_once()
