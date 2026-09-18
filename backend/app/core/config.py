import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    APP_NAME: str = "AI Trading Bot"
    SECRET_KEY: str = "change-me-to-a-long-random-string-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    DATABASE_URL: str = "postgresql://trader:traderpass@localhost:5432/tradingbot"

    ENABLE_LIVE_TRADING: bool = False

    KRAKEN_API_KEY: str = ""
    KRAKEN_API_SECRET: str = ""
    KRAKEN_ENCRYPTION_KEY: str = ""

    DEFAULT_PAPER_BALANCE_EUR: float = 500.0
    DEFAULT_TRADING_PAIR: str = "BTC/EUR"
    DEFAULT_MAX_POSITION_PCT: float = 0.20
    DEFAULT_STOP_LOSS_PCT: float = 0.03
    DEFAULT_TAKE_PROFIT_PCT: float = 0.06
    DEFAULT_FEE_PCT: float = 0.0026

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
