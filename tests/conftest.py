from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.services.certificates import init_fonts


@pytest.fixture(scope="session", autouse=True)
def setup_test_fonts():
    """Ensure font files are available and initialized for tests."""
    init_fonts(settings.fonts_dir)


@pytest.fixture
def temp_storage(tmp_path: Path):
    """Provide an isolated temporary storage and certificates directory for tests."""
    storage_dir = tmp_path / "storage"
    certs_dir = storage_dir / "certificates"
    certs_dir.mkdir(parents=True, exist_ok=True)

    orig_storage = settings.storage_dir
    settings.storage_dir = storage_dir

    yield storage_dir

    settings.storage_dir = orig_storage


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide an isolated SQLite database session for each test."""
    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db_session, temp_storage):
    """Provide a FastAPI TestClient wired to the test database and temp storage."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
