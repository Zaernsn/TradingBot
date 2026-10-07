"""Persist the last verified Kraken taker fee used by Live sizing."""
from alembic import op
import sqlalchemy as sa

revision = 'l90227fees'
down_revision = 'k90223adaptive'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('risk_configs',sa.Column('verified_taker_fee_pct',sa.Float(),nullable=True))
    op.add_column('risk_configs',sa.Column('verified_taker_fee_at',sa.DateTime(timezone=True),nullable=True))


def downgrade():
    with op.batch_alter_table('risk_configs') as batch:
        batch.drop_column('verified_taker_fee_at')
        batch.drop_column('verified_taker_fee_pct')
