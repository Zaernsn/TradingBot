"""Reproducible synthetic replay timing; never evaluates profitability or trades live.

From backend: python -m app.cli.benchmark_shadow --output ../docs/shadow-replay-benchmark.json
"""
import argparse
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

from app.exchanges.base import OHLCV
from app.ml.evaluation import digest
from app.ml.strategies import AdaptiveParameters
from app.ml.strategy_factory import StrategyDefinition, candidate_factory
from app.services.research_service import code_identity
from app.services.risk_service import RiskManager
from app.services.strategy_research import _shadow_replay


def benchmark(count=720, new_bars=5, repeats=3):
    if count<200 or not 1<=new_bars<count-100 or repeats<1:
        raise ValueError('Require >=200 bars, a nonempty warmed prefix, and >=1 repeat')
    measurements=[]
    for timeframe in ('1h','15m'):
        interval=timedelta(minutes=60 if timeframe=='1h' else 15)
        data={}
        for symbol in ('BTC/EUR','ETH/EUR','SOL/EUR'):
            rows=[]; price=100.
            for i in range(count):
                price*=1.002+math.sin(i/20)*.004
                rows.append(OHLCV(datetime(2025,1,1,tzinfo=timezone.utc)+i*interval,
                    price,price*1.01,price*.99,price,20000. if i%6==0 else 10000.))
            data[symbol]=rows
        parameters=AdaptiveParameters() if timeframe=='1h' else StrategyDefinition(
            'intraday_breakout',12,threshold=.005,volume_ratio=1.1,timeframe='15m')
        risk=RiskManager(.2,.04,.1,.0026,10,None,48 if timeframe=='15m' else 12,5,
            entry_strategy='auto',slippage_pct=.001,max_drawdown_pct=.9)
        common=dict(candles_by_symbol=data,initial_cash=500.,risk=risk,select_assets=False,
            model_factory=candidate_factory(parameters),strategy_id='timing-'+timeframe,
            liquidate_end=False,timeframe=timeframe,allow_no_trade_gaps=True)
        settings={'warmup':97 if timeframe=='15m' else 30}
        for scenario in ('normal','stress','benchmark'):
            arguments=dict(common)
            if scenario=='stress':
                arguments['risk']=replace(risk,fee_pct=risk.fee_pct*2,slippage_pct=risk.slippage_pct*2)
            elif scenario=='benchmark':
                arguments.update(risk=replace(risk,entry_strategy='momentum'),model_factory=None,strategy_id='momentum')
            prefix={symbol:rows[:-new_bars] for symbol,rows in data.items()}
            seed,_=_shadow_replay({**arguments,'candles_by_symbol':prefix},settings,None,'incremental')
            full_times=[]; incremental_times=[]
            for _ in range(repeats):
                started=perf_counter()
                full,_=_shadow_replay(arguments,settings,None,'full')
                full_times.append(perf_counter()-started)
                started=perf_counter()
                incremental,work=_shadow_replay(arguments,settings,seed['replay_checkpoint'],'incremental')
                incremental_times.append(perf_counter()-started)
                comparable=lambda result:{key:value for key,value in result.items()
                    if key not in {'replay_checkpoint','replay_work'}}
                if digest(comparable(full))!=digest(comparable(incremental)):
                    raise AssertionError('Full/incremental benchmark parity failed')
            duplicate,duplicate_work=_shadow_replay(arguments,settings,incremental['replay_checkpoint'],'incremental')
            if digest(comparable(duplicate))!=digest(comparable(full)):
                raise AssertionError('Duplicate replay parity failed')
            measurements.append({'timeframe':timeframe,'scenario':scenario,'parity_verified':True,
                'full_bars':full['replay_work']['processed_bars'],'incremental_bars':work['processed_bars'],
                'duplicate_bars':duplicate_work['processed_bars'],
                'full_seconds_median':median(full_times),'incremental_seconds_median':median(incremental_times),
                'speedup':median(full_times)/median(incremental_times)})
    return {'created_at':datetime.now(timezone.utc).isoformat(),'code_identity':code_identity(),
        'fixture':'deterministic synthetic three-market history; not a performance/edge study',
        'input_bars_per_market':count,'new_bars':new_bars,'repeats':repeats,
        'scope':'engine construction, replay, integrity hashes, statistics, checkpoint serialization; excludes database/network',
        'measurements':measurements}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--bars',type=int,default=720)
    parser.add_argument('--new-bars',type=int,default=5)
    parser.add_argument('--repeats',type=int,default=3)
    options=parser.parse_args()
    report=benchmark(options.bars,options.new_bars,options.repeats)
    content=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if options.output:
        options.output.write_text(content,encoding='utf-8')
    print(content)
