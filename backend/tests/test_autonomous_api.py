from tests.test_settings import client, _auth_header
from tests.test_autonomous import setup_bot, run
from tests.test_settings import TestingSessionLocal
from fastapi.testclient import TestClient
from app.main import create_application
from app.db.session import get_db
from app.models.portfolio import BotState, Portfolio
from app.models.user import User
import pytest
from dataclasses import asdict
from app.ml.strategies import AdaptiveParameters
from app.ml.strategy_factory import candidate_id


def test_risk_settings_and_bot_response(client):
    headers = _auth_header(client, 'slots@example.com', 'pass')
    risk = client.get('/api/v1/settings/risk', headers=headers).json()
    assert risk['max_open_positions'] == 20
    assert risk['allocation_mode'] == 'equal'
    for supplied, expected in [(3,3),(0,1),(20,20),(99,20)]:
        response=client.put('/api/v1/settings/risk', headers=headers, json={'max_open_positions':supplied,'trading_pair':'DOGE/EUR'})
        assert response.status_code==200
        assert response.json()['max_open_positions']==expected
        assert response.json()['trading_pair']==risk['trading_pair']
        assert client.get('/api/v1/bot/state',headers=headers).json()['open_slots']==expected
    for payload in [{'allocation_mode':'weighted'}, {'max_position_pct':-1}, {'fee_pct':-1}, {'max_open_positions':2.5}]:
        assert client.put('/api/v1/settings/risk',headers=headers,json=payload).status_code==422
    assert client.put('/api/v1/settings/risk',headers=headers,json={'max_open_positions':None}).status_code==200
    other=_auth_header(client,'other@example.com','pass')
    assert client.get('/api/v1/bot/state',headers=other).json()['open_slots']==20
    for route in ['stop','emergency-stop']:
        response=client.post('/api/v1/bot/'+route,headers=headers)
        assert response.status_code==200
        assert response.json()['open_slots']==20
        assert response.json()['is_running'] is False


def test_bot_state_hides_stale_memecoins_when_feature_is_disabled(client):
    headers = _auth_header(client, 'core-only@example.com', 'pass')
    assert client.put('/api/v1/settings/risk', headers=headers, json={
        'memecoins_enabled': False, 'watchlist_limit': 10,
    }).status_code == 200
    client.get('/api/v1/bot/state', headers=headers)
    with TestingSessionLocal() as db:
        user = db.query(User).filter(User.email == 'core-only@example.com').one()
        state = db.query(BotState).filter(BotState.user_id == user.id).one()
        state.watchlist = ['DOGE/EUR', 'BTC/EUR', 'PEPE/EUR', 'ETH/EUR']
        db.commit()

    result = client.get('/api/v1/bot/state', headers=headers).json()
    assert result['watchlist'] == ['BTC/EUR', 'ETH/EUR']
    assert result['memecoin_watchlist_count'] == 0
    assert result['memecoin_watchlist_target'] == 0


def test_research_metadata_roundtrip_cannot_import_live_approval(client):
    headers=_auth_header(client,'metadata@example.com','pass')
    parameters=AdaptiveParameters()
    payload={'schema_version':1,'kind':'trading-bot-research-metadata',
        'exported_at':'2026-01-01T00:00:00+00:00','shadow_runs':[],
        'candidates':[{'candidate_id':candidate_id(parameters),'parameters':asdict(parameters),
            'status':'LIVE_APPROVED','metrics':{'expectancy':999},
            'tested_at':'2026-01-01T00:00:00+00:00'}]}
    result=client.post('/api/v1/bot/research/metadata/import',headers=headers,json=payload)
    assert result.status_code==200
    assert result.json()['live_authorized'] is False
    exported=client.get('/api/v1/bot/research/metadata/export',headers=headers).json()
    assert exported['candidates'][0]['status']=='IMPORTED_UNVERIFIED'
    status=client.get('/api/v1/bot/research/status',headers=headers)
    assert status.status_code==200 and status.json()['counts']=={'IMPORTED_UNVERIFIED':1}
    assert client.post('/api/v1/bot/research/metadata/import',json=payload).status_code==401


@pytest.mark.asyncio
async def test_api_smoke_register_configure_run_and_emergency_stop(setup_bot,monkeypatch):
    c=setup_bot
    def override():
        with c.factory() as db: yield db
    app=create_application(); app.dependency_overrides[get_db]=override
    monkeypatch.setattr('app.api.v1.bot.bot_orchestrator',c.bot)
    # Keep the scheduler deterministic; trigger its registered iteration explicitly.
    monkeypatch.setattr(c.bot.scheduler,'start',lambda:None)
    with TestClient(app) as client:
        headers=_auth_header(client,'smoke@example.com','pass')
        response=client.put('/api/v1/settings/risk',headers=headers,json={'max_open_positions':3})
        assert response.status_code==200
        assert client.post('/api/v1/bot/start',headers=headers).status_code==200
        with c.factory() as db:
            state=db.query(BotState).filter(BotState.user_id!=c.user.id).one()
            portfolio=db.query(Portfolio).filter(Portfolio.user_id==state.user_id).one()
            args=(state.user_id,portfolio.id,response.json()['id'])
        await c.bot._run_iteration(*args)
        state=client.get('/api/v1/bot/state',headers=headers).json()
        assert len(state['watchlist'])==3
        assert state['open_slots']==0
        assert len(client.get('/api/v1/portfolio/positions',headers=headers).json())==3
        stopped=client.post('/api/v1/bot/emergency-stop',headers=headers).json()
        assert stopped['is_running'] is False
        assert client.get('/api/v1/portfolio/me',headers=headers).json()['mode']=='PAPER'
