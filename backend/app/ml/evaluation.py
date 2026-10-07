"""Deterministic research statistics; never authorizes live trading."""
from dataclasses import dataclass, asdict
import hashlib
import json
import math

import numpy as np


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def mean_interval(values, block_size=24, samples=1000, seed=17):
    """Circular moving-block bootstrap; observation unit must be documented."""
    values = np.asarray(values, dtype=float)
    if values.size < 2 or not np.isfinite(values).all():
        return None
    block_size = max(1, min(int(block_size), len(values)))
    rng = np.random.default_rng(seed)
    means = []
    for offset in range(0, samples, 25):
        starts = rng.integers(0, len(values), size=(min(25,samples-offset), math.ceil(len(values) / block_size)))
        indices = (starts[:, :, None] + np.arange(block_size)) % len(values)
        means.extend(values[indices.reshape(len(starts), -1)[:, :len(values)]].mean(axis=1))
    low, high = np.quantile(means, [.025, .975])
    return {'low': float(low), 'high': float(high), 'block_size': block_size,
            'samples': samples, 'seed': seed}


def curve_metrics(curve):
    values = np.asarray(curve, dtype=float)
    peaks = np.maximum.accumulate(values)
    drawdowns = values / peaks - 1
    longest = current = 0
    for value in drawdowns:
        current = current + 1 if value < -1e-12 else 0
        longest = max(longest, current)
    returns = np.diff(values) / values[:-1]
    return {'max_drawdown_pct': float(drawdowns.min()), 'time_underwater_bars': longest,
            'hourly_mean_return_interval': mean_interval(returns),
            'sharpe_ratio': float(returns.mean() / returns.std(ddof=1) * math.sqrt(365 * 24))
            if len(returns) > 1 and returns.std(ddof=1) > 1e-12 else 0.}


@dataclass(frozen=True)
class PromotionPolicy:
    # Research defaults, not a personalized capital recommendation.
    min_forward_days: int = 0
    min_closed_trades: int = 100
    max_drawdown_pct: float = .10
    max_cost_overrun_pct: float = .25

    def __post_init__(self):
        if self.min_forward_days < 0 or self.min_closed_trades < 2:
            raise ValueError('Observation days must be nonnegative and at least two trades are required')
        if not 0 < self.max_drawdown_pct <= 1 or not 0 <= self.max_cost_overrun_pct <= 1:
            raise ValueError('Invalid promotion tolerances')


def promotion_report(historical, forward, policy=None):
    """Fail closed on absent evidence. Even PASS requires human live acceptance."""
    policy = policy or PromotionPolicy()
    reasons = []
    def positive_interval(report):
        interval = report.get('hourly_mean_return_interval') or {}
        lower = interval.get('low')
        return isinstance(lower, (float, int)) and math.isfinite(lower) and lower > 0

    for name, report in [('historical', historical), ('forward', forward)]:
        if not report:
            reasons.append(f'{name}: missing evidence')
            continue
        expectancy = report.get('expectancy', 0)
        if not isinstance(expectancy, (float,int)) or not math.isfinite(expectancy) or expectancy <= 0 or not positive_interval(report):
            reasons.append(f'{name}: positive expectancy and return uncertainty requirements not met')
        drawdown = report.get('max_drawdown_pct')
        if drawdown is None or not math.isfinite(drawdown) or abs(drawdown) > policy.max_drawdown_pct:
            reasons.append(f'{name}: drawdown unavailable or exceeds tolerance')
        if report.get('closed_trades', 0) < policy.min_closed_trades:
            reasons.append(f'{name}: insufficient closed trades')
        if report.get('data_limitations'):
            reasons.append(f'{name}: unresolved data limitations')
    if historical.get('stage') != 'holdout':
        reasons.append('historical: untouched holdout required')
    if historical.get('stress_passed') is not True:
        reasons.append('historical: cost stress evidence missing or failed')
    if historical.get('benchmark_advantage') is not True:
        reasons.append('historical: benchmark advantage not established')
    if forward.get('observed_days', 0) < policy.min_forward_days:
        reasons.append('forward: observation period too short')
    if forward.get('version_consistent') is not True:
        reasons.append('forward: frozen version/configuration not verified')
    if not historical.get('candidate_id') or historical.get('candidate_id') != forward.get('candidate_id'):
        reasons.append('historical and forward candidate identities differ or are missing')
    overrun = forward.get('cost_overrun_pct')
    if overrun is None or not math.isfinite(overrun) or overrun > policy.max_cost_overrun_pct:
        reasons.append('forward: execution cost evidence missing or exceeds tolerance')
    if forward.get('unresolved_orders', 1) != 0:
        reasons.append('forward: unresolved execution outcomes')
    return {'decision': 'NO_GO' if reasons else 'READY_FOR_SUPERVISED_ACCEPTANCE',
            'live_authorized': False, 'reasons': reasons, 'policy': asdict(policy)}
