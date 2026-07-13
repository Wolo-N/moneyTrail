import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # para importar fixtures/*

from moneytrail import db  # noqa: E402


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()
