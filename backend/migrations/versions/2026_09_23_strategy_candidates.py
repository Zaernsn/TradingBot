"""Constrained automatically researched strategy candidates."""
from alembic import op
import sqlalchemy as sa

revision = 'k90223adaptive'
down_revision = 'j90223strategy'
branch_labels = None
depends_on = None


def upgrade():
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op,
        'strategy_candidates',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('candidate_id',sa.String(),nullable=False),
        sa.Column('parameters',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(),nullable=False),
        sa.Column('metrics',sa.JSON(),nullable=False),
        sa.Column('tested_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('user_id','candidate_id',name='uq_strategy_candidate_user'),
    )
    indexes={index['name'] for index in sa.inspect(op.get_bind()).get_indexes('strategy_candidates')}
    if 'ix_strategy_candidates_user_id' not in indexes:
        op.create_index('ix_strategy_candidates_user_id','strategy_candidates',['user_id'])


def downgrade():
    op.drop_index('ix_strategy_candidates_user_id',table_name='strategy_candidates')
    op.drop_table('strategy_candidates')
