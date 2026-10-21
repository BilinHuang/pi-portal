"""SQLite database setup with WAL mode optimized for Raspberry Pi TF cards."""
from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATA_DIR, DB_PATH

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 15},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Optimize SQLite for SD/TF card longevity and low memory footprint."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.execute("PRAGMA cache_size=-8000;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema_migrations():
    """Ensure newly added columns exist in an existing SQLite DB without data loss."""
    with engine.begin() as conn:
        # 1. Services table migrations
        svc_rows = conn.execute(text("PRAGMA table_info(services);")).fetchall()
        if svc_rows:
            col_names = {r[1] for r in svc_rows}
            if "status" not in col_names:
                conn.execute(
                    text(
                        "ALTER TABLE services ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';"
                    )
                )

        # 2. Users table migrations for AI Rate Limits & Quotas
        user_rows = conn.execute(text("PRAGMA table_info(users);")).fetchall()
        if user_rows:
            user_cols = {r[1] for r in user_rows}
            if "ai_daily_limit" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN ai_daily_limit INTEGER NOT NULL DEFAULT 50;"
                    )
                )
            if "ai_used_today" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN ai_used_today INTEGER NOT NULL DEFAULT 0;"
                    )
                )
            if "ai_rpm_limit" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN ai_rpm_limit INTEGER NOT NULL DEFAULT 10;"
                    )
                )
            if "ai_last_reset" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN ai_last_reset DATETIME DEFAULT '1970-01-01 00:00:00';"
                    )
                )


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
