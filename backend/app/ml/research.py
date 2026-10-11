"""File-backed research protocol: explicit provenance, sealed holdout, append-only runs."""
import csv
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from app.exchanges.base import OHLCV
from app.ml.backtest import PortfolioBacktestEngine
from app.ml.evaluation import digest
from app.ml.models import SignalModel
from app.ml.strategies import MomentumModel, PayoffModel, WindowedSignalModel, FastMomentumModel, AdaptiveMomentumModel, AdaptiveParameters
from app.services.market_data import completed_candles, INTERVALS
from app.services.market_data import candle_boundary
from app.ml.strategy_factory import StrategyDefinition, candidate_factory, candidate_parameters, candidate_risk
from app.services.research_service import candidate_identity, code_identity
from app.services.risk_service import RiskManager

RESEARCH_CANDIDATES={'auto','signal-v2','momentum','fast-momentum','payoff','normalized-3m','normalized-6m','normalized-12m','intraday-breakout'}


def intraday_definition(protocol):
    values={'lookback':24,'threshold':.01,'volume_ratio':1.5,**protocol.get('intraday_parameters',{})}
    return StrategyDefinition(family='intraday_breakout',timeframe='15m',**values)


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Research timestamps require timezone offsets')
    return result.astimezone(timezone.utc)


def write_json(path, value):
    # Exclusive create prevents accidental overwrites of research evidence.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str, allow_nan=False)


def load_dataset(manifest_path, allow_no_trade_gaps=False,timeframe=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    declared=manifest.get('timeframe','1h')
    timeframe=timeframe or declared
    if timeframe not in {'1h','15m'} or declared!=timeframe:
        raise ValueError('Manifest and protocol must agree on supported 1h or 15m timeframe')
    data, provenance = {}, {}
    for asset in manifest['assets']:
        symbol = asset['symbol']
        if symbol in data or not asset.get('source') or not asset.get('sha256'):
            raise ValueError('Unique symbols, source attribution and SHA256 are required')
        path = manifest_path.parent / asset['file']
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != asset['sha256']:
            raise ValueError(f'{symbol}: source checksum mismatch')
        with path.open(newline='', encoding='utf-8-sig') as stream:
            rows = [OHLCV(timestamp(r['timestamp']), *[float(r[k]) for k in ('open','high','low','close','volume')])
                    for r in csv.DictReader(stream)]
        clean = completed_candles(rows,timeframe)
        if not clean or len(clean) != len(rows) or [c.timestamp for c in clean] != [c.timestamp for c in rows]:
            raise ValueError(f'{symbol}: empty, unordered, duplicate or unfinished candles')
        gaps=sum(b.timestamp-a.timestamp != INTERVALS[timeframe] for a,b in zip(clean,clean[1:]))
        if gaps and not allow_no_trade_gaps:
            raise ValueError(f'{symbol}: history has missing {timeframe} intervals')
        if any(c.timestamp!=candle_boundary(c.timestamp,timeframe) for c in clean):
            raise ValueError(f'{symbol}: timestamps must align to UTC {timeframe} boundaries')
        data[symbol] = clean
        provenance[symbol] = {**asset, 'rows': len(clean), 'first': clean[0].timestamp, 'last': clean[-1].timestamp,'gaps':gaps}
    if not data: raise ValueError('Manifest has no assets')
    return data, provenance


def register(manifest_path, protocol_path, output):
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    timeframe=protocol.get('timeframe','1h')
    data, provenance = load_dataset(manifest_path,protocol.get('allow_no_trade_gaps',False),timeframe)
    start, holdout, end = (timestamp(protocol[k]) for k in ('development_start', 'holdout_start', 'end'))
    if not start < holdout < end:
        raise ValueError('Require development_start < holdout_start < end')
    risk = RiskManager(**protocol['risk'])
    from app.ml.exit_experiments import ExitExperiment
    exit_policy=ExitExperiment(**protocol.get('exit_experiment',{}))
    if exit_policy.variant!='fixed' and risk.risk_per_trade_pct<=0:
        raise ValueError('Exit experiments require an explicit matched per-trade risk budget')
    AdaptiveParameters(**protocol.get('adaptive_parameters',{}))
    if risk.fee_pct < 0 or risk.fee_pct >= .5 or risk.slippage_pct < 0 or risk.slippage_pct >= .5:
        raise ValueError('Invalid costs for 2x stress evaluation')
    if not any(rows[0].timestamp < start and rows[-1].timestamp >= end-INTERVALS[timeframe] for rows in data.values()):
        raise ValueError('At least one asset must cover warmup and complete evaluation window')
    candidates = protocol.get('candidates', ['signal-v2', 'momentum', 'payoff'])
    if not candidates or len(set(candidates)) != len(candidates) or set(candidates)-RESEARCH_CANDIDATES:
        raise ValueError('Unsupported or duplicate candidate')
    if timeframe=='15m':
        intraday_definition(protocol)
        if set(candidates)-{'intraday-breakout','momentum'} or protocol.get('select_assets',True):
            raise ValueError('15m protocol requires intraday/momentum candidates and select_assets=False')
    elif 'intraday-breakout' in candidates:
        raise ValueError('Intraday breakout requires 15m data')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    record = {'manifest': str(Path(manifest_path).resolve()), 'provenance': provenance,
              'protocol': protocol, 'registered_at': datetime.now(timezone.utc), 'code_id': code_identity()}
    record['protocol_id'] = digest(record)
    write_json(output/'protocol.json', record)
    return record


def run_experiment(directory, stage='development', candidate='signal-v2',progress=None):
    if stage not in {'development','holdout'}:
        raise ValueError('Unknown evaluation stage')
    directory = Path(directory)
    registered = json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    protocol = registered['protocol']
    timeframe=protocol.get('timeframe','1h')
    if registered['code_id'] != code_identity():
        raise ValueError('Research code changed; register a new protocol and treat prior holdout as consumed')
    if candidate not in protocol.get('candidates', ['signal-v2','momentum','payoff']):
        raise ValueError('Candidate was not preregistered')
    data, provenance = load_dataset(registered['manifest'],protocol.get('allow_no_trade_gaps',False),timeframe)
    if digest(provenance) != digest(registered['provenance']):
        raise ValueError('Dataset changed after registration')
    risk = RiskManager(**protocol['risk'])
    factories = {'signal-v2': lambda _: SignalModel(persist=False), 'momentum': lambda _: MomentumModel(lookback=96 if timeframe=='15m' else 24),
                 'auto': lambda _: AdaptiveMomentumModel(parameters=AdaptiveParameters(**protocol.get('adaptive_parameters',{}))),
                 'fast-momentum': lambda _: FastMomentumModel(),
                 'payoff': lambda _: PayoffModel(),
                 'normalized-3m':lambda _:WindowedSignalModel(90*24),
                 'normalized-6m':lambda _:WindowedSignalModel(180*24),
                 'normalized-12m':lambda _:WindowedSignalModel(365*24)}
    if timeframe=='15m':
        factories['intraday-breakout']=candidate_factory(intraday_definition(protocol))
    start = timestamp(protocol['development_start'] if stage == 'development' else protocol['holdout_start'])
    end = timestamp(protocol['holdout_start'] if stage == 'development' else protocol['end'])
    if stage == 'holdout':
        frozen = json.loads((directory/'candidate.json').read_text(encoding='utf-8'))
        if frozen['candidate'] != candidate or frozen['candidate_id'] != candidate_identity(risk,candidate):
            raise ValueError('Holdout must use frozen candidate')
        write_json(directory/'holdout-consumed.json', {'candidate': candidate, 'started_at': datetime.now(timezone.utc)})
    # Development never passes holdout candles to the engine or its data fingerprint.
    data = {s:[c for c in rows if c.timestamp < end] for s,rows in data.items()}
    def evaluate(strategy, costs=1.):
        if progress:
            progress(f'Evaluating {strategy} on {timeframe} candles at {costs:g}x costs ({stage})')
        effective=candidate_risk(risk,intraday_definition(protocol)) if timeframe=='15m' else risk
        configured = replace(effective, fee_pct=risk.fee_pct*costs, slippage_pct=risk.slippage_pct*costs,
                             entry_strategy={'auto':'auto','momentum':'momentum','fast-momentum':'fast_momentum','intraday-breakout':'auto'}.get(strategy,'model'))
        return PortfolioBacktestEngine(data, risk=configured, start_date=start, end_date=end,
            initial_cash=protocol.get('initial_cash',500.), select_assets=protocol.get('select_assets',True),
            model_factory=factories[strategy], strategy_id=strategy,
            minimum_order_eur=protocol.get('minimum_order_eur',0.),
            participation_rate=protocol.get('participation_rate',.01),
            allow_no_trade_gaps=protocol.get('allow_no_trade_gaps',False),
            exit_experiment=protocol.get('exit_experiment'),timeframe=timeframe).run(warmup=protocol.get('warmup',97 if timeframe=='15m' else 720))
    base = evaluate(candidate)
    stress = evaluate(candidate,2.)
    simple = evaluate('momentum')
    base['stage'] = stage
    if timeframe=='15m' and candidate=='intraday-breakout':
        base['strategy_parameters']=candidate_parameters(intraday_definition(protocol))
    base['candidate_id'] = candidate_identity(risk,candidate)
    base['protocol_id'] = registered['protocol_id']
    base['stress_passed'] = stress['expectancy'] > 0 and stress['total_return_pct'] > 0 and abs(stress['max_drawdown_pct']) <= risk.max_drawdown_pct
    alternatives = [v for v in base['benchmarks'].values() if v is not None] + [simple['total_return_pct']]
    base['benchmark_advantage'] = base['total_return_pct'] > max(alternatives) and abs(base['max_drawdown_pct']) <= risk.max_drawdown_pct
    if not protocol.get('historical_universe_evidence'):
        base['data_limitations'].append('Point-in-time universe provenance not supplied')
    base['data_limitations'].append('Historical execution uses modeled liquidity rather than depth/fill evidence')
    artifact = {'result':base, 'cost_stress':stress, 'momentum_baseline':simple, 'provenance':provenance}
    name = f'{stage}-{candidate}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")}.json'
    write_json(directory/name, artifact)
    with (directory/'experiments.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'artifact':name,'candidate':candidate,'stage':stage,'run_id':base['experiment']['run_id']})+'\n')
    return directory/name


def freeze(directory, candidate):
    directory = Path(directory)
    registered = json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    if registered['code_id'] != code_identity(): raise ValueError('Code changed since registration')
    if candidate not in registered['protocol'].get('candidates',['signal-v2','momentum','payoff']):
        raise ValueError('Candidate not registered')
    records = [json.loads(line) for line in (directory/'experiments.jsonl').read_text().splitlines()]
    if not any(r['candidate']==candidate and r['stage']=='development' for r in records):
        raise ValueError('Run development evaluation before freezing')
    return write_json(directory/'candidate.json', {'candidate':candidate,
        'candidate_id':candidate_identity(RiskManager(**registered['protocol']['risk']),candidate),
        'frozen_at':datetime.now(timezone.utc)})
