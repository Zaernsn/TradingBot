"""Walk-forward portfolio simulation with next-bar execution and net accounting."""
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import math
import numpy as np
from app.ml.models import SignalModel, apply_buy_threshold
from app.exchanges.base import OHLCV
from app.exchanges.universe import MEMECOIN_PAIRS, is_memecoin
from app.services.asset_selector import AssetSelector
from app.services.market_data import completed_candles, utc
from app.services.risk_service import RiskManager, entry_budget
from types import SimpleNamespace
from dataclasses import asdict, replace
from app.ml.evaluation import curve_metrics, digest
from app.ml.strategies import (
    rank_entries, MomentumModel, FastMomentumModel, AdaptiveMomentumModel,
    classify_market_regime,
)
from app.services.trading_service import exit_reason


class PortfolioBacktestEngine:
    def __init__(self, candles_by_symbol, initial_cash=500., fee_pct=.0026, slippage_pct=.001,
                 daily_by_symbol=None, max_open_positions=5, model_factory=None, select_assets=True,
                 start_date=None, end_date=None, risk=None, intrabar_stops=True,
                 participation_rate=.01, minimum_order_eur=0., strategy_id='signal-v2',
                 liquidate_end=True):
        self.risk = replace(risk) if risk is not None else RiskManager(
            .2,.03,.06,fee_pct,10,None,12,max_open_positions,slippage_pct=slippage_pct,
            memecoins_enabled=any(s in MEMECOIN_PAIRS for s in candles_by_symbol))
        fee_pct, slippage_pct = self.risk.fee_pct, self.risk.slippage_pct
        if not math.isfinite(participation_rate) or not 0 < participation_rate <= 1 or not math.isfinite(minimum_order_eur) or minimum_order_eur < 0:
            raise ValueError('Invalid execution assumptions')
        self.intrabar_stops, self.participation_rate = intrabar_stops, participation_rate
        self.minimum_order_eur, self.strategy_id = minimum_order_eur, strategy_id
        self.liquidate_end=bool(liquidate_end)
        if not math.isfinite(initial_cash) or initial_cash<=0 or not 0<=fee_pct<1 or not 0<=slippage_pct<1:
            raise ValueError('Invalid capital or costs')
        self.data={s:completed_candles(c) for s,c in sorted(candles_by_symbol.items())}
        if any(len(self.data[s]) != len(c) for s,c in candles_by_symbol.items()):
            raise ValueError('Duplicate or incomplete research candles')
        for candles in self.data.values():
            if any(c.timestamp.minute or c.timestamp.second or c.timestamp.microsecond for c in candles):
                raise ValueError('Research candles must align to UTC hours')
            if any(b.timestamp-a.timestamp!=timedelta(hours=1) for a,b in zip(candles,candles[1:])):
                raise ValueError('Backtest requires contiguous hourly data; repair missing candles')
        self.initial_cash=initial_cash
        self.fee_pct=fee_pct
        self.slippage_pct=slippage_pct
        self.daily={s:self._daily(c) for s,c in self.data.items()}
        if daily_by_symbol:
            for symbol,rows in daily_by_symbol.items():
                clean=completed_candles(rows,'1d')
                if len(clean)!=len(rows): raise ValueError('Duplicate or incomplete daily candles')
                if any(c.timestamp.hour or c.timestamp.minute or c.timestamp.second for c in clean):
                    raise ValueError('Daily candles must align to UTC days')
                self.daily[symbol]=clean
        self.max_open_positions=self.risk.max_open_positions
        if model_factory is None and self.risk.entry_strategy in {'momentum','fast_momentum','auto'}:
            model_class = {'momentum':MomentumModel,'fast_momentum':FastMomentumModel,
                           'auto':AdaptiveMomentumModel}[self.risk.entry_strategy]
            model_factory = lambda s: model_class()
            self.strategy_id = self.risk.entry_strategy.replace('_','-')
        self.model_factory=model_factory or (lambda s:SignalModel(name=f'backtest_{s.replace("/","_")}',persist=False))
        self.select_assets=select_assets
        self.start_date=utc(start_date) if start_date else None
        self.end_date=utc(end_date) if end_date else None
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError('Start must precede exclusive end')

    @staticmethod
    def _daily(candles):
        grouped=defaultdict(list)
        for candle in candles: grouped[candle.timestamp.replace(hour=0,minute=0,second=0,microsecond=0)].append(candle)
        return [OHLCV(day,rows[0].open,max(c.high for c in rows),min(c.low for c in rows),rows[-1].close,sum(c.volume for c in rows))
                for day,rows in sorted(grouped.items()) if len(rows)==24]

    def run(self,horizon=None,warmup=None,retrain_every=24):
        if warmup is None:
            warmup=30 if self.risk.entry_strategy in {'momentum','fast_momentum','auto'} else 336
        horizon = self.risk.prediction_horizon if horizon is None else horizon
        if horizon<1 or warmup<1 or retrain_every<1: raise ValueError('Invalid simulation settings')
        self.cash=self.initial_cash; self.positions={}; self.trades=[]
        self.curve=[self.initial_cash]; self.cash_curve=[]; self.peak=self.initial_cash; self.halted=False
        self.fees=0.; self.turnover=0.; self.exposures=[]
        self.limitations=set(); self.curve_timestamps=[]
        self.last_exits={}
        common=set.union(*(set(c.timestamp for c in rows) for rows in self.data.values())) if self.data else set()
        timeline=sorted(t for t in common if (not self.start_date or t>=self.start_date) and (not self.end_date or t<self.end_date))
        index={s:{c.timestamp:i for i,c in enumerate(rows)} for s,rows in self.data.items()}
        timeline=[t for t in timeline if any(index[s].get(t,-1)>=warmup for s in self.data)]
        if any(b-a != timedelta(hours=1) for a,b in zip(timeline,timeline[1:])):
            raise ValueError('Portfolio timeline contains missing hours')
        models={s:self.model_factory(s) for s in self.data}
        watchlist=[]; first_prices={}; last_prices={}; daily_counts=defaultdict(int)
        risk=replace(self.risk,prediction_horizon=horizon)
        first_stamps={}; last_stamps={}
        for step,stamp in enumerate(timeline):
            current={s:rows[index[s][stamp]] for s,rows in self.data.items() if stamp in index[s]}
            past={s:self.data[s][max(0,index[s][stamp]-8760):index[s][stamp]] for s in current}
            eligible={s for s in current if len(past[s])>=warmup}
            for s in eligible:
                first_prices.setdefault(s,current[s].open); first_stamps.setdefault(s,stamp)
                last_prices[s]=current[s].close; last_stamps[s]=stamp
            for s,p in self.positions.items():
                if s in current: p.current_price=current[s].open
                else: self.limitations.add(f'Missing execution/valuation data for held {s}')
            daily={s:(past[s][-60:] if s in MEMECOIN_PAIRS else [c for c in self.daily.get(s,[]) if utc(c.timestamp)+timedelta(days=1)<=stamp]) for s in eligible}
            watchlist=AssetSelector().select_watchlist(daily,self.max_open_positions,risk.memecoins_enabled,limit=risk.watchlist_limit) if self.select_assets else sorted(eligible)
            if risk.entry_strategy=='auto':
                round_trip=(1+self.fee_pct)*(1+self.slippage_pct)/((1-self.fee_pct)*(1-self.slippage_pct))-1
                for model in models.values():
                    if hasattr(model,'set_regime'):
                        model.set_regime(classify_market_regime(
                            past,watchlist,round_trip,getattr(model,'parameters',None)))
            predictions={}
            for symbol in list(dict.fromkeys(list(self.positions)+watchlist)):
                if symbol not in eligible: continue
                model=models[symbol]
                if step%retrain_every==0 or not model.is_fitted:
                    model.fit(past[symbol],horizon=horizon,fee_pct=self.fee_pct,slippage_pct=self.slippage_pct)
                predictions[symbol]=apply_buy_threshold(model.predict(past[symbol]),self.risk.buy_probability_threshold)
            exited=set()
            for symbol,position in list(self.positions.items()):
                if symbol not in current: continue
                bar=current[symbol]
                # Only the execution-time open is known; do not use this bar's future high/low.
                price=bar.open if exit_reason(position,risk,bar.open,now=stamp) or predictions.get(symbol,{}).get('action')=='SELL' else None
                if price is not None:
                    self._sell(symbol,price,stamp); exited.add(symbol)
            # Drawdown is assessed using information known at the execution time.
            equity=self.cash+sum(p.quantity*p.current_price for p in self.positions.values())
            self.peak=max(self.peak,equity)
            if 1-equity/self.peak>=risk.max_drawdown_pct: self.halted=True
            for symbol in rank_entries(watchlist,predictions):
                if self.halted or symbol in exited or symbol in self.positions or predictions.get(symbol,{}).get('action')!='BUY': continue
                active_strategy=predictions.get(symbol,{}).get('active_strategy',risk.entry_strategy)
                if active_strategy == 'fast_momentum':
                    if not is_memecoin(symbol): continue
                    if symbol in self.last_exits and stamp-self.last_exits[symbol]<timedelta(hours=1): continue
                if len(self.positions)>=self.max_open_positions or daily_counts[stamp.date()]>=risk.max_daily_trades: continue
                if is_memecoin(symbol):
                    required=30 if risk.entry_strategy in {'momentum','fast_momentum','auto'} else 30*24
                    if len(past[symbol])<required: continue
                    turnover=sum(c.volume*c.close for c in past[symbol][-24:])
                    if turnover<risk.memecoin_min_daily_volume_eur: continue
                portfolio=SimpleNamespace(equity=self.cash+sum(p.quantity*p.current_price for p in self.positions.values()),cash=self.cash)
                budget=entry_budget(portfolio,risk,symbol,list(self.positions.values()),past)
                if active_strategy == 'fast_momentum':
                    budget=min(budget,turnover*.001)
                price=current[symbol].open*(1+self.slippage_pct)
                quantity=min(budget/(price*(1+self.fee_pct)),past[symbol][-1].volume*self.participation_rate)
                if quantity<=0 or quantity*price<self.minimum_order_eur: continue
                fee=quantity*price*self.fee_pct
                self.cash-=quantity*price+fee
                self.positions[symbol]=SimpleNamespace(symbol=symbol,quantity=quantity,avg_entry_price=price,
                                                       entry_fees=fee,current_price=current[symbol].open,opened_at=stamp)
                self._trade(symbol,'BUY',quantity,price,fee,None,stamp)
                daily_counts[stamp.date()]+=1
            if self.intrabar_stops:
                for symbol,position in list(self.positions.items()):
                    if symbol not in current: continue
                    bar=current[symbol]
                    stop=position.avg_entry_price*(1-risk.stop_loss_pct)
                    target=position.avg_entry_price*(1+risk.take_profit_pct)
                    # Conservative stop-first ordering when both barriers are touched.
                    if bar.low<=stop: self._sell(symbol,min(bar.open,stop),stamp+timedelta(hours=1))
                    elif bar.high>=target: self._sell(symbol,target,stamp+timedelta(hours=1))
            for s,p in self.positions.items():
                if s in current: p.current_price=current[s].close
            equity=self.cash+sum(p.quantity*p.current_price for p in self.positions.values())
            self.peak=max(self.peak,equity)
            if 1-equity/self.peak>=risk.max_drawdown_pct: self.halted=True
            self.curve.append(equity)
            self.cash_curve.append(self.cash)
            self.curve_timestamps.append(stamp+timedelta(hours=1))
            self.exposures.append((equity-self.cash)/equity if equity>0 else 0.)
        if timeline and self.liquidate_end:
            for symbol in list(self.positions):
                if last_stamps.get(symbol)!=timeline[-1]:
                    self.limitations.add(f'Stale terminal mark for {symbol}; no terminal fill')
                    continue
                self._sell(symbol,last_prices[symbol],timeline[-1]+timedelta(hours=1))
            self.curve[-1]=self.cash+sum(p.quantity*p.current_price for p in self.positions.values())
        full=[s for s in first_prices if first_stamps[s]==timeline[0] and last_stamps[s]==timeline[-1]] if timeline else []
        if len(full)!=len(self.data): self.limitations.add('Some assets lack full-period benchmark coverage')
        result=self._result(timeline,{s:first_prices[s] for s in full},{s:last_prices[s] for s in full})
        config={'risk':asdict(risk),'warmup':warmup,'retrain_every':retrain_every,'strategy_id':self.strategy_id,
                'select_assets':self.select_assets,'start':self.start_date,'end':self.end_date,'initial_cash':self.initial_cash,
                'intrabar_stops':self.intrabar_stops,'participation_rate':self.participation_rate,'minimum_order_eur':self.minimum_order_eur,
                'liquidate_end':self.liquidate_end}
        data_hash=digest({'hourly':{s:[vars(c) for c in rows] for s,rows in self.data.items()},
                          'daily':{s:[vars(c) for c in rows] for s,rows in self.daily.items()}})
        result.update(experiment={'configuration':config,'data_sha256':data_hash,'run_id':digest({'config':config,'data':data_hash})},
                      closed_trades=sum(t['side']=='SELL' for t in self.trades),data_limitations=sorted(self.limitations),
                      equity_curve=[{'timestamp':t,'equity':v,'cash':cash}
                                    for t,v,cash in zip(self.curve_timestamps,self.curve[1:],self.cash_curve)],
                      ending_cash=self.cash,
                      open_positions={symbol:{'quantity':position.quantity,'avg_entry_price':position.avg_entry_price,
                          'entry_fees':position.entry_fees,'current_price':position.current_price,
                          'opened_at':position.opened_at}
                          for symbol,position in self.positions.items()},
                      **curve_metrics(self.curve))
        return result

    def _trade(self,symbol,side,quantity,price,fee,pnl,stamp):
        self.fees+=fee; self.turnover+=quantity*price
        self.trades.append(dict(symbol=symbol,timestamp=stamp,side=side,quantity=quantity,price=price,fee=fee,pnl=pnl))

    def _sell(self,symbol,market,stamp):
        self.last_exits[symbol]=stamp
        position=self.positions.pop(symbol)
        price=market*(1-self.slippage_pct)
        gross=position.quantity*price; fee=gross*self.fee_pct
        pnl=(price-position.avg_entry_price)*position.quantity-fee-position.entry_fees
        self.cash+=gross-fee
        self._trade(symbol,'SELL',position.quantity,price,fee,pnl,stamp)

    def _result(self,timeline,first,last):
        values=np.asarray(self.curve)
        returns=np.diff(values)/values[:-1]
        drawdown=values/np.maximum.accumulate(values)-1
        sells=[t for t in self.trades if t['side']=='SELL']
        per_symbol={s:sum(t['pnl'] or 0 for t in sells if t['symbol']==s) for s in self.data}
        per_month=defaultdict(float)
        for trade in sells: per_month[trade['timestamp'].strftime('%Y-%m')]+=trade['pnl']
        profits=sorted([t['pnl'] for t in sells if t['pnl']>0],reverse=True)
        factors={s:(last[s]*(1-self.slippage_pct)*(1-self.fee_pct))/(first[s]*(1+self.slippage_pct)*(1+self.fee_pct))-1 for s in first}
        return dict(symbol=','.join(self.data),initial_cash=self.initial_cash,final_equity=float(values[-1]),
            total_return_pct=float(values[-1]/self.initial_cash-1),num_trades=len(self.trades),
            win_rate=sum(t['pnl']>0 for t in sells)/len(sells) if sells else 0.,
            max_drawdown_pct=float(drawdown.min()),
            sharpe_ratio=float(returns.mean()/returns.std(ddof=1)*math.sqrt(365*24)) if len(returns)>1 and returns.std(ddof=1)>1e-12 else 0.,
            expectancy=float(np.mean([t['pnl'] for t in sells])) if sells else 0.,
            total_fees=self.fees,turnover=self.turnover/self.initial_cash,
            average_exposure=float(np.mean(self.exposures)) if self.exposures else 0.,
            per_month_pnl=dict(per_month),top_five_profit_share=sum(profits[:5])/sum(profits) if profits else 0.,
            per_symbol_pnl=per_symbol,benchmarks={'cash':0.,'equal_weight_buy_hold':float(np.mean(list(factors.values()))) if factors else 0.,
                                               'btc_buy_hold':factors.get('BTC/EUR')},
            evaluation_start=timeline[0] if timeline else None,evaluation_end=timeline[-1]+timedelta(hours=1) if timeline else None,
            evaluated_bars=len(timeline),risk_halted=self.halted,trades=self.trades,
            warnings=([] if timeline else ['Insufficient history for the requested evaluation window'])+
                     ['Historical simulation; thresholds are not evidence of future profitability',
                      'Intrabar stops use conservative stop-first ordering; historical depth/partial fills are unavailable',
                      'Entry capacity uses past volume; exit liquidity is assumed and minimum/precision varies by market',
                      'Historical category membership and spread eligibility require separate evidence'])


class BacktestEngine(PortfolioBacktestEngine):
    def __init__(self,candles,initial_cash=500.,fee_pct=.0026,slippage_pct=.001,**kwargs):
        super().__init__({'UNKNOWN':candles},initial_cash,fee_pct,slippage_pct,max_open_positions=1,select_assets=False,**kwargs)
