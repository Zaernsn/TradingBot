from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib
import pytest
from tests.test_autonomous import setup_bot, candles
from tests.test_settings import client, _auth_header, TestingSessionLocal
from app.core.config import settings
from app.models.user import User, PasswordResetToken
from app.models.portfolio import ExecutionOrder, Position, Trade
from app.services.password_reset import issue_reset, consume_reset, rate_allowed
from app.services.live_execution import (
    execute_live, reconcile_order, unresolved, OrderIntentAlreadyHandled,
)
from app.services.trading_books import activate_paper_book
from app.services.trading_service import record_fill
from app.exchanges.base import OrderResult, OrderStatus, OrderSide
from app.ml.features import build_features, make_target
from app.ml.models import SignalModel
from app.ml.backtest import PortfolioBacktestEngine
from app.services.bot_service import with_verified_taker_fee
from app.services.risk_service import risk_manager_from_config


def test_target_future_tail_and_costs():
    df=build_features(candles(.001,.002,count=200,objects=True))
    target=make_target(df,12,0,0)
    assert target.tail(12).isna().all()
    assert target.iloc[:-12].notna().all()
    costly=make_target(df,12,.1,.1)
    assert costly.dropna().sum()==0


def test_live_taker_fee_raises_execution_cost_without_rejecting_pair(setup_bot):
    risk=risk_manager_from_config(setup_bot.risk)
    adjusted=with_verified_taker_fee(risk,.004)
    assert adjusted.fee_pct==.004
    assert with_verified_taker_fee(adjusted,.0026).fee_pct==.004
    with pytest.raises(ValueError,match='usable taker fee'):
        with_verified_taker_fee(risk,float('nan'))


def test_short_model_holds():
    model=SignalModel(persist=False).fit(candles(count=80,objects=True))
    assert not model.is_fitted
    assert model.predict(candles(count=80,objects=True))['action']=='HOLD'


def test_entry_fees_count_in_realized_pnl(setup_bot):
    c=setup_bot
    record_fill(c.db,c.portfolio,'BTC/EUR',OrderSide.BUY,1,100,1,100)
    record_fill(c.db,c.portfolio,'BTC/EUR',OrderSide.SELL,1,110,1,110)
    assert c.portfolio.cash==pytest.approx(508)
    sell=c.db.query(Trade).filter(Trade.side=='SELL').one()
    assert sell.pnl==pytest.approx(8)


def test_reactivating_same_paper_keeps_active(setup_bot):
    c=setup_bot;c.state.is_running=False;c.db.commit()
    activate_paper_book(c.db,c.user.id)
    c.db.expire_all()
    assert c.portfolio.is_active


@pytest.mark.asyncio
async def test_partial_fills_are_idempotent_and_cancellation_preserves_fill(setup_bot):
    c=setup_bot
    order=ExecutionOrder(portfolio_id=c.portfolio.id,client_id='partial',exchange_id='kraken1',symbol='BTC/EUR',side='BUY',requested_quantity=2)
    c.db.add(order);c.db.commit()
    result=OrderResult('kraken1',OrderStatus.PARTIAL,1,100,.3,cost=100)
    exchange=SimpleNamespace(get_order_status=AsyncMock(return_value=result))
    assert not await reconcile_order(c.db,c.portfolio,exchange,order)
    await reconcile_order(c.db,c.portfolio,exchange,order)
    assert c.db.query(Trade).count()==1
    assert c.portfolio.cash==pytest.approx(399.7)
    result.status=OrderStatus.CANCELED
    assert await reconcile_order(c.db,c.portfolio,exchange,order)
    assert not unresolved(c.db,c.portfolio)
    assert c.db.query(Position).one().quantity==1


@pytest.mark.asyncio
async def test_ambiguous_submission_never_retries(setup_bot,monkeypatch):
    c=setup_bot
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.live_execution.fingerprint',lambda user:'binding')
    c.portfolio.book_type=c.portfolio.mode='LIVE';c.portfolio.account_fingerprint='binding';c.db.commit()
    exchange=SimpleNamespace(prepare_order=AsyncMock(return_value=(1,100)),submit_ioc=AsyncMock(side_effect=TimeoutError()),find_order=AsyncMock(return_value=None))
    with pytest.raises(ValueError,match='Uncertain'):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk)
    assert c.db.query(ExecutionOrder).one().status=='UNKNOWN'
    assert c.db.query(Trade).count()==0
    with pytest.raises(ValueError,match='Reconcile'):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk)
    assert exchange.submit_ioc.await_count==1
    result=OrderResult('recovered',OrderStatus.FILLED,1,100,.3,cost=100)
    exchange.find_order.return_value=result
    await reconcile_order(c.db,c.portfolio,exchange,c.db.query(ExecutionOrder).one())
    assert c.db.query(Trade).count()==1
    assert c.portfolio.cash==pytest.approx(399.7)


@pytest.mark.asyncio
async def test_deterministic_signal_intent_blocks_second_submission(setup_bot,monkeypatch):
    from app.exchanges.kraken import OrderRejected
    c=setup_bot
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.live_execution.fingerprint',lambda user:'binding')
    c.portfolio.book_type=c.portfolio.mode='LIVE'
    c.portfolio.account_fingerprint='binding'; c.db.commit()
    exchange=SimpleNamespace(
        prepare_order=AsyncMock(return_value=(1,100)),
        submit_ioc=AsyncMock(side_effect=OrderRejected('confirmed rejection')),
    )
    with pytest.raises(OrderRejected):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk,
                           intent_key='signal:42:BUY')
    with pytest.raises(OrderIntentAlreadyHandled,match='duplicate submission blocked'):
        await execute_live(c.db,c.portfolio,c.user,exchange,'BTC/EUR',OrderSide.BUY,1,100,c.risk,
                           intent_key='signal:42:BUY')
    assert exchange.submit_ioc.await_count==1
    assert c.db.query(ExecutionOrder).one().status=='REJECTED'


def test_reset_revokes_token_rejects_reuse_and_expiry(client,monkeypatch):
    headers=_auth_header(client,'reset@example.com','oldpassword')
    with TestingSessionLocal() as db:
        token=issue_reset(db,'reset@example.com')
        assert db.get(PasswordResetToken,hashlib.sha256(token.encode()).hexdigest())
    response=client.post('/api/v1/auth/reset-password',json={'token':token,'password':'new-password-123'})
    assert response.status_code==200,response.text
    assert client.get('/api/v1/portfolio/me',headers=headers).status_code==401
    assert client.post('/api/v1/auth/reset-password',json={'token':token,'password':'new-password-123'}).status_code==400
    assert client.post('/api/v1/auth/login',json={'email':'reset@example.com','password':'new-password-123'}).status_code==200
    with TestingSessionLocal() as db:
        token=issue_reset(db,'reset@example.com')
        row=db.get(PasswordResetToken,hashlib.sha256(token.encode()).hexdigest())
        row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        assert not consume_reset(db,token,'another-password')


def test_reset_email_is_account_neutral_and_rate_limited(client,monkeypatch):
    _auth_header(client,'mail@example.com','oldpassword')
    monkeypatch.setattr(settings,'RESEND_API_KEY','test-key');monkeypatch.setattr(settings,'RESEND_FROM','sender@example.com')
    delivered=[]
    monkeypatch.setattr('app.services.password_reset.send_reset',lambda email,token:delivered.append((email,token)))
    a=client.post('/api/v1/auth/forgot-password',json={'email':'mail@example.com'})
    b=client.post('/api/v1/auth/forgot-password',json={'email':'missing@example.com'})
    assert a.status_code==b.status_code==200
    assert a.json()==b.json()
    assert len(delivered)==1
    with TestingSessionLocal() as db:
        assert rate_allowed(db,'limited',1)
        assert not rate_allowed(db,'limited',1)


def test_backtest_uses_past_data_and_net_accounting():
    rows=candles(.001,.002,count=370,objects=True)
    class Model:
        is_fitted=False
        def fit(self,history,**kwargs): self.is_fitted=True; return self
        def predict(self,history):
            assert len(history)<len(rows)
            return {'action':'BUY'}
    result=PortfolioBacktestEngine({'BTC/EUR':rows},model_factory=lambda _:Model(),select_assets=False).run()
    assert result['num_trades']>0
    assert result['total_fees']>0
    assert result['final_equity']==pytest.approx(500+sum(t['pnl'] or 0 for t in result['trades']))


def test_calibration_and_validation_are_purged():
    import numpy as np
    from app.exchanges.base import OHLCV
    rng=np.random.default_rng(17)
    prices=100*np.exp(np.cumsum(rng.normal(0,.012,720)))
    end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    rows=[OHLCV(end-timedelta(hours=720-i),p,p+1,p-1,p,1000+rng.random()*100) for i,p in enumerate(prices)]
    model=SignalModel(persist=False).fit(rows)
    assert model.is_fitted,model.failure_reason
    stats=model.validation
    assert stats['training_rows']+stats['calibration_rows']+stats['validation_rows']+24==stats['total_labeled_rows']
    df=build_features(rows)
    np.testing.assert_allclose(model.scaler.mean_,df[model.feature_cols].iloc[:stats['training_rows']].mean(),rtol=1e-9)
    assert 0<=stats['brier_score']<=1


@pytest.mark.asyncio
async def test_live_book_activation_preserves_paper_and_is_idempotent(setup_bot,monkeypatch):
    from app.services.trading_books import enable_live_book
    from app.models.portfolio import Portfolio
    c=setup_bot;c.state.is_running=False;c.db.commit()
    monkeypatch.setattr(settings,'ENABLE_LIVE_TRADING',True)
    monkeypatch.setattr('app.services.trading_books.fingerprint',lambda user:'unique-key')
    exchange=SimpleNamespace(validate_permissions=AsyncMock(),get_balances=AsyncMock(return_value={'EUR':123}),open_orders=AsyncMock(return_value=[]),close=AsyncMock())
    monkeypatch.setattr('app.services.trading_books.live_exchange',lambda user:exchange)
    book=await enable_live_book(c.db,c.user)
    assert book.cash==123 and book.book_type=='LIVE'
    assert c.portfolio.cash==500 and not c.portfolio.is_active
    await enable_live_book(c.db,c.user)
    assert c.db.query(Portfolio).filter(Portfolio.is_active.is_(True)).one().id==book.id
    activate_paper_book(c.db,c.user.id)
    assert c.db.query(Portfolio).filter(Portfolio.is_active.is_(True)).one().id==c.portfolio.id


@pytest.mark.asyncio
async def test_kraken_permission_check_fails_closed():
    from app.exchanges.kraken import KrakenExchange
    exchange=KrakenExchange(api_key='',api_secret='')
    exchange.client.request=AsyncMock(return_value={'result':{'permissions':['query-funds','withdraw-funds']}})
    try:
        with pytest.raises(ValueError,match='withdrawal'): await exchange.validate_permissions()
        exchange.client.request.return_value={'result':{}}
        with pytest.raises(ValueError,match='verify'): await exchange.validate_permissions()
    finally: await exchange.close()


def test_lease_excludes_other_worker_and_expires(setup_bot):
    from app.services import execution_lease as lease
    c=setup_bot
    token=lease.acquire(c.db,c.user.id)
    assert token and lease.acquire(c.db,c.user.id) is None
    assert not lease.renew(c.db,c.user.id,'wrong-token')
    lease.release(c.db,c.user.id,token)
    assert lease.acquire(c.db,c.user.id)


def test_live_order_records_are_scoped_to_current_user(client):
    from app.models.portfolio import Portfolio
    headers=_auth_header(client,'orders@example.com','password')
    other=_auth_header(client,'other-orders@example.com','password')
    book_id=client.get('/api/v1/portfolio/me',headers=headers).json()['id']
    with TestingSessionLocal() as db:
        db.add(ExecutionOrder(portfolio_id=book_id,client_id='private-client-id',symbol='BTC/EUR',side='BUY',requested_quantity=1))
        db.commit()
    assert client.get('/api/v1/portfolio/orders',headers=headers).json()[0]['client_id']=='private-client-id'
    assert client.get('/api/v1/portfolio/orders',headers=other).json()==[]
    assert client.get('/api/v1/portfolio/orders').status_code==401


def test_drawdown_stays_halted_after_recovery(setup_bot):
    from app.services.risk_service import check_drawdown
    c=setup_bot;c.portfolio.equity=400
    assert check_drawdown(c.portfolio,c.risk)
    c.portfolio.equity=600
    assert check_drawdown(c.portfolio,c.risk)


def test_archive_excludes_incomplete_and_preserves_existing(setup_bot):
    from app.services.market_data import archive, history
    from app.exchanges.base import OHLCV
    c=setup_bot
    rows=candles(count=5,objects=True)
    rows.append(OHLCV(datetime.now(timezone.utc),100,101,99,100,1))
    archive(c.db,'BTC/EUR','1h',rows)
    archive(c.db,'BTC/EUR','1h',rows)
    assert len(history(c.db,'BTC/EUR'))==5
