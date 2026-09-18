from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.user import User
from app.models.portfolio import Portfolio, BotState, RiskConfig
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.config import settings
from datetime import timedelta


def create_user(db: Session, email: str, password: str) -> User:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, hashed_password=get_password_hash(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(Portfolio(user_id=user.id, cash=settings.DEFAULT_PAPER_BALANCE_EUR, equity=settings.DEFAULT_PAPER_BALANCE_EUR))
    db.add(BotState(user_id=user.id))
    db.add(
        RiskConfig(
            user_id=user.id,
            max_position_pct=settings.DEFAULT_MAX_POSITION_PCT,
            stop_loss_pct=settings.DEFAULT_STOP_LOSS_PCT,
            take_profit_pct=settings.DEFAULT_TAKE_PROFIT_PCT,
            fee_pct=settings.DEFAULT_FEE_PCT,
            trading_pair=settings.DEFAULT_TRADING_PAIR,
        )
    )
    db.commit()
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    return user


def generate_token(user: User) -> str:
    return create_access_token({"sub": user.id}, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
