"""Single-use password reset tokens and shared authentication rate limits."""
from alembic import op
import sqlalchemy as sa
from app.db.migration_helpers import create_table_unless_matching
revision='d90219reset'
down_revision='c90219live'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('token_version',sa.Integer(),nullable=False,server_default='0'))
    create_table_unless_matching(op,'password_reset_tokens',sa.Column('token_hash',sa.String(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False,index=True),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('used',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    create_table_unless_matching(op,'auth_rate_limits',sa.Column('key',sa.String(),primary_key=True),
        sa.Column('window_at',sa.DateTime(timezone=True),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False))

def downgrade():
    op.drop_table('auth_rate_limits'); op.drop_table('password_reset_tokens'); op.drop_column('users','token_version')
