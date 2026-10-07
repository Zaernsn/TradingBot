from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from app.core.config import settings


def test_migration_upgrade_downgrade_preserves_existing_position(tmp_path, monkeypatch):
    path=tmp_path / 'migration.sqlite'
    url=f'sqlite:///{path.as_posix()}'
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    cfg=Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    cfg.set_main_option('script_location',str(Path(__file__).parents[1] / 'migrations'))
    command.upgrade(cfg,'eccc293d6dc0')
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id,email,hashed_password) VALUES (1,'old@example.com','unused')"))
        conn.execute(text("INSERT INTO portfolios (id,user_id,currency,cash,equity,mode) VALUES (1,1,'EUR',400,500,'PAPER')"))
        conn.execute(text("INSERT INTO risk_configs (user_id,max_position_pct,stop_loss_pct,take_profit_pct,fee_pct,max_daily_trades,trading_pair,prediction_horizon) VALUES (1,.2,.03,.06,.0026,10,'BTC/EUR',12)"))
        conn.execute(text("INSERT INTO positions (portfolio_id,symbol,quantity,avg_entry_price,current_price,unrealized_pnl,realized_pnl) VALUES (1,'BTC/EUR',1,100,100,0,0)"))
    command.upgrade(cfg,'head')
    with engine.begin() as conn:
        assert conn.execute(text('SELECT max_open_positions FROM risk_configs')).scalar()==20
        assert conn.execute(text('SELECT memecoins_enabled FROM risk_configs')).scalar()==1
        assert conn.execute(text('SELECT quantity FROM positions')).scalar()==1
        conn.execute(text('UPDATE risk_configs SET trading_pair=NULL'))
    command.downgrade(cfg,'eccc293d6dc0')
    with engine.connect() as conn:
        assert conn.execute(text('SELECT trading_pair FROM risk_configs')).scalar()=='BTC/EUR'
        assert conn.execute(text('SELECT quantity FROM positions')).scalar()==1
    command.upgrade(cfg,'head')
    engine.dispose()


def test_upgrade_legacy_startup_with_new_empty_tables(tmp_path,monkeypatch):
    from app.cli.migrate import migrate
    from app.db.base import Base
    from sqlalchemy import inspect
    url=f'sqlite:///{(tmp_path / "legacy-startup.sqlite").as_posix()}'
    monkeypatch.setattr(settings,'DATABASE_URL',url)
    cfg=Config(str(Path(__file__).parents[1]/'alembic.ini'))
    cfg.set_main_option('script_location',str(Path(__file__).parents[1]/'migrations'))
    command.upgrade(cfg,'9e9b4ef6f510')
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id,email,hashed_password) VALUES (1,'preserved@example.com','hash')"))
        conn.execute(text('DROP TABLE alembic_version'))
    # Reproduce create_all creating new tables while leaving legacy columns untouched.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE execution_orders DROP COLUMN filled_base_fee'))
    assert 'lock_token' not in {c['name'] for c in inspect(engine).get_columns('bot_states')}
    migrate()
    assert 'lock_token' in {c['name'] for c in inspect(engine).get_columns('bot_states')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT email FROM users WHERE id=1')).scalar()=='preserved@example.com'
        assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='m90227shadow'
    migrate()  # Restart is idempotent.
    engine.dispose()
