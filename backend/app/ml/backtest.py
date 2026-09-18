from datetime import datetime, timezone
from typing import List
import pandas as pd
import numpy as np
from app.exchanges.base import OHLCV, OrderSide
from app.ml.features import build_features, make_target
from app.ml.models import SignalModel


class BacktestEngine:
    def __init__(self, candles: List[OHLCV], initial_cash: float = 500.0, fee_pct: float = 0.0026):
        self.df = build_features(candles)
        self.initial_cash = initial_cash
        self.fee_pct = fee_pct
        self.cash = initial_cash
        self.quantity = 0.0
        self.trades: List[dict] = []
        self.equity_curve: List[float] = []

    def run(self, horizon: int = 12) -> dict:
        if len(self.df) < 60:
            return self._empty_result()

        self.df["timestamp"] = [c.timestamp for c in self.candles[len(self.candles) - len(self.df):]]
        y = make_target(self.df, horizon).loc[self.df.index]
        model = SignalModel(name="backtest_ensemble")
        model.fit(candles=[], horizon=horizon)  # we will train incrementally below

        feature_cols = model.feature_cols
        X = self.df[feature_cols]
        y_series = y

        for i in range(30, len(self.df) - horizon):
            train_X = X.iloc[:i]
            train_y = y_series.iloc[:i]
            if train_y.nunique() < 2:
                continue
            model.scaler.fit(train_X)
            X_scaled = model.scaler.transform(train_X)
            model.lr.fit(X_scaled, train_y)
            model.rf.fit(train_X, train_y)
            model.is_fitted = True

            current_X = X.iloc[[i]]
            prob_lr = model.lr.predict_proba(model.scaler.transform(current_X))[0][1]
            prob_rf = model.rf.predict_proba(current_X)[0][1]
            prob = (prob_lr + prob_rf) / 2
            price = self.df["close"].iloc[i]
            ts = self.df["timestamp"].iloc[i]

            if prob > 0.6 and self.quantity == 0:
                qty = self._position_size(price)
                if qty > 0 and self.cash >= qty * price * (1 + self.fee_pct):
                    cost = qty * price * (1 + self.fee_pct)
                    self.cash -= cost
                    self.quantity = qty
                    self.trades.append({"timestamp": ts, "side": "BUY", "quantity": qty, "price": price, "pnl": None})
            elif prob < 0.4 and self.quantity > 0:
                qty = self.quantity
                proceeds = qty * price * (1 - self.fee_pct)
                pnl = proceeds - (qty * self.trades[-1]["price"])
                self.cash += proceeds
                self.quantity = 0
                self.trades.append({"timestamp": ts, "side": "SELL", "quantity": qty, "price": price, "pnl": pnl})

            equity = self.cash + self.quantity * price
            self.equity_curve.append(equity)

        final_price = self.df["close"].iloc[-1]
        final_equity = self.cash + self.quantity * final_price
        return self._build_result(final_equity)

    def _position_size(self, price: float) -> float:
        allocation = self.initial_cash * 0.20
        return allocation / price

    def _empty_result(self) -> dict:
        return {
            "symbol": "UNKNOWN",
            "initial_cash": self.initial_cash,
            "final_equity": self.initial_cash,
            "total_return_pct": 0.0,
            "num_trades": 0,
            "win_rate": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "trades": [],
        }

    def _build_result(self, final_equity: float) -> dict:
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        total_return = (final_equity - self.initial_cash) / self.initial_cash
        wins = [t for t in self.trades if t.get("pnl", 0) and t["pnl"] > 0]
        sells = [t for t in self.trades if t["side"] == "SELL"]
        win_rate = len(wins) / len(sells) if sells else 0.0
        running_max = pd.Series(self.equity_curve).cummax()
        drawdown = (pd.Series(self.equity_curve) - running_max) / running_max
        max_dd = drawdown.min() if len(drawdown) else 0.0
        sharpe = 0.0
        if len(returns) > 1 and returns.std() != 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(len(returns))
        return {
            "symbol": "UNKNOWN",
            "initial_cash": self.initial_cash,
            "final_equity": final_equity,
            "total_return_pct": total_return,
            "num_trades": len(self.trades),
            "win_rate": win_rate,
            "max_drawdown_pct": max_dd,
            "sharpe_ratio": sharpe,
            "trades": self.trades,
        }
