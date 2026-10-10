"""Offline-only exit challengers. Live configuration does not expose these policies."""
from dataclasses import dataclass
from datetime import timedelta
import math


@dataclass(frozen=True)
class ExitExperiment:
    variant: str = 'fixed'
    atr_multiple: float = 2.
    trailing_activation_pct: float = .04
    trailing_distance_pct: float = .025
    max_hours: int = 24
    progress_hours: int = 12
    required_progress_pct: float = .01

    def __post_init__(self):
        if self.variant not in {'fixed','atr','trailing','time','no-progress'}:
            raise ValueError('Unknown exit experiment')
        values=(self.atr_multiple,self.trailing_activation_pct,self.trailing_distance_pct,self.required_progress_pct)
        if not all(math.isfinite(v) and v>0 for v in values):
            raise ValueError('Exit experiment values must be finite and positive')
        if not 0<self.trailing_distance_pct<self.trailing_activation_pct<1 or not 0<self.required_progress_pct<1:
            raise ValueError('Invalid trailing/progress thresholds')
        if not 1<=self.max_hours<=8760 or not 1<=self.progress_hours<=8760:
            raise ValueError('Invalid exit experiment duration')

    def initial_stop_pct(self, history, price, baseline):
        if self.variant!='atr':
            return baseline
        if len(history)<15:
            raise ValueError('ATR exit needs 15 completed candles')
        rows=history[-15:]
        atr=sum(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(rows,rows[1:]))/14
        # Bounds are part of the preregistered hypothesis, not tuned from holdout.
        return min(.10,max(.01,self.atr_multiple*atr/price))

    def stop_price(self, position, baseline):
        stop=position.avg_entry_price*(1-getattr(position,'experiment_stop_pct',baseline))
        high=getattr(position,'high_water_price',position.avg_entry_price)
        if self.variant=='trailing' and high>=position.avg_entry_price*(1+self.trailing_activation_pct):
            stop=max(stop,high*(1-self.trailing_distance_pct))
        return stop

    def time_exit(self, position, price, now):
        age=now-position.opened_at
        if self.variant=='time':
            return age>=timedelta(hours=self.max_hours)
        if self.variant=='no-progress':
            return age>=timedelta(hours=self.progress_hours) and price<position.avg_entry_price*(1+self.required_progress_pct)
        return False
