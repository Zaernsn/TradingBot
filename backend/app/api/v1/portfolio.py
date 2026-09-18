from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import Signal
from app.schemas.portfolio import PortfolioOut, PositionOut, TradeOut, SignalOut
from app.services.portfolio_service import get_or_create_portfolio, recalculate_equity

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/me", response_model=PortfolioOut)
def get_portfolio(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = get_or_create_portfolio(db, current_user.id)
    recalculate_equity(db, portfolio)
    return portfolio


@router.get("/positions", response_model=List[PositionOut])
def get_positions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = get_or_create_portfolio(db, current_user.id)
    return portfolio.positions


@router.get("/trades", response_model=List[TradeOut])
def get_trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = get_or_create_portfolio(db, current_user.id)
    return portfolio.trades


@router.get("/signals", response_model=List[SignalOut])
def get_signals(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = get_or_create_portfolio(db, current_user.id)
    return (
        db.query(Signal)
        .filter(Signal.portfolio_id == portfolio.id)
        .order_by(Signal.created_at.desc())
        .limit(50)
        .all()
    )
