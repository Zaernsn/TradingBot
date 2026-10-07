from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.portfolio import RiskConfig, BotState, Position, Portfolio


def test_risk_config_defaults():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    config = RiskConfig(user_id=1)
    db.add(config)
    db.commit()
    db.refresh(config)

    assert config.max_open_positions == 20
    assert config.allocation_mode == "equal"
    assert config.trading_pair is None
    db.close()


def test_bot_state_watchlist():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    state = BotState(user_id=1, watchlist=["BTC/EUR", "ETH/EUR"])
    db.add(state)
    db.commit()
    db.refresh(state)

    assert state.watchlist == ["BTC/EUR", "ETH/EUR"]
    assert state.watchlist_updated_at is None
    db.close()


def test_portfolio_target_positions_default():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    portfolio = Portfolio(user_id=1)
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    assert portfolio.target_positions == 20
    db.close()
