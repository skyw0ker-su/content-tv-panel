import os
import tempfile

# Configure the server before the app module reads its settings.
_work_dir = tempfile.mkdtemp(prefix="signage-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_work_dir}/test.db"
os.environ["STORAGE_DIR"] = f"{_work_dir}/storage"
os.environ["ADMIN_TOKEN"] = "test-admin"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN = {"X-Admin-Token": "test-admin"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
