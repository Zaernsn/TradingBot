"""Enable memecoin focus and invalidate old position-limited watchlists."""
from alembic import op
import sqlalchemy as sa

revision = 'f90220focus'
down_revision = 'e90219meme'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('risk_configs') as batch:
        batch.alter_column('memecoins_enabled', existing_type=sa.Boolean(),
                           existing_nullable=False, server_default=sa.true())
    op.execute(sa.text('UPDATE risk_configs SET memecoins_enabled = true'))
    op.execute(sa.text('UPDATE bot_states SET watchlist = NULL, watchlist_updated_at = NULL'))


def downgrade():
    # Preserve saved user preferences when reverting the insertion default.
    with op.batch_alter_table('risk_configs') as batch:
        batch.alter_column('memecoins_enabled', existing_type=sa.Boolean(),
                           existing_nullable=False, server_default=sa.false())
