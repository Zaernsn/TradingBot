from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.portfolio import Portfolio
from app.exchanges.paper import PaperExchange
from app.exchanges.base import OrderSide
from app.services.trading_service import execute_paper_trade


def test_buy_and_sell():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    portfolio = Portfolio(user_id=1, cash=500.0, equity=500.0, mode="PAPER", currency="EUR")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)

    exchange = PaperExchange()

    trade = execute_paper_trade(
        db,
        portfolio,
        exchange,
        "BTC/EUR",
        OrderSide.BUY,
        0.001,
        50000.0,
        fee_pct=0.0026,
        reason="test buy",
    )

    assert trade.side == "BUY"
    assert portfolio.cash < 500.0

    sell_trade = execute_paper_trade(
        db,
        portfolio,
        exchange,
        "BTC/EUR",
        OrderSide.SELL,
        0.001,
        51000.0,
        fee_pct=0.0026,
        reason="test sell",
    )

    assert sell_trade.side == "SELL"
    db.close()
