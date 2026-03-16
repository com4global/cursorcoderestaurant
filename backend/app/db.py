from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from .config import settings

connect_args = {}
is_sqlite = settings.database_url.startswith("sqlite")

if is_sqlite:
    connect_args["check_same_thread"] = False
else:
    # PostgreSQL (Supabase) — add connect timeout and keepalives
    connect_args["connect_timeout"] = 10
    connect_args["keepalives"] = 1
    connect_args["keepalives_idle"] = 30
    connect_args["keepalives_interval"] = 10

engine_kwargs = {
    "connect_args": connect_args,
    "pool_pre_ping": not is_sqlite,
}

if is_sqlite:
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 30
    engine_kwargs["pool_timeout"] = 60
    engine_kwargs["pool_recycle"] = 1800
else:
    # Use NullPool for serverless (Vercel) — no persistent pool
    engine_kwargs["poolclass"] = NullPool

engine = create_engine(settings.database_url, **engine_kwargs)

# Enable WAL mode & foreign keys for SQLite
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
