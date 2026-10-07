from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.portfolio import Signal, Trade
from app.schemas.portfolio import PortfolioOut, PositionOut, TradeOut, SignalOut
from app.services.portfolio_service import get_or_create_portfolio, recalculate_equity

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get('/kraken-overview')
async def kraken_overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from fastapi import HTTPException
    from app.services.kraken_overview import account_overview
    try:
        return await account_overview(db, current_user)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=502, detail='Unable to sync Kraken balances. Check your saved API key and balance-query permission.')


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
    return db.query(Trade).filter(Trade.portfolio_id == portfolio.id).order_by(Trade.created_at.desc(), Trade.id.desc()).all()


@router.get("/signals", response_model=List[SignalOut])
def get_signals(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolio = get_or_create_portfolio(db, current_user.id)
    return (
        db.query(Signal)
        .filter(Signal.portfolio_id == portfolio.id)
        .order_by(Signal.created_at.desc(), Signal.id.desc())
        .limit(50)
        .all()
    )

@router.get('/orders')
def get_execution_orders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.portfolio import ExecutionOrder
    book=get_or_create_portfolio(db,current_user.id)
    rows=db.query(ExecutionOrder).filter(ExecutionOrder.portfolio_id==book.id).order_by(ExecutionOrder.id.desc()).limit(100).all()
    fields=('id','client_id','exchange_id','symbol','side','status','requested_quantity','filled_quantity','filled_fee','last_error','created_at')
    return [{field:getattr(row,field) for field in fields} for row in rows]
