"""Upgrade fresh/versioned databases; recognize only known legacy create_all layouts."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, select, func
from app.core.config import settings
from app.db.base import Base
import app.models


def migrate():
    config=Config(str(Path(__file__).resolve().parents[2]/'alembic.ini'))
    config.set_main_option('script_location',str(Path(__file__).resolve().parents[2]/'migrations'))
    engine=create_engine(settings.DATABASE_URL)
    try:
        inspector=inspect(engine)
        tables=set(inspector.get_table_names())-{'alembic_version'}
        with engine.connect() as connection:
            versioned='alembic_version' in inspector.get_table_names() and connection.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar()>0
        if tables and not versioned:
            legacy={'users','portfolios','positions','trades','signals','bot_states','risk_configs'}
            extras=tables-legacy
            if not legacy.issubset(tables) or extras-{'execution_orders','market_candles','password_reset_tokens','auth_rate_limits','kraken_snapshots','research_snapshots','model_recoveries','strategy_candidates','shadow_runs','shadow_trades','shadow_equity'}:
                raise RuntimeError('Unversioned database has an unknown layout; back up and reconcile its migration baseline')
            with engine.connect() as connection:
                for name in extras:
                    if connection.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar():
                        raise RuntimeError('Unversioned database has newer table data; migration baseline requires manual review')
            later={
                'users':{'token_version'},
                'portfolios':{'book_type','is_active','initial_equity','peak_equity','risk_halted','account_fingerprint'},
                'positions':{'entry_fees'},
                'bot_states':{'lock_token','lock_until'},
                'risk_configs':{'max_invest_per_trade_eur','max_drawdown_pct','max_total_exposure_pct','max_correlated_exposure_pct','correlation_threshold','slippage_pct','memecoins_enabled','memecoin_max_position_pct','memecoin_max_exposure_pct','memecoin_max_spread_pct','memecoin_min_daily_volume_eur','verified_taker_fee_pct','verified_taker_fee_at'},
            }
            observed={t:{c['name'] for c in inspector.get_columns(t)} for t in legacy}
            later['risk_configs'].update({'risk_per_trade_pct','max_holding_hours','discovery_limit','watchlist_limit','entry_strategy','buy_probability_threshold'})
            later['bot_states'].update({'entry_decisions','candidate_status','discovery_stats'})
            expected={t:set(Base.metadata.tables[t].columns.keys())-later.get(t,set()) for t in legacy}
            revision='9e9b4ef6f510'
            if observed!=expected:
                expected['portfolios']-={'target_positions'}
                expected['bot_states']-={'watchlist','watchlist_updated_at'}
                expected['risk_configs']-={'max_open_positions','allocation_mode'}
                revision='eccc293d6dc0'
                if observed!=expected:
                    expected['users']-={'kraken_api_key_encrypted','kraken_api_secret_encrypted'}
                    revision='0001_initial'
                if observed!=expected: raise RuntimeError('Unversioned database columns do not match a supported legacy schema; no migration baseline changed')
            if not any(c['column_names']==['user_id'] for c in inspector.get_unique_constraints('portfolios')):
                raise RuntimeError('Legacy portfolio uniqueness constraint missing; migration baseline requires review')
            if revision=='9e9b4ef6f510' and any(i['name']=='uq_positions_open_symbol' for i in inspector.get_indexes('positions')):
                revision='b76401a8d202'
            command.stamp(config,revision)
        command.upgrade(config,'head')
    finally:
        engine.dispose()

if __name__=='__main__': migrate()
