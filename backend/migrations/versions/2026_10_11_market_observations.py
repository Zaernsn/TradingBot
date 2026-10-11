"""Archive bounded public quote/depth observations."""
from alembic import op
import sqlalchemy as sa

revision = 'p61011market'
down_revision = 'p61010guards'
branch_labels = None
depends_on = None


def upgrade():
    from app.db.migration_helpers import create_table_unless_matching
    create_table_unless_matching(op,'market_observations',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('exchange',sa.String(),nullable=False),
        sa.Column('symbol',sa.String(),nullable=False),
        sa.Column('bucket_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('received_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('quote_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('book_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('status',sa.String(),nullable=False),
        sa.Column('evidence',sa.JSON(),nullable=False),
        sa.UniqueConstraint('exchange','symbol','bucket_at',name='uq_market_observation_bucket'))
    indexes={index['name'] for index in sa.inspect(op.get_bind()).get_indexes('market_observations')}
    if 'ix_market_observation_symbol_received' not in indexes:
        op.create_index('ix_market_observation_symbol_received','market_observations',['symbol','received_at'])


def downgrade():
    op.drop_index('ix_market_observation_symbol_received',table_name='market_observations')
    op.drop_table('market_observations')
