import os
import pickle
from typing import List, Optional, Dict, Any
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from app.exchanges.base import OHLCV
from app.ml.features import build_features, make_target

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "./models"))
MODEL_DIR.mkdir(exist_ok=True)


class SignalModel:
    def __init__(self, name: str = "ensemble"):
        self.name = name
        self.scaler = StandardScaler()
        self.lr = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.rf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, class_weight="balanced")
        self.feature_cols: List[str] = []
        self.is_fitted = False

    def _feature_cols(self, df: pd.DataFrame) -> List[str]:
        exclude = {"open", "high", "low", "close", "volume"}
        return [c for c in df.columns if c not in exclude]

    def fit(self, candles: List[OHLCV], horizon: int = 12):
        df = build_features(candles)
        if len(df) < 50:
            self.is_fitted = False
            return self
        y = make_target(df, horizon).loc[df.index]
        self.feature_cols = self._feature_cols(df)
        X = df[self.feature_cols]
        X_scaled = self.scaler.fit_transform(X)
        self.lr.fit(X_scaled, y)
        self.rf.fit(X, y)
        self.is_fitted = True
        self._save()
        return self

    def predict(self, candles: List[OHLCV]) -> Dict[str, Any]:
        df = build_features(candles)
        if len(df) == 0 or not self.is_fitted:
            return {"action": "HOLD", "probability": 0.5, "confidence": 0.0, "explanation": "Not enough data or model not trained"}

        X = df[self.feature_cols].iloc[[-1]]
        X_scaled = self.scaler.transform(X)

        prob_lr = self.lr.predict_proba(X_scaled)[0][1]
        prob_rf = self.rf.predict_proba(X)[0][1]
        prob = float((prob_lr + prob_rf) / 2)

        if prob > 0.6:
            action = "BUY"
        elif prob < 0.4:
            action = "SELL"
        else:
            action = "HOLD"

        confidence = abs(prob - 0.5) * 2  # scale to 0-1
        explanation = self._explain(X.iloc[0], prob_lr, prob_rf)
        return {
            "action": action,
            "probability": round(prob, 4),
            "confidence": round(confidence, 4),
            "features": {col: round(float(X[col].iloc[0]), 4) for col in self.feature_cols},
            "explanation": explanation,
        }

    def _explain(self, row: pd.Series, prob_lr: float, prob_rf: float) -> str:
        parts = [
            f"Logistic regression probability of positive return: {prob_lr:.2%}",
            f"Random forest probability of positive return: {prob_rf:.2%}",
        ]
        if "rsi" in row:
            parts.append(f"RSI is {row['rsi']:.1f}")
        if "macd" in row:
            parts.append(f"MACD is {row['macd']:.4f}")
        if "volatility" in row:
            parts.append(f"Recent volatility is {row['volatility']:.2%}")
        return "; ".join(parts)

    def _save(self):
        path = MODEL_DIR / f"{self.name}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"scaler": self.scaler, "lr": self.lr, "rf": self.rf, "feature_cols": self.feature_cols}, f)

    def load(self):
        path = MODEL_DIR / f"{self.name}.pkl"
        if path.exists():
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.scaler = data["scaler"]
            self.lr = data["lr"]
            self.rf = data["rf"]
            self.feature_cols = data["feature_cols"]
            self.is_fitted = True
