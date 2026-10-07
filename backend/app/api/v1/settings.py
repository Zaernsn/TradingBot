from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import Portfolio, RiskConfig, BotState
from app.schemas.portfolio import RiskConfigOut, RiskConfigUpdate
from app.schemas.settings import ExchangeCredentialsIn, ExchangeStatusOut
from app.services.portfolio_service import reset_paper_portfolio
from app.services.risk_service import get_risk_config
from app.services.exchange_service import encrypt_value, decrypt_value, mask_key
from app.core.config import settings

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_user_kraken_credentials(user: User):
    # Server keys must never be reported as belonging to an arbitrary app user.
    if user.kraken_api_key_encrypted and user.kraken_api_secret_encrypted:
        try:
            return (decrypt_value(user.kraken_api_key_encrypted), decrypt_value(user.kraken_api_secret_encrypted))
        except Exception:
            return '', ''
    return '', ''


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
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in data.items():
        setattr(config, key, value)
    if any(key in data for key in ('max_open_positions','watchlist_limit','discovery_limit','entry_strategy')) or any(key.startswith('memecoin') for key in data):
        portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id, Portfolio.is_active.is_(True)).first()
        if portfolio:
            portfolio.target_positions = config.max_open_positions
        state = db.query(BotState).filter(BotState.user_id == current_user.id).first()
        if state:
            state.watchlist = []
            state.watchlist_updated_at = None
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
    try:
        reset_paper_portfolio(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": "Paper portfolio reset to €500. All paper history deleted."}


@router.get("/exchange", response_model=ExchangeStatusOut)
def get_exchange_status(current_user: User = Depends(get_current_user)):
    key, secret = _get_user_kraken_credentials(current_user)
    return ExchangeStatusOut(connected=bool(key and secret), masked_key=mask_key(key) if key else "****")


@router.post("/exchange")
def save_exchange_credentials(
    payload: ExchangeCredentialsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trading_books import require_idle
    try:
        require_idle(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if db.query(Portfolio).filter(Portfolio.user_id == current_user.id, Portfolio.book_type == 'LIVE').first():
        raise HTTPException(status_code=409, detail='A live book is bound to this key. Credential rotation requires explicit account reconciliation.')
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
    stored = bool(current_user.kraken_api_key_encrypted and current_user.kraken_api_secret_encrypted)
    return {
        "enable_live_trading_env": settings.ENABLE_LIVE_TRADING,
        "api_credentials_present": has_creds,
        "credential_status": 'saved' if has_creds else 'unreadable' if stored else 'missing',
        "credential_message": ('Your account key is saved. Use Test Connection to verify Kraken access.' if has_creds else
            'Saved credentials cannot be decrypted. Check KRAKEN_ENCRYPTION_KEY or restore the key used when saving them.' if stored else
            'Save your Kraken API key and secret in Kraken Connection for this signed-in account. Server environment keys do not enable personal live trading.'),
        "live_possible": settings.ENABLE_LIVE_TRADING and has_creds,
        "message": "Live mode uses a separate Kraken book. Requires your own key without withdrawal permission, EUR funds, no unmanaged holdings/orders, and explicit confirmation.",
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

    from app.services.trading_books import enable_live_book
    try:
        book = await enable_live_book(db, current_user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        db.rollback()
        import logging
        from app.services.preflight_errors import preflight_error, preflight_reason
        # Raw exception text can contain exchange payloads or SQL parameters.
        logging.getLogger(__name__).error('Live preflight failed: category=%s reason=%s', type(exc).__name__, preflight_reason(exc))
        raise HTTPException(status_code=502, detail=preflight_error(exc) + ' Live mode was not enabled.')
    return {"detail": "Live book enabled. Start Bot explicitly to trade.", "equity": book.equity}


@router.post("/disable-live")
def disable_live(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.trading_books import activate_paper_book
    try:
        activate_paper_book(db, current_user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return {"detail": "Switched to the separate paper book. Live history is preserved."}


@router.post('/resume-risk')
def resume_risk(confirm: bool = False, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.trading_books import require_idle
    from app.services.portfolio_service import get_or_create_portfolio
    if not confirm:
        raise HTTPException(status_code=400, detail='Confirm resetting the drawdown reference')
    try:
        require_idle(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    book=get_or_create_portfolio(db,current_user.id)
    book.peak_equity=book.equity; book.risk_halted=False; db.commit()
    return {'detail':'Drawdown reference reset to current equity; bot remains stopped'}
