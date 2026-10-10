"""Optional, persistent rolling-loss and execution-quality entry guards."""
from alembic import op
import sqlalchemy as sa

revision = 'p61010guards'
down_revision = 'o61010evidence'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('portfolios', sa.Column('entry_halt', sa.JSON(), nullable=True))
    for field in ('daily_loss_pct', 'weekly_loss_pct', 'max_realized_slippage_pct'):
        op.add_column('risk_configs', sa.Column(field, sa.Float(), nullable=False, server_default='0'))
    op.add_column('risk_configs', sa.Column('max_order_failures', sa.Integer(), nullable=False, server_default='0'))
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op, 'equity_checkpoints',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id'), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('equity', sa.Float(), nullable=False),
        sa.Column('funding_basis', sa.Float(), nullable=False))
    if 'ix_equity_checkpoint_book_time' not in {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('equity_checkpoints')}:
        op.create_index('ix_equity_checkpoint_book_time', 'equity_checkpoints', ['portfolio_id', 'captured_at'])


def downgrade():
    op.drop_table('equity_checkpoints')
    with op.batch_alter_table('risk_configs') as batch:
        for field in ('daily_loss_pct', 'weekly_loss_pct', 'max_realized_slippage_pct', 'max_order_failures'):
            batch.drop_column(field)
    with op.batch_alter_table('portfolios') as batch:
        batch.drop_column('entry_halt')
