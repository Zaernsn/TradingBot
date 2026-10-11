import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.exchanges.base import OHLCV
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.evaluation import digest
from app.ml.replay_checkpoint import CheckpointInvalid
from app.ml.strategies import MomentumModel, AdaptiveParameters
from app.ml.strategy_factory import StrategyDefinition, candidate_factory, candidate_parameters
from app.models.portfolio import StrategyCandidate, ShadowRun, ShadowTrade, ShadowEquity, ExecutionOrder
from app.services.strategy_research import advance_shadow_candidates
from tests.test_research import risk, Buyer
from tests.test_autonomous import setup_bot


def market_data(timeframe='1h', count=260, gaps=False):
    interval=timedelta(minutes=15 if timeframe=='15m' else 60)
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    result={}
    for symbol in ('BTC/EUR','ETH/EUR','SOL/EUR'):
        rows=[]
        price=100.
        for i in range(count):
            # Repeated trends, reversals, volume spikes, and ambiguous exits.
            price*=1.004 if i%80<50 else .994
            if gaps and 135<=i<142:
                continue
            rows.append(OHLCV(start+i*interval,price,price*1.015,price*.99,
                              price*1.002,20000. if i%6==0 else 10000.))
        result[symbol]=rows
    return result


def comparable(result):
    return {key:value for key,value in result.items() if key not in {'replay_checkpoint','replay_work'}}


def replay(data, timeframe, factory=None, **overrides):
    return PortfolioBacktestEngine(data,risk=risk(entry_strategy='auto' if factory else 'momentum',
        max_drawdown_pct=.9,fee_pct=.001,slippage_pct=.001,max_holding_hours=48),
        select_assets=False,model_factory=factory,timeframe=timeframe,
        liquidate_end=False,allow_no_trade_gaps=True,**overrides)


@pytest.mark.parametrize('timeframe', ['1h','15m'])
@pytest.mark.parametrize('gaps', [False,True])
def test_restart_duplicate_and_gap_parity(timeframe,gaps):
    data=market_data(timeframe,gaps=gaps)
    first={symbol:rows[:130] for symbol,rows in data.items()}
    result=replay(first,timeframe).run(warmup=30,save_checkpoint=True)
    assert result['trades'] and result['open_positions']
    checkpoint=json.loads(json.dumps(result['replay_checkpoint'],allow_nan=False))
    resumed=replay(data,timeframe).run(warmup=30,checkpoint=checkpoint)
    full=replay(data,timeframe).run(warmup=30)
    assert digest(comparable(resumed))==digest(comparable(full))
    assert resumed['replay_work']['processed_bars']==130
    duplicate=replay(data,timeframe).run(warmup=30,checkpoint=resumed['replay_checkpoint'])
    assert duplicate['replay_work']['processed_bars']==0
    assert digest(comparable(duplicate))==digest(comparable(full))


@pytest.mark.parametrize('definition',[
    AdaptiveParameters(),
    StrategyDefinition('volatility_trend',24,threshold=.01),
    StrategyDefinition('breakout_liquidity',24,volume_ratio=1.1),
    StrategyDefinition('defensive_mean_reversion',24,z_entry=-1.5),
    StrategyDefinition('intraday_breakout',12,threshold=.005,volume_ratio=1.1,timeframe='15m'),
])
def test_all_automatic_families_resume_without_training_state(definition):
    timeframe=getattr(definition,'timeframe','1h')
    data=market_data(timeframe)
    factory=candidate_factory(definition)
    first=replay({symbol:rows[:160] for symbol,rows in data.items()},timeframe,factory).run(
        warmup=97,save_checkpoint=True)
    resumed=replay(data,timeframe,factory).run(warmup=97,checkpoint=first['replay_checkpoint'])
    full=replay(data,timeframe,factory).run(warmup=97)
    assert digest(comparable(resumed))==digest(comparable(full))


@pytest.mark.parametrize('change',['revision','removed','late','corrupt','settings'])
def test_changed_inputs_or_corrupted_state_block_resume(change):
    data=market_data()
    first=replay(data,'1h').run(warmup=30,save_checkpoint=True)
    checkpoint=json.loads(json.dumps(first['replay_checkpoint']))
    kwargs={}
    if change=='revision':
        row=data['BTC/EUR'][10]
        data['BTC/EUR'][10]=replace(row,close=row.close+1)
    elif change=='removed':
        data['BTC/EUR']=data['BTC/EUR'][1:]
    elif change=='late':
        data['NEW/EUR']=data['BTC/EUR']
    elif change=='corrupt':
        checkpoint['state']['engine']['cash']+=1
    elif change=='settings':
        kwargs['participation_rate']=.02
    with pytest.raises(CheckpointInvalid):
        replay(data,'1h',**kwargs).run(warmup=30,checkpoint=checkpoint)


def test_unserializable_learned_model_and_terminal_liquidation_cannot_checkpoint():
    with pytest.raises(ValueError,match='rule strategies'):
        replay(market_data(),'1h',lambda _:Buyer()).run(warmup=30,save_checkpoint=True)
    with pytest.raises(ValueError,match='rule strategies'):
        PortfolioBacktestEngine(market_data(),risk=risk(entry_strategy='momentum'),
            select_assets=False).run(warmup=30,save_checkpoint=True)


def test_recovered_market_coverage_does_not_keep_stale_warning():
    data=market_data()
    data['ETH/EUR']=[row for i,row in enumerate(data['ETH/EUR']) if not 126<=i<130]
    boundary=data['BTC/EUR'][130].timestamp
    first=replay({symbol:[row for row in rows if row.timestamp<boundary] for symbol,rows in data.items()},'1h').run(
        warmup=30,save_checkpoint=True)
    assert 'Some assets lack full-period benchmark coverage' in first['data_limitations']
    resumed=replay(data,'1h').run(warmup=30,checkpoint=first['replay_checkpoint'])
    assert digest(comparable(resumed))==digest(comparable(replay(data,'1h').run(warmup=30)))


def test_full_mode_cannot_bypass_revision_check():
    from app.services.strategy_research import _shadow_replay
    data=market_data()
    common=dict(candles_by_symbol=data,risk=risk(entry_strategy='momentum'),select_assets=False,liquidate_end=False)
    first,_=_shadow_replay(common,{'warmup':30},None,'full')
    row=data['BTC/EUR'][10]
    data['BTC/EUR'][10]=replace(row,close=row.close+1)
    with pytest.raises(CheckpointInvalid):
        _shadow_replay(common,{'warmup':30},first['replay_checkpoint'],'full')


@pytest.mark.parametrize('timeframe',['1h','15m'])
def test_database_resume_comparison_and_revision_preserve_ledger(setup_bot,monkeypatch,timeframe):
    c=setup_bot
    monkeypatch.setenv('SHADOW_REPLAY_MODE','compare')
    data=market_data(timeframe,count=760)
    definition=AdaptiveParameters() if timeframe=='1h' else StrategyDefinition(
        'intraday_breakout',12,threshold=.005,volume_ratio=1.1,timeframe='15m')
    tested=data['BTC/EUR'][720].timestamp
    c.db.add(StrategyCandidate(user_id=c.user.id,candidate_id='incremental-test',
        parameters=candidate_parameters(definition),status='PAPER_APPROVED',metrics={},tested_at=tested))
    c.db.commit()
    first={symbol:rows[:745] for symbol,rows in data.items()}
    assert advance_shadow_candidates(c.db,c.user.id,data_snapshot=first if timeframe=='1h' else None,
        timeframe_snapshots={timeframe:first},now=data['BTC/EUR'][-1].timestamp)
    c.db.expire_all()  # Reload JSON state from persistence, as on process restart.
    assert advance_shadow_candidates(c.db,c.user.id,timeframe_snapshots={timeframe:data},
        now=data['BTC/EUR'][-1].timestamp)
    run=c.db.query(ShadowRun).one()
    assert set(run.metrics['checkpoints'])=={'normal','stress','benchmark'}
    assert all(item['processed_bars']==15 and item['parity_verified'] for item in run.metrics['replay'].values())
    before=(c.db.query(ShadowTrade).count(),c.db.query(ShadowEquity).count())
    advance_shadow_candidates(c.db,c.user.id,timeframe_snapshots={timeframe:data},now=data['BTC/EUR'][-1].timestamp)
    assert all(item['processed_bars']==0 for item in run.metrics['replay'].values())
    assert before==(c.db.query(ShadowTrade).count(),c.db.query(ShadowEquity).count())
    row=data['BTC/EUR'][740]
    data['BTC/EUR'][740]=replace(row,close=row.close+1)
    update=advance_shadow_candidates(c.db,c.user.id,timeframe_snapshots={timeframe:data},now=data['BTC/EUR'][-1].timestamp)
    assert update[0]['status']=='REJECTED' and run.status=='INVALIDATED'
    assert before==(c.db.query(ShadowTrade).count(),c.db.query(ShadowEquity).count())
    assert c.db.query(ExecutionOrder).count()==0
