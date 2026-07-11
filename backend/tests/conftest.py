from __future__ import annotations

import os
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[2]
TEST_DATA = PROJECT_ROOT / "backend" / ".test-data"
TEST_DATA.mkdir(parents=True, exist_ok=True)
os.environ["WXA_DATA_DIR"] = str(TEST_DATA)
os.environ["WXA_DISABLE_WATCHER"] = "1"

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_absent_process_probe():
    """Keep tests deterministic without offering a production bypass.

    TestClient never opens a TCP socket and the watcher is disabled above. The
    production application state always uses the real Windows process probe.
    """
    original = app.state.process_probe
    app.state.process_probe = lambda: False
    yield
    app.state.process_probe = original


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
