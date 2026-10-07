"""Enforce one open position per portfolio and symbol."""
from alembic import op
import sqlalchemy as sa

revision = 'b76401a8d202'
down_revision = '9e9b4ef6f510'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('uq_positions_open_symbol', 'positions', ['portfolio_id', 'symbol'],
                    unique=True, sqlite_where=sa.text('quantity > 0'),
                    postgresql_where=sa.text('quantity > 0'))


def downgrade():
    op.drop_index('uq_positions_open_symbol', table_name='positions')
