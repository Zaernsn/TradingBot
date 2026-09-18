from typing import List
import numpy as np
import pandas as pd
from app.exchanges.base import OHLCV


def build_features(candles: List[OHLCV]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    )
    df["returns"] = df["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    df["sma_10"] = df["close"].rolling(window=10).mean()
    df["sma_30"] = df["close"].rolling(window=30).mean()
    df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["rsi"] = compute_rsi(df["close"], 14)
    df["macd"] = df["ema_12"] - df["close"].ewm(span=26, adjust=False).mean()
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["volatility"] = df["returns"].rolling(window=14).std()
    df["volume_sma"] = df["volume"].rolling(window=10).mean()
    df["bb_upper"], df["bb_lower"] = bollinger_bands(df["close"], 20, 2)
    df = df.dropna()
    return df


def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(prices: pd.Series, window: int = 20, num_std: int = 2):
    sma = prices.rolling(window=window).mean()
    std = prices.rolling(window=window).std()
    return sma + num_std * std, sma - num_std * std


def make_target(df: pd.DataFrame, horizon: int = 12) -> pd.Series:
    """Target: 1 if close is higher `horizon` periods ahead, else 0."""
    future_return = df["close"].shift(-horizon) / df["close"] - 1
    return (future_return > 0).astype(int)
