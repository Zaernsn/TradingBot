"""Set a twenty-position budget and refresh the memecoin shortlist."""
from alembic import op
import sqlalchemy as sa

revision = 'g90220slots'
down_revision = 'f90220focus'
branch_labels = None
depends_on = None


def upgrade():
    for table, column in [('risk_configs', 'max_open_positions'), ('portfolios', 'target_positions')]:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.Integer(), existing_nullable=False, server_default='20')
        op.execute(sa.text(f'UPDATE {table} SET {column} = 20'))
    op.execute(sa.text('UPDATE bot_states SET watchlist = NULL, watchlist_updated_at = NULL'))


def downgrade():
    for table, column in [('risk_configs', 'max_open_positions'), ('portfolios', 'target_positions')]:
        op.execute(sa.text(f'UPDATE {table} SET {column} = 10 WHERE {column} > 10'))
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.Integer(), existing_nullable=False, server_default='5')
