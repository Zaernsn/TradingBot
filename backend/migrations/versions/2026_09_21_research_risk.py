"""Opt-in risk budgeting and maximum holding period; preserve existing behavior."""
from alembic import op
import sqlalchemy as sa

revision = 'h90221risk'
down_revision = 'h90220overview'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bot_states', sa.Column('entry_decisions', sa.JSON(), nullable=True))
    with op.batch_alter_table('risk_configs') as batch:
        batch.add_column(sa.Column('risk_per_trade_pct', sa.Float(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('max_holding_hours', sa.Integer(), nullable=False, server_default='0'))
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op, 'research_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('portfolio_id', sa.Integer(), sa.ForeignKey('portfolios.id'), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('candidate_id', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False))
    if not any(i['name']=='ix_research_snapshots_portfolio_id' for i in sa.inspect(op.get_bind()).get_indexes('research_snapshots')):
        op.create_index('ix_research_snapshots_portfolio_id', 'research_snapshots', ['portfolio_id'])


def downgrade():
    op.drop_column('bot_states', 'entry_decisions')
    op.drop_table('research_snapshots')
    with op.batch_alter_table('risk_configs') as batch:
        batch.drop_column('max_holding_hours')
        batch.drop_column('risk_per_trade_pct')
