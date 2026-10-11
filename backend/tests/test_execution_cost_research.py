from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
import importlib.util
from pathlib import Path

from app.exchanges.base import Ticker
from app.ml.cost_attribution import attribution
from app.models.portfolio import MarketObservation, ExecutionOrder, Portfolio
from app.services.market_observations import observation, collect_market_observations, available_observation, depth_probe
from app.services.execution_costs import execution_cost_report
from tests.test_autonomous import setup_bot
from tests.test_settings import client, _auth_header


def book(now):
    return {'bids':[[99,10],[98,10]],'asks':[[101,10],[102,10]],'timestamp':now.timestamp()*1000,'source':'rest'}


def ticker(now):
    return Ticker('BTC/EUR',99,101,100,10000,now,'rest')


@pytest.mark.parametrize('kind,status', [('normal','VALID'),('stale','STALE'),('future','INVALID_TIME'),
    ('missing','PARTIAL'),('crossed','PARTIAL'),('malformed','PARTIAL')])
def test_observation_quality_and_timestamp_uncertainty(kind,status):
    now=datetime(2026,1,1,tzinfo=timezone.utc)
    snapshot=book(now); quote=ticker(now)
    if kind=='stale': snapshot['timestamp']=(now-timedelta(seconds=31)).timestamp()*1000
    if kind=='future': snapshot['timestamp']=(now+timedelta(seconds=6)).timestamp()*1000
    if kind=='missing': snapshot['timestamp']=None
    if kind=='crossed': snapshot['bids']=[[103,10]]
    if kind=='malformed': snapshot['asks']=[[float('nan'),10]]
    quality,evidence,_,_=observation(quote,snapshot,now)
    assert quality==status
    if kind=='normal':
        assert evidence['spread_pct']==pytest.approx(.02)
        assert evidence['probes']['BUY'][0]['complete']
        assert evidence['probes']['BUY'][0]['adverse_vs_mid_pct']==pytest.approx(.01)


def test_depth_probe_cannot_claim_full_fill_beyond_recorded_depth():
    result=depth_probe([[101,1]],'BUY',500,100)
    assert not result['complete'] and result['filled_fraction']==pytest.approx(.202)


@pytest.mark.asyncio
async def test_collector_persists_once_and_never_orders(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    exchange=SimpleNamespace(get_ticker=AsyncMock(return_value=ticker(now)),
        get_order_book=AsyncMock(return_value=book(now)),place_order=AsyncMock(),get_balances=AsyncMock())
    first=await collect_market_observations(c.db,exchange,['BTC/EUR','BTC/EUR'],now)
    second=await collect_market_observations(c.db,exchange,['BTC/EUR'],now)
    assert first['counts']=={'VALID':1} and second['already_recorded']==['BTC/EUR']
    assert c.db.query(MarketObservation).count()==1
    assert exchange.get_ticker.await_count==exchange.get_order_book.await_count==1
    exchange.place_order.assert_not_awaited(); exchange.get_balances.assert_not_awaited()


@pytest.mark.asyncio
async def test_errors_deadline_and_retention_are_persisted_without_private_calls(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    c.db.add(MarketObservation(exchange='kraken',symbol='OLD/EUR',bucket_at=now-timedelta(days=15),
        requested_at=now-timedelta(days=15),received_at=now-timedelta(days=15),status='FAILED',evidence={}))
    c.db.commit()
    exchange=SimpleNamespace(get_ticker=AsyncMock(side_effect=RuntimeError('secret must not be recorded')),
                             get_order_book=AsyncMock(return_value=book(now)))
    result=await collect_market_observations(c.db,exchange,['BTC/EUR'],now)
    row=c.db.query(MarketObservation).one()
    assert row.status=='PARTIAL' and row.evidence['errors']['quote']=='RuntimeError'
    assert 'secret' not in str(row.evidence) and result['pruned']==1
    result=await collect_market_observations(c.db,exchange,['ETH/EUR'],now,deadline_seconds=0)
    assert result['counts']=={'FAILED':1}


def test_asof_lookup_never_borrows_later_snapshot_or_stale_source(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    for offset,source_offset,symbol in ((-1,-2,'BTC/EUR'),(1,-2,'ETH/EUR'),(-1,-31,'SOL/EUR')):
        c.db.add(MarketObservation(exchange='kraken',symbol=symbol,bucket_at=now,
            requested_at=now-timedelta(seconds=3),received_at=now+timedelta(seconds=offset),
            quote_at=now+timedelta(seconds=source_offset),book_at=now+timedelta(seconds=source_offset),
            status='VALID',evidence={}))
    c.db.commit()
    assert available_observation(c.db,'BTC/EUR',now)
    assert available_observation(c.db,'ETH/EUR',now) is None
    assert available_observation(c.db,'SOL/EUR',now) is None


@pytest.mark.asyncio
async def test_rotating_collection_does_not_starve_large_universe(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    exchange=SimpleNamespace(get_ticker=AsyncMock(return_value=ticker(now)),get_order_book=AsyncMock(return_value=book(now)))
    symbols=[f'C{i:02d}/EUR' for i in range(61)]
    for offset in range(3):
        result=await collect_market_observations(c.db,exchange,symbols,now+timedelta(minutes=5*offset))
        assert result['selected']<=30
    assert {row[0] for row in c.db.query(MarketObservation.symbol).distinct()}==set(symbols)


@pytest.mark.asyncio
async def test_scheduled_public_collection_continues_after_history_failure(setup_bot,monkeypatch):
    c=setup_bot; now=datetime.now(timezone.utc)
    c.risk.entry_strategy='auto'; c.state.watchlist=['BTC/EUR']; c.state.is_running=False; c.db.commit()
    exchange=SimpleNamespace(get_ticker=AsyncMock(return_value=ticker(now)),get_order_book=AsyncMock(return_value=book(now)),
                             close=AsyncMock(),place_order=AsyncMock())
    monkeypatch.setattr('app.db.session.SessionLocal',c.factory)
    monkeypatch.setattr('app.services.bot_service.PaperExchange',lambda:exchange)
    monkeypatch.setattr('app.services.research_market_data.collect_intraday_history',AsyncMock(side_effect=ValueError('history unavailable')))
    monkeypatch.setattr('app.services.strategy_research.research_next_candidate',lambda *args,**kwargs:None)
    monkeypatch.setattr('app.services.strategy_research.advance_shadow_candidates',lambda *args,**kwargs:[])
    monkeypatch.setattr('app.services.strategy_research.review_live_canary',lambda *args,**kwargs:[])
    await c.bot.research_strategies()
    c.db.expire_all()
    assert c.db.query(MarketObservation).count()==1 and not c.state.is_running
    assert c.state.discovery_stats['strategy_research']['intraday_collection']['execution_observations']['counts']=={'VALID':1}
    exchange.place_order.assert_not_awaited(); exchange.close.assert_awaited_once()


def fills(partial=False):
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    trades=[dict(symbol='BTC/EUR',side='BUY',quantity=2 if partial else 1,price=100,fee=2 if partial else 1,timestamp=start),
            dict(symbol='BTC/EUR',side='SELL',quantity=1,price=102 if partial else 100.5,fee=.5 if partial else 1,
                 pnl=.5 if partial else -1.5,timestamp=start+timedelta(hours=2))]
    return {'trades':trades,'initial_cash':500,'final_equity':502.5 if partial else 498.5,
        'total_fees':2.5 if partial else 2.,'open_positions':{'BTC/EUR':{'current_price':103}} if partial else {},
        'experiment':{'configuration':{'risk':{'slippage_pct':.01}}}}


def test_fee_drag_can_exceed_net_loss_without_claiming_new_strategy_profit():
    result=attribution(fills())
    assert result['net_pnl']==pytest.approx(-1.5)
    assert result['closed_fees']==2 and result['same_fill_path_before_fees_pnl']==.5
    assert result['fee_share_of_net_loss']==pytest.approx(4/3)
    assert result['equity_reconciliation_residual']==pytest.approx(0)
    assert result['groups']['exit_reason']['Unrecorded']['closed_trades']==1


def test_partial_close_and_open_mark_reconcile_without_double_counted_entry_fee():
    result=attribution(fills(partial=True))
    assert result['closed_fees']==1.5 and result['total_recorded_fees']==2.5
    assert result['open_marked_pnl']==2 and result['equity_reconciliation_residual']==pytest.approx(0)


def test_missing_slippage_and_inconsistent_accounting_are_explicit():
    result=fills(); result.pop('experiment')
    assert attribution(result)['modeled_slippage'] is None
    result['trades'][1]['pnl']=999
    with pytest.raises(ValueError,match='reconcile'):
        attribution(result)


def test_live_report_excludes_paper_and_missing_or_stale_quotes(setup_bot):
    c=setup_bot; now=datetime.now(timezone.utc)
    live=Portfolio(user_id=c.user.id,book_type='LIVE',is_active=False,mode='LIVE_DISABLED',cash=500,equity=500)
    c.db.add(live); c.db.flush()
    for index,(portfolio,age) in enumerate(((live,1),(live,60),(c.portfolio,1))):
        c.db.add(ExecutionOrder(portfolio_id=portfolio.id,client_id=f'cost-{index}',symbol='BTC/EUR',side='BUY',
            requested_quantity=1,status='FILLED',filled_quantity=1,filled_cost=102,filled_fee=1,
            created_at=now,execution_evidence={'bid':99,'ask':101,'quote_at':(now-timedelta(seconds=age)).isoformat(),
                                             'submission_started_at':now.isoformat()}))
    c.db.commit()
    result=execution_cost_report(c.db,c.user.id,now)['live_execution']
    assert result['filled_orders']==2 and result['fresh_quote_matched_orders']==1
    assert result['quote_fee_eur']==2 and result['adverse_vs_touch_eur']==1
    assert execution_cost_report(c.db,c.user.id+100,now)['live_execution']['quote_fee_eur'] is None


def test_cost_endpoint_requires_auth_and_empty_evidence_is_not_zero_cost(client):
    assert client.get('/api/v1/bot/research/execution-costs').status_code==401
    headers=_auth_header(client,'cost-evidence@example.com','pass')
    response=client.get('/api/v1/bot/research/execution-costs',headers=headers)
    assert response.status_code==200 and response.json()['live_execution']['adverse_vs_touch_eur'] is None


def test_market_observation_migration_round_trip():
    path=Path(__file__).resolve().parents[1]/'migrations/versions/2026_10_11_market_observations.py'
    spec=importlib.util.spec_from_file_location('market_migration',path)
    migration=importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    with create_engine('sqlite://').begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert 'market_observations' in inspect(connection).get_table_names()
            assert inspect(connection).get_unique_constraints('market_observations')
            migration.downgrade()
            assert 'market_observations' not in inspect(connection).get_table_names()
