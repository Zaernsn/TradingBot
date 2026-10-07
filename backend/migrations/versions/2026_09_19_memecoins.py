"""Opt-in memecoin controls."""
from alembic import op
import sqlalchemy as sa
revision='e90219meme'
down_revision='d90219reset'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('risk_configs',sa.Column('memecoins_enabled',sa.Boolean(),nullable=False,server_default=sa.false()))
    for name,value in [('memecoin_max_position_pct','0.05'),('memecoin_max_exposure_pct','0.10'),('memecoin_max_spread_pct','0.003'),('memecoin_min_daily_volume_eur','1000000')]:
        op.add_column('risk_configs',sa.Column(name,sa.Float(),nullable=False,server_default=value))


def downgrade():
    with op.batch_alter_table('risk_configs') as batch:
        for name in ['memecoins_enabled','memecoin_max_position_pct','memecoin_max_exposure_pct','memecoin_max_spread_pct','memecoin_min_daily_volume_eur']:
            batch.drop_column(name)
