from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.portfolio import BotStateOut
from app.services.bot_service import bot_orchestrator
from app.models.portfolio import Portfolio, Position
from app.services.risk_service import get_risk_config

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get('/research/metadata/export')
def export_research_metadata(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.research_metadata import export_metadata
    return export_metadata(db,current_user.id)


@router.post('/research/metadata/import')
def import_research_metadata(payload: dict = Body(...), db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    from app.services.research_metadata import import_metadata
    try:
        return import_metadata(db,current_user.id,payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc))


@router.get('/research/status')
def get_research_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.strategy_research import research_status
    return research_status(db,current_user.id)


@router.get('/research/forward')
def get_forward_evidence(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.services.research_service import forward_report
    from app.ml.evaluation import promotion_report
    book = db.query(Portfolio).filter(Portfolio.user_id == current_user.id, Portfolio.is_active.is_(True)).first()
    forward = forward_report(db, book.id) if book else {}
    return {'forward': forward, 'promotion': promotion_report({}, forward)}


@router.get("/state", response_model=BotStateOut)
def get_state(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.portfolio import BotState
    state = db.query(BotState).filter(BotState.user_id == current_user.id).first()
    if not state:
        state = BotState(user_id=current_user.id)
        db.add(state)
        db.commit()
        db.refresh(state)
    config = get_risk_config(db, current_user.id)
    count = db.query(Position).join(Portfolio).filter(
        Portfolio.user_id == current_user.id, Portfolio.is_active.is_(True), Position.quantity > 0,
    ).count()
    if state.entry_decisions is None: state.entry_decisions = {}
    result = BotStateOut.model_validate(state)
    result.watchlist_refresh_seconds = 300 if config.memecoins_enabled else 86400
    from app.exchanges.universe import CURATED_PAIRS, is_memecoin
    result.watchlist = [
        symbol for symbol in result.watchlist or []
        if symbol in CURATED_PAIRS or (config.memecoins_enabled and is_memecoin(symbol))
    ][:config.watchlist_limit]
    result.memecoin_watchlist_count = sum(is_memecoin(s) for s in result.watchlist or [])
    result.memecoin_watchlist_target = max(0,config.watchlist_limit - sum(not is_memecoin(s) for s in result.watchlist or [])) if config.memecoins_enabled else 0
    result.open_slots = max(0, config.max_open_positions - count)
    from collections import Counter
    from datetime import datetime, timezone
    from app.services.market_data import utc
    current=datetime.now(timezone.utc)
    reasons=[]
    for decision in result.entry_decisions.values():
        try:
            age=(current-utc(datetime.fromisoformat(decision['checked_at']))).total_seconds()
        except (KeyError,ValueError,TypeError): age=float('inf')
        if not state.is_running or age>120 or age<0: continue
        code=decision.get('code','unknown')
        if code=='waiting_candle': code=decision.get('model_status','waiting_candle')
        if code not in {'held','submitted','ready'}: reasons.append(code)
    result.blocker_summary=dict(Counter(reasons))
    return result


@router.post("/start", response_model=BotStateOut)
async def start_bot(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        await bot_orchestrator.start(db, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return get_state(db, current_user)


@router.post("/stop", response_model=BotStateOut)
async def stop_bot(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    await bot_orchestrator.stop(db, current_user)
    return get_state(db, current_user)


@router.post("/emergency-stop", response_model=BotStateOut)
async def emergency_stop(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    await bot_orchestrator.emergency_stop(db, current_user)
    return get_state(db, current_user)
