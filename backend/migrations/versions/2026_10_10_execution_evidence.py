"""Persist passive live-order execution measurements."""
from alembic import op
import sqlalchemy as sa

revision = 'o61010evidence'
down_revision = 'n61010protection'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('execution_orders', sa.Column('execution_evidence', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('execution_orders') as batch:
        batch.drop_column('execution_evidence')
