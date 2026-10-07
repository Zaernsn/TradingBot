from dataclasses import replace
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import csv
import hashlib
import json

import pytest

from app.exchanges.base import OHLCV
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.evaluation import promotion_report, mean_interval
from app.ml.research import register, run_experiment, freeze, load_dataset
from app.services.asset_selector import AssetSelector
from app.services.risk_service import RiskManager, entry_budget
from app.services.trading_service import exit_reason


def rows(count=80, start=None, swing=0.):
    start = start or datetime(2024,1,1,tzinfo=timezone.utc)
    return [OHLCV(start+timedelta(hours=i),100,100+swing,100-swing,100,10000) for i in range(count)]


def risk(**kwargs):
    return replace(RiskManager(.5,.03,.06,0.,10,None,12,2,
                              slippage_pct=0.,max_total_exposure_pct=1.,max_correlated_exposure_pct=1.),**kwargs)


class Buyer:
    is_fitted = False
    def fit(self, history, **kwargs): self.is_fitted=True
    def predict(self, history): return {'action':'BUY'}


def engine(data, **kwargs):
    return PortfolioBacktestEngine(data, model_factory=lambda _:Buyer(), select_assets=False, **kwargs)


def test_intrabar_stop_first_and_shared_saved_risk():
    data=rows(4)
    data[2]=OHLCV(data[2].timestamp,100,110,90,100,10000)
    result=engine({'BTC/EUR':data},risk=risk(max_invest_per_trade_eur=40.)).run(warmup=2)
    assert result['trades'][0]['quantity']==pytest.approx(.4)
    assert result['trades'][1]['price']==97
    assert result['trades'][1]['pnl']==pytest.approx(-1.2)
    assert result['final_equity']==pytest.approx(500+sum(t['pnl'] or 0 for t in result['trades']))


def test_gap_stop_fills_at_open_not_stop():
    data=rows(4)
    data[3]=OHLCV(data[3].timestamp,80,80,80,80,10000)
    result=engine({'BTC/EUR':data},risk=risk()).run(warmup=2)
    assert result['trades'][1]['price']==80


def test_later_listing_does_not_truncate_earlier_asset():
    data=rows(60)
    result=engine({'BTC/EUR':data,'ETH/EUR':data[30:]},risk=risk()).run(warmup=10)
    assert result['evaluation_start']==data[10].timestamp
    eth=[t for t in result['trades'] if t['symbol']=='ETH/EUR']
    assert eth and eth[0]['timestamp']>=data[40].timestamp
    assert 'Some assets lack full-period benchmark coverage' in result['data_limitations']


def test_missing_terminal_data_is_not_a_fabricated_fill():
    data=rows(60)
    result=engine({'BTC/EUR':data,'ETH/EUR':data[:40]},risk=risk()).run(warmup=10)
    assert any('Stale terminal mark' in text for text in result['data_limitations'])
    assert not any(t['side']=='SELL' and t['symbol']=='ETH/EUR' for t in result['trades'])


def test_reproducible_ids_duplicate_rejection_and_costs():
    data={'BTC/EUR':rows()}
    a=engine(data,risk=risk()).run(warmup=10)
    b=engine(data,risk=risk()).run(warmup=10)
    assert a['experiment']==b['experiment']
    expensive=engine(data,risk=risk(fee_pct=.004)).run(warmup=10)
    assert expensive['final_equity']<a['final_equity']
    with pytest.raises(ValueError,match='Duplicate'):
        engine({'BTC/EUR':rows()+rows()})


def test_only_past_volume_limits_entry():
    data=rows(4)
    data[1].volume=.1
    result=engine({'BTC/EUR':data},risk=risk(),participation_rate=.01).run(warmup=2)
    assert result['trades'][0]['quantity']==pytest.approx(.001)


def test_volatility_budget_reduces_size_and_preserves_caps():
    quiet=rows(40)
    volatile=rows(40)
    for i,c in enumerate(volatile): c.close=100+(10 if i%2 else -10)
    portfolio=SimpleNamespace(equity=500.,cash=500.)
    configured=risk(risk_per_trade_pct=.005,max_invest_per_trade_eur=100.)
    small=entry_budget(portfolio,configured,'BTC/EUR',[],{'BTC/EUR':volatile})
    large=entry_budget(portfolio,configured,'BTC/EUR',[],{'BTC/EUR':quiet})
    assert 0<small<large<=100
    assert entry_budget(portfolio,configured,'BTC/EUR',[],{})==0


def test_max_holding_exit_and_unchanged_default():
    opened=datetime(2024,1,1,tzinfo=timezone.utc)
    position=SimpleNamespace(avg_entry_price=100,opened_at=opened)
    assert exit_reason(position,risk(),100,now=opened+timedelta(hours=100)) is None
    assert exit_reason(position,risk(max_holding_hours=24),100,now=opened+timedelta(hours=24))=='Maximum holding period'


def test_selector_annualization_is_timeframe_aware():
    candles=[{'close':100*(1.005**i)*(1.001 if i%2 else 1),'volume':100} for i in range(31)]
    selector=AssetSelector(min_volatility=.08,max_volatility=2.)
    assert selector.select({'X':candles},timeframe='1d')==[]
    assert selector.select({'X':candles},timeframe='1h')==['X']


def test_promotion_fails_closed_and_never_authorizes_live():
    report=promotion_report({}, {})
    assert report['decision']=='NO_GO' and not report['live_authorized']
    assert mean_interval([.01]*100)==mean_interval([.01]*100)
    good=dict(expectancy=1.,hourly_mean_return_interval={'low':.001},max_drawdown_pct=-.02,
              closed_trades=200,candidate_id='same',stage='holdout',stress_passed=True,benchmark_advantage=True,
              observed_days=60,version_consistent=True,cost_overrun_pct=0.,unresolved_orders=0)
    assert promotion_report(good,good)['decision']=='READY_FOR_SUPERVISED_ACCEPTANCE'
    assert not promotion_report(good,good)['live_authorized']
    assert promotion_report({**good,'expectancy':float('nan')},good)['decision']=='NO_GO'


def test_protocol_provenance_freeze_and_single_use_holdout(tmp_path):
    source=tmp_path/'btc.csv'
    data=rows(90)
    with source.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['timestamp','open','high','low','close','volume'])
        writer.writeheader()
        for c in data: writer.writerow(vars(c))
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'assets':[{'symbol':'BTC/EUR','file':'btc.csv','source':'synthetic test only',
        'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    protocol=tmp_path/'spec.json'
    from dataclasses import asdict
    protocol.write_text(json.dumps({'risk':asdict(risk()),'development_start':data[30].timestamp.isoformat(),
        'holdout_start':data[60].timestamp.isoformat(),'end':(data[-1].timestamp+timedelta(hours=1)).isoformat(),
        'candidates':['momentum'],'warmup':25,'select_assets':False}))
    output=tmp_path/'experiment'
    register(manifest,protocol,output)
    artifact=run_experiment(output,candidate='momentum')
    result=json.loads(artifact.read_text())['result']
    assert result['evaluation_end'].startswith('2024-01-03 12:00')
    freeze(output,'momentum')
    run_experiment(output,stage='holdout',candidate='momentum')
    with pytest.raises(FileExistsError): run_experiment(output,stage='holdout',candidate='momentum')
    source.write_text(source.read_text()+'\n')
    with pytest.raises(ValueError,match='checksum'): load_dataset(manifest)
