"""Separate trading books, durable orders, cost basis and risk state."""
from alembic import op
import sqlalchemy as sa
from app.db.migration_helpers import create_table_unless_matching
revision='c90219live'
down_revision='b76401a8d202'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('portfolios', sa.Column('book_type',sa.String(),nullable=False,server_default='PAPER'))
    op.add_column('portfolios', sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.add_column('portfolios', sa.Column('initial_equity',sa.Float(),nullable=False,server_default='500'))
    op.add_column('portfolios', sa.Column('peak_equity',sa.Float(),nullable=False,server_default='500'))
    op.add_column('portfolios', sa.Column('risk_halted',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('portfolios', sa.Column('account_fingerprint',sa.String(),nullable=True))
    inspector=sa.inspect(op.get_bind())
    unique=next(c for c in inspector.get_unique_constraints('portfolios') if c['column_names']==['user_id'])
    with op.batch_alter_table('portfolios',naming_convention={'uq':'uq_%(table_name)s_%(column_0_name)s'}) as batch:
        batch.drop_constraint(unique['name'] or 'uq_portfolios_user_id',type_='unique')
        batch.create_unique_constraint('uq_portfolios_user_book',['user_id','book_type'])
        batch.create_unique_constraint('uq_portfolios_account_fingerprint',['account_fingerprint'])
    op.create_index('uq_portfolios_active_user','portfolios',['user_id'],unique=True,
                    sqlite_where=sa.text('is_active = 1'),postgresql_where=sa.text('is_active = true'))
    op.add_column('positions',sa.Column('entry_fees',sa.Float(),nullable=False,server_default='0'))
    # Historical entry fees cannot be safely reconstructed for all partial positions.
    # Preserve balances and price basis; accounting improvements apply to new fills.
    op.execute(sa.text('UPDATE portfolios SET peak_equity = CASE WHEN equity > 500 THEN equity ELSE 500 END'))
    op.add_column('bot_states',sa.Column('lock_token',sa.String(),nullable=True))
    op.add_column('bot_states',sa.Column('lock_until',sa.DateTime(timezone=True),nullable=True))
    for name,default in [('max_drawdown_pct','.10'),('max_total_exposure_pct','.80'),
                         ('max_correlated_exposure_pct','.40'),('correlation_threshold','.80'),('slippage_pct','.001')]:
        op.add_column('risk_configs',sa.Column(name,sa.Float(),nullable=False,server_default=default))
    create_table_unless_matching(op,'execution_orders',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('portfolio_id',sa.Integer(),sa.ForeignKey('portfolios.id'),nullable=False,index=True),
        sa.Column('client_id',sa.String(),nullable=False,unique=True),
        sa.Column('exchange_id',sa.String(),unique=True),
        sa.Column('symbol',sa.String(),nullable=False),sa.Column('side',sa.String(),nullable=False),
        sa.Column('requested_quantity',sa.Float(),nullable=False),sa.Column('status',sa.String(),nullable=False),
        sa.Column('filled_quantity',sa.Float(),nullable=False),sa.Column('filled_cost',sa.Float(),nullable=False),
        sa.Column('filled_fee',sa.Float(),nullable=False),sa.Column('filled_base_fee',sa.Float(),nullable=False),sa.Column('last_error',sa.Text()),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now()))
    create_table_unless_matching(op,'market_candles',sa.Column('symbol',sa.String(),primary_key=True),
        sa.Column('timeframe',sa.String(),primary_key=True),sa.Column('timestamp',sa.DateTime(timezone=True),primary_key=True),
        *[sa.Column(c,sa.Float(),nullable=False) for c in ['open','high','low','close','volume']])


def downgrade():
    conn=op.get_bind()
    if conn.execute(sa.text("SELECT COUNT(*) FROM portfolios WHERE book_type = 'LIVE'")).scalar():
        raise RuntimeError('Archive live books explicitly before downgrading; live financial records will not be deleted')
    op.drop_table('market_candles'); op.drop_table('execution_orders')
    for name in ['max_drawdown_pct','max_total_exposure_pct','max_correlated_exposure_pct','correlation_threshold','slippage_pct']:
        op.drop_column('risk_configs',name)
    op.drop_column('bot_states','lock_until'); op.drop_column('bot_states','lock_token')
    op.drop_column('positions','entry_fees')
    op.drop_index('uq_portfolios_active_user',table_name='portfolios')
    with op.batch_alter_table('portfolios') as batch:
        batch.drop_constraint('uq_portfolios_user_book',type_='unique')
        batch.drop_constraint('uq_portfolios_account_fingerprint',type_='unique')
        batch.create_unique_constraint('uq_portfolios_user_id',['user_id'])
        for name in ['book_type','is_active','initial_equity','peak_equity','risk_halted','account_fingerprint']:
            batch.drop_column(name)
