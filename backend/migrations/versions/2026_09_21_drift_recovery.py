"""Persistent model recovery and discovery diagnostics."""
from alembic import op
import sqlalchemy as sa

revision = 'i90221drift'
down_revision = 'h90221risk'
branch_labels = None
depends_on = None


def upgrade():
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op, 'model_recoveries',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('portfolio_id',sa.Integer(),sa.ForeignKey('portfolios.id'),nullable=False),
        sa.Column('symbol',sa.String(),nullable=False),
        sa.Column('signature',sa.String(),nullable=False),
        sa.Column('candle_timestamp',sa.String(),nullable=False),
        sa.Column('state',sa.String(),nullable=False),
        sa.Column('attempted_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('retry_after',sa.DateTime(timezone=True),nullable=False),
        sa.Column('message',sa.Text(),nullable=False),
        sa.Column('diagnostics',sa.JSON(),nullable=True),
        sa.UniqueConstraint('portfolio_id','symbol',name='uq_model_recovery_symbol'))
    op.add_column('bot_states',sa.Column('discovery_stats',sa.JSON(),nullable=True))
    op.add_column('bot_states',sa.Column('candidate_status',sa.JSON(),nullable=True))
    op.add_column('risk_configs',sa.Column('discovery_limit',sa.Integer(),nullable=False,server_default='60'))
    op.add_column('risk_configs',sa.Column('watchlist_limit',sa.Integer(),nullable=False,server_default='30'))


def downgrade():
    op.drop_table('model_recoveries')
    with op.batch_alter_table('bot_states') as batch:
        batch.drop_column('candidate_status')
        batch.drop_column('discovery_stats')
    with op.batch_alter_table('risk_configs') as batch:
        batch.drop_column('watchlist_limit')
        batch.drop_column('discovery_limit')
