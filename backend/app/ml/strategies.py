"""Small research challengers. No challenger is automatically deployed."""
import math
import numpy as np
from dataclasses import dataclass
from app.ml.models import SignalModel


@dataclass(frozen=True)
class MarketRegime:
    name: str
    breadth: float
    median_three_hour_return: float
    coverage: float
    observed_markets: int
    required_markets: int


@dataclass(frozen=True)
class AdaptiveParameters:
    trend_breadth: float = .60
    trend_return: float = .0025
    acceleration_breadth: float = .70
    acceleration_return: float = .0075
    momentum_threshold: float = .015

    def __post_init__(self):
        if not (.5<=self.trend_breadth<=self.acceleration_breadth<=.9):
            raise ValueError('Invalid adaptive breadth thresholds')
        if not (0<=self.trend_return<=self.acceleration_return<=.05):
            raise ValueError('Invalid adaptive return thresholds')
        if not (.005<=self.momentum_threshold<=.10):
            raise ValueError('Invalid adaptive momentum threshold')


def classify_market_regime(histories, symbols=None, cost=0., parameters=None):
    """Classify only from completed historical candles shared by all strategies."""
    parameters=parameters or AdaptiveParameters()
    symbols=list(symbols or histories)
    expected=max(1,len(symbols))
    valid=[]
    for symbol in symbols:
        rows=histories.get(symbol) or []
        if len(rows)<25:
            continue
        close=np.asarray([row.close for row in rows[-25:]],dtype=float)
        if len(close)==25 and np.isfinite(close).all() and (close>0).all():
            valid.append(close)
    observed=len(valid)
    coverage=observed/expected
    required=min(10,max(3,math.ceil(expected*.8)))
    if observed<required or coverage<.8:
        return MarketRegime('insufficient',0.,0.,coverage,observed,required)
    breadth=float(np.mean([close[-1]>close[0] for close in valid]))
    median_three=float(np.median([close[-1]/close[-4]-1 for close in valid]))
    if breadth>=parameters.acceleration_breadth and median_three>max(parameters.acceleration_return,cost):
        name='acceleration'
    elif breadth>=parameters.trend_breadth and median_three>max(parameters.trend_return,cost/3):
        name='trend'
    else:
        name='defensive'
    return MarketRegime(name,breadth,median_three,coverage,observed,required)


class AdaptiveMomentumModel:
    """Regime controller over fixed, auditable momentum strategies."""

    def __init__(self, regime=None, parameters=None):
        self.parameters=parameters or AdaptiveParameters()
        self.regime=regime or MarketRegime('insufficient',0.,0.,0.,0,3)
        self.slow=MomentumModel(threshold=self.parameters.momentum_threshold)
        self.fast=FastMomentumModel()
        self.name='adaptive-momentum-v1'
        self.is_fitted=False

    def set_regime(self, regime):
        self.regime=regime

    def fit(self, candles, **kwargs):
        self.slow.fit(candles,**kwargs)
        self.fast.fit(candles,**kwargs)
        self.is_fitted=True
        return self

    def predict(self, candles):
        slow=self.slow.predict(candles)
        if self.regime.name in {'insufficient','defensive'}:
            result={'action':'SELL' if slow.get('action')=='SELL' else 'HOLD',
                    'opportunity_score':min(0.,float(slow.get('opportunity_score',0.) or 0.)),
                    'explanation':'Adaptive controller is defensive; new entries remain in cash.',
                    'active_strategy':'cash'}
        elif self.regime.name=='acceleration':
            fast=self.fast.predict(candles)
            if fast.get('action')=='BUY':
                result={**fast,'active_strategy':'fast_momentum'}
            elif slow.get('action')=='SELL':
                result={**slow,'active_strategy':'momentum'}
            else:
                result={**fast,'action':'HOLD','active_strategy':'fast_momentum'}
        else:
            result={**slow,'active_strategy':'momentum'}
        result['regime']={
            'name':self.regime.name,'breadth':self.regime.breadth,
            'median_three_hour_return':self.regime.median_three_hour_return,
            'coverage':self.regime.coverage,'observed_markets':self.regime.observed_markets,
            'required_markets':self.regime.required_markets,
        }
        return result


class WindowedSignalModel(SignalModel):
    """Normalized-feature research candidate with a declared rolling history."""
    def __init__(self, hours):
        super().__init__(persist=False, feature_schema='normalized-v1')
        self.window_hours=hours

    def fit(self, candles, **kwargs):
        if len(candles)<self.window_hours:
            self.is_fitted=False
            self.failure_reason=f'Requires {self.window_hours} hourly candles for this research window'
            return self
        return super().fit(candles[-self.window_hours:],**kwargs)


class MomentumModel:
    def __init__(self, lookback=24, threshold=.01):
        if lookback < 2 or threshold < 0:
            raise ValueError('Invalid momentum configuration')
        self.lookback, self.threshold = lookback, threshold
        self.is_fitted = False

    def fit(self, candles, **kwargs):
        self.is_fitted = True
        self.cost = (1 + kwargs.get('fee_pct', 0)) * (1 + kwargs.get('slippage_pct', 0)) / (
            (1 - kwargs.get('fee_pct', 0)) * (1 - kwargs.get('slippage_pct', 0))) - 1
        return self

    def predict(self, candles):
        if len(candles) <= self.lookback:
            return {'action': 'HOLD'}
        closes = np.asarray([c.close for c in candles[-self.lookback-1:]])
        momentum = closes[-1] / closes[0] - 1
        volatility = float(np.std(np.diff(closes) / closes[:-1]))
        score = (momentum - self.cost) / max(volatility * math.sqrt(self.lookback), 1e-8)
        return {'action': 'BUY' if momentum > max(self.threshold, self.cost) else 'SELL' if momentum < 0 else 'HOLD',
                'opportunity_score': score, 'momentum': float(momentum)}


class FastMomentumModel(MomentumModel):
    """Hourly momentum challenger; deterministic signals, no claimed probability.

    Uses only completed candles supplied by the caller. Research first: current
    spread, exchange minimums and portfolio limits remain execution concerns.
    """
    def predict(self, candles):
        if len(candles) < 25 or not self.is_fitted:
            return {'action': 'HOLD', 'explanation': 'Waiting for 25 completed hourly candles.'}
        recent = candles[-25:]
        close = np.asarray([c.close for c in recent], dtype=float)
        volume = np.asarray([c.volume for c in recent], dtype=float)
        if not np.isfinite(close).all() or not np.isfinite(volume).all() or (close <= 0).any() or (volume < 0).any():
            return {'action': 'HOLD', 'explanation': 'Invalid momentum inputs.'}
        hourly = close[-1] / close[-2] - 1
        momentum = close[-1] / close[-4] - 1
        mean_volume = float(volume[:-1].mean())
        volume_ratio = float(volume[-1] / mean_volume) if mean_volume > 0 else 0.
        trend = close[-1] > close[-13:-1].mean()
        breakout = close[-1] > close[-7:-1].max()
        entry = (trend and breakout and 0 < hourly <= .08 and
                 momentum > max(.005, self.cost) and volume_ratio >= 1.2)
        exit_signal = close[-1] < close[-4:-1].mean() and momentum < 0
        volatility = float(np.std(np.diff(close) / close[:-1]))
        return {'action': 'BUY' if entry else 'SELL' if exit_signal else 'HOLD',
                'opportunity_score': float((momentum - self.cost) / max(volatility * math.sqrt(3), .001)),
                'momentum': float(momentum), 'hourly_return': float(hourly),
                'volume_ratio': volume_ratio,
                'explanation': 'Fast momentum: 3-hour strength, 6-hour breakout and increased volume.' if entry else
                               'Fast momentum exit: short-term trend reversed.' if exit_signal else
                               'Waiting for momentum, breakout and volume confirmation.'}


class RegimeStrategy:
    """Base for bounded strategy families sharing the market regime controller."""
    name='regime-strategy'
    def __init__(self, regime=None):
        self.regime=regime or MarketRegime('insufficient',0.,0.,0.,0,3)
        self.is_fitted=False
    def set_regime(self,regime): self.regime=regime
    def fit(self,candles,**kwargs):
        self.cost=(1+kwargs.get('fee_pct',0))*(1+kwargs.get('slippage_pct',0))/(
            (1-kwargs.get('fee_pct',0))*(1-kwargs.get('slippage_pct',0)))-1
        self.is_fitted=True; return self
    def result(self,action,score,explanation,**values):
        return {'action':action,'opportunity_score':float(score),'explanation':explanation,
                'active_strategy':self.name,'regime':{'name':self.regime.name,
                'breadth':self.regime.breadth,'median_three_hour_return':self.regime.median_three_hour_return,
                'coverage':self.regime.coverage,'observed_markets':self.regime.observed_markets,
                'required_markets':self.regime.required_markets},**values}


class VolatilityTrendModel(RegimeStrategy):
    name='volatility_trend'
    def __init__(self,regime=None,lookback=72,threshold=.02):
        super().__init__(regime); self.lookback=lookback; self.threshold=threshold
    def predict(self,candles):
        if not self.is_fitted or len(candles)<=self.lookback:
            return self.result('HOLD',0,'Waiting for volatility-trend history.')
        close=np.asarray([c.close for c in candles[-self.lookback-1:]],dtype=float)
        returns=np.diff(close)/close[:-1]
        momentum=close[-1]/close[0]-1
        recent=close[-1]/close[-25]-1
        vol=float(returns.std())*math.sqrt(self.lookback)
        score=(momentum-self.cost)/max(vol,.001)
        buy=(self.regime.name=='trend' and momentum>max(self.threshold,self.cost) and recent>0)
        action='BUY' if buy else 'SELL' if recent<0 else 'HOLD'
        return self.result(action,score,'Volatility-normalized multi-day trend.',momentum=float(momentum),volatility=vol)


class BreakoutLiquidityModel(RegimeStrategy):
    name='breakout_liquidity'
    def __init__(self,regime=None,lookback=24,volume_ratio=1.5):
        super().__init__(regime); self.lookback=lookback; self.required_volume_ratio=volume_ratio
    def predict(self,candles):
        if not self.is_fitted or len(candles)<=self.lookback:
            return self.result('HOLD',0,'Waiting for breakout history.')
        recent=candles[-self.lookback-1:]
        close=np.asarray([c.close for c in recent],dtype=float)
        volume=np.asarray([c.volume for c in recent],dtype=float)
        ratio=float(volume[-1]/max(volume[:-1].mean(),1e-12))
        breakout=close[-1]>close[:-1].max()
        move=close[-1]/close[-7]-1
        buy=(self.regime.name in {'trend','acceleration'} and breakout and
             move>max(.005,self.cost) and ratio>=self.required_volume_ratio)
        action='BUY' if buy else 'SELL' if close[-1]<close[-7:].mean() else 'HOLD'
        return self.result(action,(move-self.cost)*ratio,'Breakout confirmed by volume acceleration.',
                           momentum=float(move),volume_ratio=ratio)


class DefensiveMeanReversionModel(RegimeStrategy):
    name='defensive_mean_reversion'
    def __init__(self,regime=None,lookback=48,z_entry=-2.):
        super().__init__(regime); self.lookback=lookback; self.z_entry=z_entry
    def predict(self,candles):
        if not self.is_fitted or len(candles)<=self.lookback:
            return self.result('HOLD',0,'Waiting for mean-reversion history.')
        close=np.asarray([c.close for c in candles[-self.lookback:]],dtype=float)
        mean=float(close.mean()); std=float(close.std())
        z=(float(close[-1])-mean)/max(std,1e-12)
        long_floor=close[-1]>=close[0]*.95
        buy=(self.regime.name=='defensive' and long_floor and z<=self.z_entry and abs(z)*std/mean>self.cost)
        action='BUY' if buy else 'SELL' if z>=0 else 'HOLD'
        return self.result(action,-z,'Defensive-regime mean reversion with long-term floor.',z_score=z)


class PayoffModel:
    """Conditional historical payoff challenger, fitted only on matured outcomes.

    Labels are fixed-horizon returns; this is not an estimate of stop-policy payoff.
    Require positive lower confidence margin and trend before an entry.
    """
    def __init__(self):
        self.is_fitted = False

    def fit(self, candles, horizon=12, fee_pct=0., slippage_pct=0.):
        closes = np.asarray([c.close for c in candles])
        self.is_fitted = True
        self.groups = {}
        factor = (1-slippage_pct)*(1-fee_pct)/((1+slippage_pct)*(1+fee_pct))
        for rising in (False, True):
            outcomes = [closes[i+horizon]/closes[i]*factor-1
                        for i in range(24, len(closes)-horizon)
                        if bool(closes[i] > closes[i-24]) == rising]
            # Non-overlapping subsample reduces, but does not remove, dependence.
            self.groups[rising] = np.asarray(outcomes[::horizon], dtype=float)
        return self

    def predict(self, candles):
        if len(candles) < 25:
            return {'action': 'HOLD'}
        rising = candles[-1].close > candles[-25].close
        values = self.groups.get(rising, np.array([]))
        if len(values) < 30:
            return {'action': 'HOLD'}
        expected = float(values.mean())
        downside = max(float(-np.quantile(values, .1)), 1e-8)
        lower = expected - 2 * float(values.std(ddof=1)) / math.sqrt(len(values))
        return {'action': 'BUY' if rising and lower > 0 else 'SELL' if not rising else 'HOLD',
                'expected_net_return': expected, 'downside_return': downside,
                'opportunity_score': lower/downside}


def rank_trade_candidates(symbols, predictions):
    """Prefer valid positive entry setups over stale hold/no-op signals.

    The point is not to chase a symbolic BUY label; it is to rank the candidates that are
    most likely to fill a real order and remain risk-qualified.
    """
    def score(symbol):
        prediction = predictions.get(symbol, {})
        if not isinstance(prediction, dict):
            return -math.inf

        action = str(prediction.get('action', 'HOLD')).upper()
        opportunity = prediction.get('opportunity_score', prediction.get('probability', 0.0))
        numeric = float(opportunity) if isinstance(opportunity, (int, float)) and math.isfinite(opportunity) else 0.0

        action_bonus = {'BUY': 1.10, 'HOLD': -0.35, 'SELL': -1.50}.get(action, -0.75)
        ready_bonus = 0.25 if prediction.get('status') == 'ready' else 0.0
        qualified_bonus = 0.20 if prediction.get('entry_qualified') is True else 0.0
        liquidity_bonus = 0.15 if prediction.get('liquidity_healthy') is True else 0.0
        spread_bonus = 0.10 if prediction.get('spread_ok') is True else 0.0
        risk_bonus = 0.10 if prediction.get('risk_fit') is True else 0.0

        # Preserve a real tradeable BUY above a noisy HOLD even when the raw score is only moderate.
        return numeric + action_bonus + ready_bonus + qualified_bonus + liquidity_bonus + spread_bonus + risk_bonus

    return sorted(symbols, key=lambda s: (-score(s), s))


def rank_entries(symbols, predictions):
    """Stable ranking; unscored models retain deterministic symbol ordering."""
    return rank_trade_candidates(symbols, predictions)
