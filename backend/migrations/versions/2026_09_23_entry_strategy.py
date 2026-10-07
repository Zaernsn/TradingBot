"""Selectable momentum entries; existing accounts keep their model strategy."""
from alembic import op
import sqlalchemy as sa

revision = 'j90223strategy'
down_revision = 'i90221drift'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('risk_configs', sa.Column('entry_strategy', sa.String(), nullable=False, server_default='model'))
    op.add_column('risk_configs', sa.Column('buy_probability_threshold', sa.Float(), nullable=False, server_default='0.6'))


def downgrade():
    with op.batch_alter_table('risk_configs') as batch:
        batch.drop_column('buy_probability_threshold')
        batch.drop_column('entry_strategy')
