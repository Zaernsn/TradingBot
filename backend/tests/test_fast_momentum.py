from types import SimpleNamespace
from app.ml.strategies import FastMomentumModel


def data(last=102, volume=1500):
    return [SimpleNamespace(close=100., volume=1000.) for _ in range(24)] + [SimpleNamespace(close=last,volume=volume)]


def test_breakout_requires_volume_and_cost_coverage():
    model=FastMomentumModel().fit([],fee_pct=.0026,slippage_pct=.001)
    assert model.predict(data())['action']=='BUY'
    assert model.predict(data(volume=500))['action']=='HOLD'
    assert model.predict(data(last=100.4))['action']=='HOLD'
    assert model.predict(data(last=110))['action']=='HOLD'
    assert 'probability' not in model.predict(data())


def test_reversal_exits_and_invalid_data_holds():
    model=FastMomentumModel().fit([])
    assert model.predict(data(last=98))['action']=='SELL'
    assert model.predict(data(last=float('nan')))['action']=='HOLD'
    assert model.predict(data()[:10])['action']=='HOLD'
