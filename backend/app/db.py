from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Base.metadata.create_all() only creates missing TABLES, not columns added
# to an already-existing one -- and this local sqlite file holds real user
# data (saved interests, feedback history) that a drop-and-recreate would
# destroy. Idempotent, additive-only ALTER TABLE instead: safe to call on
# every startup, a no-op once the columns already exist.
_NEW_COLUMNS = {
    "events": {
        "category_native": "VARCHAR(128)",
        "venue_name_native": "VARCHAR(256)",
        "location_native": "VARCHAR(256)",
        "embedding": "TEXT",
        "scored_at": "DATETIME",
        "scored_profile_version": "DATETIME",
    },
    "interest_profiles": {
        "embedding": "TEXT",
        "excluded_keywords": "TEXT",
    },
    "ask_logs": {
        "referenced_events": "TEXT",
    },
}

# ALTER TABLE ADD COLUMN backfills existing rows with NULL, not the ORM's
# `default=list` (that only applies to rows the ORM itself INSERTs after
# the column exists) -- and unlike a plain string/number column, a JSON
# *list* column left NULL breaks its Pydantic response schema (`list[str]
# = []` only fills a genuinely *missing* value, not an explicit None),
# which surfaced as a 500 on every /api/interests request against the one
# pre-existing profile row. Backfill any such column to an empty JSON
# array right after adding it.
_JSON_LIST_BACKFILLS = {
    "interest_profiles": ["excluded_keywords"],
    "ask_logs": ["referenced_events"],
}


def ensure_schema() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for column, coltype in columns.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
        for table, columns in _JSON_LIST_BACKFILLS.items():
            for column in columns:
                conn.execute(text(f"UPDATE {table} SET {column} = '[]' WHERE {column} IS NULL"))
        conn.commit()
