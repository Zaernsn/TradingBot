"""Kraken valuation history and maximum investment per trade."""
from alembic import op
import sqlalchemy as sa

revision = 'h90220overview'
down_revision = 'g90220slots'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('risk_configs', sa.Column('max_invest_per_trade_eur', sa.Float(), nullable=False, server_default='0'))
    if not sa.inspect(op.get_bind()).has_table('kraken_snapshots'):
        op.create_table('kraken_snapshots',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('account_key', sa.String(), nullable=False),
            sa.Column('equity', sa.Float(), nullable=True),
            sa.Column('holdings', sa.JSON(), nullable=False),
            sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_kraken_snapshots_user_id', 'kraken_snapshots', ['user_id'])
        op.create_index('ix_kraken_snapshots_captured_at', 'kraken_snapshots', ['captured_at'])


def downgrade():
    op.drop_table('kraken_snapshots')
    with op.batch_alter_table('risk_configs') as batch:
        batch.drop_column('max_invest_per_trade_eur')
