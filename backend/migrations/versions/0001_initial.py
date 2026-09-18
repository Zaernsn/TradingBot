"""Initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("email", sa.String(), unique=True, index=True, nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("currency", sa.String(), default="EUR", nullable=False),
        sa.Column("cash", sa.Float(), default=500.0, nullable=False),
        sa.Column("equity", sa.Float(), default=500.0, nullable=False),
        sa.Column("mode", sa.String(), default="PAPER", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), default=0.0, nullable=False),
        sa.Column("avg_entry_price", sa.Float(), default=0.0, nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), default=0.0, nullable=False),
        sa.Column("realized_pnl", sa.Float(), default=0.0, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), default=0.0, nullable=False),
        sa.Column("slippage", sa.Float(), default=0.0, nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("mode", sa.String(), default="PAPER", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "bot_states",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("is_running", sa.Boolean(), default=False, nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("health", sa.String(), default="UNKNOWN", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "risk_configs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("max_position_pct", sa.Float(), default=0.20, nullable=False),
        sa.Column("stop_loss_pct", sa.Float(), default=0.03, nullable=False),
        sa.Column("take_profit_pct", sa.Float(), default=0.06, nullable=False),
        sa.Column("fee_pct", sa.Float(), default=0.0026, nullable=False),
        sa.Column("max_daily_trades", sa.Integer(), default=10, nullable=False),
        sa.Column("trading_pair", sa.String(), default="BTC/EUR", nullable=False),
        sa.Column("prediction_horizon", sa.Integer(), default=12, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("risk_configs")
    op.drop_table("bot_states")
    op.drop_table("signals")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("portfolios")
    op.drop_table("users")
