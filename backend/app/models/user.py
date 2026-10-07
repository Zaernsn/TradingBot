from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    kraken_api_key_encrypted = Column(String, nullable=True)
    kraken_api_secret_encrypted = Column(String, nullable=True)
    token_version = Column(Integer, default=0, server_default="0", nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    portfolios = relationship("Portfolio", back_populates="user")
    bot_state = relationship("BotState", uselist=False)
    risk_config = relationship("RiskConfig", uselist=False)


class PasswordResetToken(Base):
    __tablename__ = 'password_reset_tokens'
    token_hash = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuthRateLimit(Base):
    __tablename__ = 'auth_rate_limits'
    key = Column(String, primary_key=True)
    window_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False)
