from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings


is_sqlite=settings.DATABASE_URL.startswith('sqlite:')
engine = create_engine(settings.DATABASE_URL,
    connect_args={'check_same_thread':False,'timeout':30} if is_sqlite else {})


if is_sqlite:
    @event.listens_for(engine,'connect')
    def configure_sqlite(connection, _):
        cursor=connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
