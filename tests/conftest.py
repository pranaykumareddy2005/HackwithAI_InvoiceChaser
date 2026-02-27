import os
from pathlib import Path

import pytest

from db.database import configure_engine


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """
    Provide an isolated SQLite DB file path and reconfigure the engine / session
    to point at it for the duration of each test.
    """
    db_file = tmp_path / "test_invoice_chaser.db"
    url = f"sqlite:///{db_file}"
    os.environ["DATABASE_URL"] = url
    configure_engine(url)
    return db_file

