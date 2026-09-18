from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.portfolio import BotStateOut
from app.services.bot_service import bot_orchestrator

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/state", response_model=BotStateOut)
def get_state(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.portfolio import BotState
    state = db.query(BotState).filter(BotState.user_id == current_user.id).first()
    if not state:
        state = BotState(user_id=current_user.id)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


@router.post("/start", response_model=BotStateOut)
async def start_bot(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await bot_orchestrator.start(db, current_user)


@router.post("/stop", response_model=BotStateOut)
async def stop_bot(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await bot_orchestrator.stop(db, current_user)


@router.post("/emergency-stop", response_model=BotStateOut)
async def emergency_stop(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await bot_orchestrator.emergency_stop(db, current_user)
