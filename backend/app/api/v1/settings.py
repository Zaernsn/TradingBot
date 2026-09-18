from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import Portfolio, RiskConfig
from app.schemas.portfolio import RiskConfigOut, RiskConfigUpdate
from app.schemas.settings import ExchangeCredentialsIn, ExchangeStatusOut
from app.services.portfolio_service import reset_paper_portfolio
from app.services.risk_service import get_risk_config
from app.services.exchange_service import encrypt_value, decrypt_value, mask_key
from app.core.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_user_kraken_credentials(user: User):
    if user.kraken_api_key_encrypted and user.kraken_api_secret_encrypted:
        return (
            decrypt_value(user.kraken_api_key_encrypted),
            decrypt_value(user.kraken_api_secret_encrypted),
        )
    return settings.KRAKEN_API_KEY, settings.KRAKEN_API_SECRET


@router.get("/risk", response_model=RiskConfigOut)
def get_risk(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_risk_config(db, current_user.id)


@router.put("/risk", response_model=RiskConfigOut)
def update_risk(
    payload: RiskConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    config = get_risk_config(db, current_user.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config


@router.post("/reset-paper")
def reset_paper(
    confirm: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirm reset by passing confirm=true")
    reset_paper_portfolio(db, current_user.id)
    return {"detail": "Paper portfolio reset to €500. All paper history deleted."}


@router.get("/exchange", response_model=ExchangeStatusOut)
def get_exchange_status(current_user: User = Depends(get_current_user)):
    key, _ = _get_user_kraken_credentials(current_user)
    return ExchangeStatusOut(connected=bool(key), masked_key=mask_key(key) if key else "****")


@router.post("/exchange")
def save_exchange_credentials(
    payload: ExchangeCredentialsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.kraken_api_key_encrypted = encrypt_value(payload.api_key)
    current_user.kraken_api_secret_encrypted = encrypt_value(payload.api_secret)
    db.commit()
    return {"detail": "Credentials saved"}


@router.post("/exchange/test")
async def test_exchange_credentials(current_user: User = Depends(get_current_user)):
    key, secret = _get_user_kraken_credentials(current_user)
    if not key or not secret:
        raise HTTPException(status_code=400, detail="No Kraken credentials configured")
    from app.exchanges.kraken import KrakenExchange
    exchange = KrakenExchange(api_key=key, api_secret=secret)
    try:
        await exchange.get_balances()
        return {"detail": "Connection successful"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kraken connection failed: {e}")
    finally:
        await exchange.client.close()


@router.get("/safety")
def safety_status(current_user: User = Depends(get_current_user)):
    user_key, user_secret = _get_user_kraken_credentials(current_user)
    has_creds = bool(user_key and user_secret)
    return {
        "enable_live_trading_env": settings.ENABLE_LIVE_TRADING,
        "api_credentials_present": has_creds,
        "live_possible": settings.ENABLE_LIVE_TRADING and has_creds,
        "message": "Live trading is disabled by default. It requires explicit env flag, credentials, UI opt-in, and confirmation.",
    }


@router.post("/enable-live")
async def enable_live(
    confirm: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.ENABLE_LIVE_TRADING:
        raise HTTPException(status_code=403, detail="Live trading is disabled in server configuration")

    key, secret = _get_user_kraken_credentials(current_user)
    if not (key and secret):
        raise HTTPException(status_code=400, detail="Exchange API credentials not configured")

    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "You must confirm that you understand the risks. "
                "Live trading can lose money. Withdrawal functionality is never used. "
                "Pass confirm=true to proceed."
            ),
        )

    portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    from app.exchanges.kraken import KrakenExchange
    exchange = KrakenExchange(api_key=key, api_secret=secret)
    try:
        has_withdrawal = await exchange.check_withdrawal_permission()
        if has_withdrawal:
            raise HTTPException(status_code=400, detail="API key has withdrawal permission. Use a key without withdrawal rights.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Unable to verify API key permissions. Live mode blocked.")
    finally:
        await exchange.client.close()

    portfolio.mode = "LIVE"
    db.commit()
    return {"detail": "Live trading enabled. Emergency stop is available."}


@router.post("/disable-live")
def disable_live(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).first()
    if portfolio:
        portfolio.mode = "PAPER"
        db.commit()
    return {"detail": "Switched back to paper trading mode."}
