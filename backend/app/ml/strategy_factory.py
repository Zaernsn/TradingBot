"""Constrained strategy generation and promotion; never executes an order."""
from dataclasses import asdict, dataclass, replace
from app.ml.strategies import (
    AdaptiveParameters, AdaptiveMomentumModel, VolatilityTrendModel,
    BreakoutLiquidityModel, DefensiveMeanReversionModel, IntradayBreakoutModel,
)


@dataclass(frozen=True)
class StrategyDefinition:
    family: str
    lookback: int
    threshold: float = 0.
    volume_ratio: float = 0.
    z_entry: float = 0.
    timeframe: str = '1h'

    def __post_init__(self):
        if self.family=='intraday_breakout':
            if self.timeframe!='15m' or not 8<=self.lookback<=96 or not .005<=self.threshold<=.10 or not 1.05<=self.volume_ratio<=3.:
                raise ValueError('Intraday parameters require bounded 15-minute configuration')
            return
        if self.family not in {'volatility_trend','breakout_liquidity','defensive_mean_reversion'} or self.timeframe!='1h':
            raise ValueError('Unknown generated strategy family')
        if not 24<=self.lookback<=168:
            raise ValueError('Generated strategy lookback is outside bounds')
        if self.family=='volatility_trend' and not .005<=self.threshold<=.10:
            raise ValueError('Volatility-trend threshold is outside bounds')
        if self.family=='breakout_liquidity' and not 1.05<=self.volume_ratio<=3.:
            raise ValueError('Breakout volume ratio is outside bounds')
        if self.family=='defensive_mean_reversion' and not -4.<=self.z_entry<=-1.:
            raise ValueError('Mean-reversion entry is outside bounds')


def generated_candidates():
    """A small declared grammar avoids arbitrary self-written live code."""
    rows=(
        (.55,0,.70,.005,.0125), (.60,0,.70,.0075,.015),
        (.60,.0025,.70,.0075,.015), (.60,.005,.75,.01,.02),
        (.65,0,.75,.0075,.0125), (.65,.0025,.75,.0075,.015),
        (.65,.005,.75,.01,.02), (.70,.0025,.80,.01,.015),
        (.70,.005,.80,.0125,.02), (.75,.005,.85,.015,.025),
        (.55,.0025,.75,.01,.02), (.60,.0025,.80,.0125,.025),
    )
    adaptive=[AdaptiveParameters(*row) for row in rows]
    families=[
        StrategyDefinition('volatility_trend',48,threshold=.015),
        StrategyDefinition('volatility_trend',72,threshold=.02),
        StrategyDefinition('volatility_trend',120,threshold=.03),
        StrategyDefinition('breakout_liquidity',24,volume_ratio=1.25),
        StrategyDefinition('breakout_liquidity',48,volume_ratio=1.5),
        StrategyDefinition('breakout_liquidity',72,volume_ratio=2.),
        StrategyDefinition('defensive_mean_reversion',24,z_entry=-1.5),
        StrategyDefinition('defensive_mean_reversion',48,z_entry=-2.),
        StrategyDefinition('defensive_mean_reversion',72,z_entry=-2.5),
    ]
    intraday=[StrategyDefinition('intraday_breakout',lookback,threshold=threshold,volume_ratio=volume,timeframe='15m')
              for lookback,threshold,volume in ((12,.0075,1.25),(24,.01,1.5),(48,.015,2.))]
    return intraday+adaptive+families


def derived_candidates(evaluated, successive=False):
    """Create a tiny second generation inside the declared safe grammar.

    The bot may tune parameters, but it cannot author executable code, expand
    risk limits, or create an unbounded multiple-testing loop.
    """
    base=generated_candidates(); base_ids={candidate_id(value) for value in base}
    rows=list(evaluated) if successive else [row for row in evaluated if row.candidate_id in base_ids]
    # Freeze the parent pool before generating children. Final-test outcomes
    # must never influence mutations, including after a parent is refreshed.
    if not successive and {row.candidate_id for row in rows} != base_ids:
        return []
    def family(row): return row.parameters.get('family','adaptive_momentum')
    def score(row):
        metrics=row.metrics or {}
        development=metrics.get('generation_development',metrics.get('development',{}))
        return (float(development.get('expectancy') or 0.),
                float(development.get('total_return_pct') or 0.),row.candidate_id)
    children=[]
    for name in ('adaptive_momentum','volatility_trend','breakout_liquidity','defensive_mean_reversion','intraday_breakout'):
        matches=[row for row in rows if family(row)==name]
        if not matches: continue
        parent=definition_from_parameters(max(matches,key=score).parameters)
        if isinstance(parent,AdaptiveParameters):
            for delta in (-.0025,.0025):
                value=max(.005,min(.10,parent.momentum_threshold+delta))
                children.append(AdaptiveParameters(parent.trend_breadth,parent.trend_return,
                    parent.acceleration_breadth,parent.acceleration_return,value))
        elif name=='volatility_trend':
            children.extend([StrategyDefinition(name,max(24,parent.lookback-12),max(.005,parent.threshold*.85)),
                             StrategyDefinition(name,min(168,parent.lookback+12),min(.10,parent.threshold*1.15))])
        elif name=='breakout_liquidity':
            children.extend([StrategyDefinition(name,max(24,parent.lookback-12),volume_ratio=max(1.05,parent.volume_ratio-.15)),
                             StrategyDefinition(name,min(168,parent.lookback+12),volume_ratio=min(3.,parent.volume_ratio+.15))])
        elif name=='defensive_mean_reversion':
            children.extend([StrategyDefinition(name,max(24,parent.lookback-12),z_entry=max(-4.,parent.z_entry-.25)),
                             StrategyDefinition(name,min(168,parent.lookback+12),z_entry=min(-1.,parent.z_entry+.25))])
        else:
            children.extend([replace(parent,lookback=max(8,parent.lookback-4),threshold=max(.005,parent.threshold*.85)),
                             replace(parent,lookback=min(96,parent.lookback+4),threshold=min(.10,parent.threshold*1.15))])
    unique=[]; seen=base_ids
    # Reserve a first variation for each family before spending remaining slots.
    for child in children[::2]+children[1::2]:
        identity=candidate_id(child)
        if identity not in seen: unique.append(child); seen.add(identity)
    return unique[:8]


def candidate_parameters(parameters):
    # Keep the original adaptive representation stable. Existing databases and
    # exported metadata used this shape before multiple families were added.
    values=asdict(parameters)
    if values.get('timeframe')=='1h':
        values.pop('timeframe')  # Preserve existing hourly identities and exports.
    return values


def candidate_timeframe(parameters):
    return getattr(parameters,'timeframe','1h')


def candidate_warmup(parameters):
    return max(97,parameters.lookback+1) if candidate_timeframe(parameters)=='15m' else 30


def candidate_risk(risk,parameters):
    # A saved hourly volatility-sizing horizon keeps its duration at four bars/hour.
    return replace(risk,prediction_horizon=risk.prediction_horizon*4) if candidate_timeframe(parameters)=='15m' else risk


def candidate_id(parameters):
    values=candidate_parameters(parameters)
    prefix='adaptive' if isinstance(parameters,AdaptiveParameters) else 'strategy'
    return prefix+'-'+'-'.join(
        f'{key}={values[key] if isinstance(values[key],str) else f"{values[key]:g}"}'
        for key in sorted(values))


def candidate_factory(parameters):
    if isinstance(parameters,AdaptiveParameters):
        return lambda _: AdaptiveMomentumModel(parameters=parameters)
    if parameters.family=='intraday_breakout':
        return lambda _: IntradayBreakoutModel(lookback=parameters.lookback,threshold=parameters.threshold,volume_ratio=parameters.volume_ratio)
    if parameters.family=='volatility_trend':
        return lambda _: VolatilityTrendModel(lookback=parameters.lookback,threshold=parameters.threshold)
    if parameters.family=='breakout_liquidity':
        return lambda _: BreakoutLiquidityModel(lookback=parameters.lookback,volume_ratio=parameters.volume_ratio)
    return lambda _: DefensiveMeanReversionModel(lookback=parameters.lookback,z_entry=parameters.z_entry)


def definition_from_parameters(values):
    values=dict(values)
    family=values.pop('family','adaptive_momentum')
    return AdaptiveParameters(**values) if family=='adaptive_momentum' else StrategyDefinition(family=family,**values)


def promotion_decision(development, validation, stress, benchmark, holdout=None):
    """Fixed minimum gates. Passing approves paper use, never live use."""
    # `holdout` is optional only for callers of the old public helper. The live
    # research pipeline always supplies a separately embargoed holdout period.
    holdout=holdout or validation
    closed=holdout.get('closed_trades',holdout.get('num_trades',0)//2)
    concentration=float(holdout.get('top_five_profit_share') or 0.)
    passed=(development['expectancy']>0 and validation['expectancy']>0
            and holdout['expectancy']>0
            and holdout['total_return_pct']>max(0.,benchmark['total_return_pct'])
            and stress['expectancy']>0 and stress['total_return_pct']>0
            and holdout['max_drawdown_pct']>=-.08 and closed>=30
            and concentration<=.80)
    return {
        'decision':'PAPER_APPROVED' if passed else 'REJECTED',
        'live_authorized':False,
        'checks':{
            'development_expectancy_positive':development['expectancy']>0,
            'validation_expectancy_positive':validation['expectancy']>0,
            'holdout_expectancy_positive':holdout['expectancy']>0,
            'holdout_beats_cash':holdout['total_return_pct']>0,
            'holdout_beats_momentum':holdout['total_return_pct']>benchmark['total_return_pct'],
            'stress_positive':stress['expectancy']>0 and stress['total_return_pct']>0,
            'drawdown_within_8pct':holdout['max_drawdown_pct']>=-.08,
            'holdout_closed_trades_at_least_30':closed>=30,
            'profit_concentration_within_80pct':concentration<=.80,
        },
    }


def shadow_promotion_decision(shadow, stress, benchmark, observed_days,
                              min_days=0, max_days=30, min_closed_trades=30):
    """Promote only frozen, genuinely forward shadow evidence.

    No calendar minimum applies by default: completed forward trades and net
    performance qualify a small live pilot, not proof of a profitable strategy.
    The candidate remains active while evidence is immature. After the maximum
    observation window, a candidate that still misses a gate is rejected so a
    weak strategy cannot wait indefinitely for one lucky period.
    """
    closed=int(shadow.get('closed_trades') or 0)
    checks={
        'minimum_forward_days':observed_days>=min_days,
        'minimum_closed_trades':closed>=min_closed_trades,
        'shadow_expectancy_positive':float(shadow.get('expectancy') or 0.)>0,
        'shadow_return_positive':float(shadow.get('total_return_pct') or 0.)>0,
        'shadow_beats_momentum':float(shadow.get('total_return_pct') or 0.)>
                                float(benchmark.get('total_return_pct') or 0.),
        'stress_positive':float(stress.get('expectancy') or 0.)>0 and
                          float(stress.get('total_return_pct') or 0.)>0,
        'drawdown_within_5pct':float(shadow.get('max_drawdown_pct',-1.))>=-.05,
        'shadow_profit_concentration_within_80pct':0<=float(shadow.get('top_five_profit_share',1.))<=.80,
        'risk_not_halted':shadow.get('risk_halted') is not True,
    }
    passed=all(checks.values())
    decision=('LIVE_APPROVED_CANARY' if passed else
              'REJECTED' if observed_days>=max_days else 'PAPER_APPROVED')
    return {'decision':decision,'live_authorized':passed,'checks':checks,
            'observed_days':observed_days,'minimum_days':min_days,
            'maximum_days':max_days,'minimum_closed_trades':min_closed_trades}
