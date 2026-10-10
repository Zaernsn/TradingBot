"""Persist independent protective monitoring diagnostics."""
from alembic import op
import sqlalchemy as sa

revision = 'n61010protection'
down_revision = 'm90227shadow'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bot_states',sa.Column('protection_status',sa.JSON(),nullable=True))


def downgrade():
    with op.batch_alter_table('bot_states') as batch:
        batch.drop_column('protection_status')
