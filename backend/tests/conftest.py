import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + str(
    Path(tempfile.mkdtemp(prefix="reconcile-test-")) / "test.db"
).replace("\\", "/")
os.environ["STORAGE_PATH"] = tempfile.mkdtemp(prefix="reconcile-storage-")
os.environ["PARSER"] = "pymupdf"
os.environ["OPENAI_API_KEY"] = ""
os.environ["INVOICE_AZURE_API_KEY"] = ""
import pytest
from fastapi.testclient import TestClient

from backend.app import models  # noqa: F401 - registers mapped tables
from backend.app.api import app
from backend.app.db import Base, engine


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    yield
    # Only the isolated test database is cleared.
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
