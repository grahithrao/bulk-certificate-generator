from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

# Engine configuration
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=settings.debug,
)


# SQLite PRAGMA configuration for concurrency and durability
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        # Enable Write-Ahead Logging for high-concurrency read/write
        cursor.execute("PRAGMA journal_mode=WAL;")
        # Enforce foreign key constraints
        cursor.execute("PRAGMA foreign_keys=ON;")
        # Set busy timeout to 5000ms so concurrent transactions wait rather than fail immediately
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and safely closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None) -> None:
    """Create database tables if they do not exist."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
