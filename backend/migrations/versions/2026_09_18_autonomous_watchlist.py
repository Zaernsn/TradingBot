"""autonomous watchlist and multi-position"""
from alembic import op
import sqlalchemy as sa

revision = "9e9b4ef6f510"
down_revision = "eccc293d6dc0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("risk_configs", sa.Column("max_open_positions", sa.Integer, nullable=False, server_default="5"))
    op.add_column("risk_configs", sa.Column("allocation_mode", sa.String, nullable=False, server_default="equal"))
    with op.batch_alter_table("risk_configs") as batch:
        batch.alter_column("trading_pair", existing_type=sa.String(), nullable=True)

    op.add_column("bot_states", sa.Column("watchlist", sa.JSON, nullable=True))
    op.add_column("bot_states", sa.Column("watchlist_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("portfolios", sa.Column("target_positions", sa.Integer, nullable=False, server_default="5"))

    # Optional performance index for position lookups by portfolio + symbol.
    op.create_index("ix_positions_portfolio_symbol", "positions", ["portfolio_id", "symbol"], unique=False)


def downgrade():
    op.drop_index("ix_positions_portfolio_symbol", table_name="positions")
    op.drop_column("portfolios", "target_positions")
    op.drop_column("bot_states", "watchlist_updated_at")
    op.drop_column("bot_states", "watchlist")
    op.execute(sa.text("UPDATE risk_configs SET trading_pair = 'BTC/EUR' WHERE trading_pair IS NULL"))
    with op.batch_alter_table("risk_configs") as batch:
        batch.alter_column("trading_pair", existing_type=sa.String(), nullable=False)
    op.drop_column("risk_configs", "allocation_mode")
    op.drop_column("risk_configs", "max_open_positions")
