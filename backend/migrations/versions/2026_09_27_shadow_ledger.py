"""Persistent idempotent Shadow portfolio evidence."""
from alembic import op
import sqlalchemy as sa

revision = 'm90227shadow'
down_revision = 'l90227fees'
branch_labels = None
depends_on = None


def upgrade():
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op,'shadow_runs',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('candidate_id',sa.String(),nullable=False),
        sa.Column('version',sa.String(),nullable=False),
        sa.Column('status',sa.String(),nullable=False),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('last_candle_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('initial_cash',sa.Float(),nullable=False),
        sa.Column('cash',sa.Float(),nullable=False),
        sa.Column('equity',sa.Float(),nullable=False),
        sa.Column('peak_equity',sa.Float(),nullable=False),
        sa.Column('open_positions',sa.JSON(),nullable=False),
        sa.Column('metrics',sa.JSON(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now()),
        sa.UniqueConstraint('user_id','candidate_id',name='uq_shadow_run_candidate'))
    indexes={i['name'] for i in sa.inspect(op.get_bind()).get_indexes('shadow_runs')}
    if 'ix_shadow_runs_user_id' not in indexes:
        op.create_index('ix_shadow_runs_user_id','shadow_runs',['user_id'])
    create_table_unless_matching(op,'shadow_trades',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('run_id',sa.Integer(),sa.ForeignKey('shadow_runs.id'),nullable=False),
        sa.Column('intent_key',sa.String(),nullable=False),
        sa.Column('symbol',sa.String(),nullable=False),
        sa.Column('side',sa.String(),nullable=False),
        sa.Column('quantity',sa.Float(),nullable=False),
        sa.Column('price',sa.Float(),nullable=False),
        sa.Column('fee',sa.Float(),nullable=False),
        sa.Column('pnl',sa.Float(),nullable=True),
        sa.Column('candle_timestamp',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('run_id','intent_key',name='uq_shadow_trade_intent'))
    indexes={i['name'] for i in sa.inspect(op.get_bind()).get_indexes('shadow_trades')}
    if 'ix_shadow_trades_run_id' not in indexes:
        op.create_index('ix_shadow_trades_run_id','shadow_trades',['run_id'])
    create_table_unless_matching(op,'shadow_equity',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('run_id',sa.Integer(),sa.ForeignKey('shadow_runs.id'),nullable=False),
        sa.Column('candle_timestamp',sa.DateTime(timezone=True),nullable=False),
        sa.Column('cash',sa.Float(),nullable=False),
        sa.Column('equity',sa.Float(),nullable=False),
        sa.Column('drawdown_pct',sa.Float(),nullable=False),
        sa.UniqueConstraint('run_id','candle_timestamp',name='uq_shadow_equity_candle'))
    indexes={i['name'] for i in sa.inspect(op.get_bind()).get_indexes('shadow_equity')}
    if 'ix_shadow_equity_run_id' not in indexes:
        op.create_index('ix_shadow_equity_run_id','shadow_equity',['run_id'])


def downgrade():
    op.drop_index('ix_shadow_equity_run_id',table_name='shadow_equity')
    op.drop_table('shadow_equity')
    op.drop_index('ix_shadow_trades_run_id',table_name='shadow_trades')
    op.drop_table('shadow_trades')
    op.drop_index('ix_shadow_runs_user_id',table_name='shadow_runs')
    op.drop_table('shadow_runs')
