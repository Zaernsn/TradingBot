from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.exchanges.paper import PaperExchange
from app.schemas.portfolio import MarketPrice, BacktestRequest, BacktestResult
from app.ml.backtest import BacktestEngine

router = APIRouter(prefix="/market", tags=["market"])

from app.exchanges.universe import CURATED_PAIRS, SUPPORTED_PAIRS


@router.get("/pairs")
def get_pairs():
    return CURATED_PAIRS


@router.get("/price/{symbol:path}", response_model=MarketPrice)
async def get_price(symbol: str):
    exchange = PaperExchange()
    try:
        ticker = await exchange.get_ticker(symbol)
        return MarketPrice(
            symbol=symbol,
            price=ticker.last,
            bid=ticker.bid,
            ask=ticker.ask,
            timestamp=ticker.timestamp,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await exchange.close()


@router.get("/ohlcv/{symbol:path}")
async def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 100):
    exchange = PaperExchange()
    try:
        candles = await exchange.get_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await exchange.close()


@router.post("/backtest", response_model=BacktestResult)
async def run_backtest(request: BacktestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    import asyncio
    from app.services.market_data import load_history
    from app.ml.backtest import PortfolioBacktestEngine
    symbols = CURATED_PAIRS if request.symbol == "PORTFOLIO" else [request.symbol]
    if any(symbol not in SUPPORTED_PAIRS for symbol in symbols):
        raise HTTPException(status_code=422, detail="Choose a supported EUR pair or PORTFOLIO (core portfolio)")
    exchange = PaperExchange()
    try:
        hourly = {s: await load_history(db, exchange, s) for s in symbols}
        daily = {s: await load_history(db, exchange, s, '1d', limit=720) for s in symbols}
        from app.services.risk_service import get_risk_config, risk_manager_from_config
        risk = risk_manager_from_config(get_risk_config(db, current_user.id)) if request.use_saved_risk else None
        engine = PortfolioBacktestEngine(hourly, initial_cash=request.initial_cash, fee_pct=request.fee_pct,
            slippage_pct=request.slippage_pct,daily_by_symbol=daily,select_assets=request.symbol=="PORTFOLIO",
            start_date=request.start_date,end_date=request.end_date,
            risk=risk,
            max_open_positions=request.max_open_positions if request.symbol=="PORTFOLIO" else 1)
        result = await asyncio.to_thread(engine.run, horizon=risk.prediction_horizon if risk else request.prediction_horizon)
        result["symbol"] = request.symbol
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Market data or backtest execution failed")
    finally:
        await exchange.close()
