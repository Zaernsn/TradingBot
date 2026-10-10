from datetime import timedelta
from types import SimpleNamespace
import pytest

from app.ml.exit_experiments import ExitExperiment
from tests.test_research import rows, risk, engine
from app.exchanges.base import OHLCV


def test_atr_uses_completed_history_and_bounded_distance():
    policy=ExitExperiment(variant='atr')
    data=rows(20,swing=1)
    assert policy.initial_stop_pct(data,100,.03)==pytest.approx(.04)
    assert policy.initial_stop_pct(rows(20,swing=90),100,.03)==.1
    with pytest.raises(ValueError): policy.initial_stop_pct(data[:10],100,.03)


def test_trailing_waits_for_prior_completed_bar_high_and_exports_state():
    data=rows(5)
    data[2]=OHLCV(data[2].timestamp,100,105,99,104,10000)
    data[3]=OHLCV(data[3].timestamp,104,104,103,104,10000)
    result=engine({'BTC/EUR':data[:4]},risk=risk(),liquidate_end=False,
                  exit_experiment={'variant':'trailing'}).run(warmup=2)
    # Raising this candle's high cannot retroactively tighten its own stop.
    assert not [t for t in result['trades'] if t['side']=='SELL']
    assert result['open_positions']['BTC/EUR']['high_water_price']==105
    result=engine({'BTC/EUR':data},risk=risk(),exit_experiment={'variant':'trailing'}).run(warmup=2)
    # Next-bar gap below the armed trailing barrier fills at the gap, not the barrier.
    assert result['trades'][1]['side']=='SELL' and result['trades'][1]['price']==100


def test_no_progress_and_time_are_separate_experiments():
    start=rows(1)[0].timestamp
    position=SimpleNamespace(opened_at=start,avg_entry_price=100)
    assert ExitExperiment(variant='no-progress').time_exit(position,100,start+timedelta(hours=12))
    assert not ExitExperiment(variant='no-progress').time_exit(position,102,start+timedelta(hours=12))
    assert ExitExperiment(variant='time').time_exit(position,105,start+timedelta(hours=24))
    assert not ExitExperiment().time_exit(position,100,start+timedelta(days=7))


def test_rolling_loss_halt_does_not_disable_existing_exits():
    data=rows(5)
    data[2]=OHLCV(data[2].timestamp,100,100,98,98,10000)
    data[3]=OHLCV(data[3].timestamp,98,98,90,90,10000)
    result=engine({'BTC/EUR':data},risk=risk(daily_loss_pct=.001)).run(warmup=2)
    assert result['risk_halted']
    assert any(t['side']=='SELL' for t in result['trades'])
