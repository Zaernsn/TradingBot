from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import Portfolio, RiskConfig
from app.schemas.portfolio import RiskConfigOut, RiskConfigUpdate
from app.services.portfolio_service import reset_paper_portfolio
from app.services.risk_service import get_risk_config
from app.core.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


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


@router.get("/safety")
def safety_status(current_user: User = Depends(get_current_user)):
    has_creds = bool(settings.KRAKEN_API_KEY and settings.KRAKEN_API_SECRET)
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
    if not (settings.KRAKEN_API_KEY and settings.KRAKEN_API_SECRET):
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

    # Additional safety: check key does not have withdrawal permission
    from app.exchanges.kraken import KrakenExchange
    exchange = KrakenExchange()
    try:
        has_withdrawal = await exchange.check_withdrawal_permission()
        if has_withdrawal:
            raise HTTPException(status_code=400, detail="API key has withdrawal permission. Use a key without withdrawal rights.")
    except HTTPException:
        raise
    except Exception:
        # If we cannot verify, block live mode
        raise HTTPException(status_code=400, detail="Unable to verify API key permissions. Live mode blocked.")

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
