"""Constrained strategy generation and promotion; never executes an order."""
from dataclasses import asdict, dataclass
from app.ml.strategies import (
    AdaptiveParameters, AdaptiveMomentumModel, VolatilityTrendModel,
    BreakoutLiquidityModel, DefensiveMeanReversionModel,
)


@dataclass(frozen=True)
class StrategyDefinition:
    family: str
    lookback: int
    threshold: float = 0.
    volume_ratio: float = 0.
    z_entry: float = 0.

    def __post_init__(self):
        if self.family not in {'volatility_trend','breakout_liquidity','defensive_mean_reversion'}:
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
    return adaptive+families


def derived_candidates(evaluated):
    """Create a tiny second generation inside the declared safe grammar.

    The bot may tune parameters, but it cannot author executable code, expand
    risk limits, or create an unbounded multiple-testing loop.
    """
    base=generated_candidates(); base_ids={candidate_id(value) for value in base}
    rows=[row for row in evaluated if row.candidate_id in base_ids]
    def family(row): return row.parameters.get('family','adaptive_momentum')
    def score(row):
        holdout=(row.metrics or {}).get('holdout',{})
        return (float(holdout.get('expectancy') or 0.),float(holdout.get('total_return_pct') or 0.))
    children=[]
    for name in ('adaptive_momentum','volatility_trend','breakout_liquidity','defensive_mean_reversion'):
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
        else:
            children.extend([StrategyDefinition(name,max(24,parent.lookback-12),z_entry=max(-4.,parent.z_entry-.25)),
                             StrategyDefinition(name,min(168,parent.lookback+12),z_entry=min(-1.,parent.z_entry+.25))])
    unique=[]; seen=base_ids
    for child in children:
        identity=candidate_id(child)
        if identity not in seen: unique.append(child); seen.add(identity)
    return unique[:8]


def candidate_parameters(parameters):
    # Keep the original adaptive representation stable. Existing databases and
    # exported metadata used this shape before multiple families were added.
    return asdict(parameters) if isinstance(parameters,AdaptiveParameters) else asdict(parameters)


def candidate_id(parameters):
    values=candidate_parameters(parameters)
    prefix='adaptive' if isinstance(parameters,AdaptiveParameters) else 'strategy'
    return prefix+'-'+'-'.join(
        f'{key}={values[key] if isinstance(values[key],str) else f"{values[key]:g}"}'
        for key in sorted(values))


def candidate_factory(parameters):
    if isinstance(parameters,AdaptiveParameters):
        return lambda _: AdaptiveMomentumModel(parameters=parameters)
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
            'holdout_beats_momentum':holdout['total_return_pct']>benchmark['total_return_pct'],
            'stress_positive':stress['expectancy']>0 and stress['total_return_pct']>0,
            'drawdown_within_8pct':holdout['max_drawdown_pct']>=-.08,
            'holdout_closed_trades_at_least_30':closed>=30,
            'profit_concentration_within_80pct':concentration<=.80,
        },
    }


def shadow_promotion_decision(shadow, stress, benchmark, observed_days,
                              min_days=7, max_days=30, min_closed_trades=30):
    """Promote only frozen, genuinely forward shadow evidence.

    The candidate remains active while evidence is immature.  After the maximum
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
        'drawdown_within_5pct':float(shadow.get('max_drawdown_pct') or -1.)>=-.05,
        'risk_not_halted':shadow.get('risk_halted') is not True,
    }
    passed=all(checks.values())
    decision=('LIVE_APPROVED_CANARY' if passed else
              'REJECTED' if observed_days>=max_days else 'PAPER_APPROVED')
    return {'decision':decision,'live_authorized':passed,'checks':checks,
            'observed_days':observed_days,'minimum_days':min_days,
            'maximum_days':max_days,'minimum_closed_trades':min_closed_trades}
