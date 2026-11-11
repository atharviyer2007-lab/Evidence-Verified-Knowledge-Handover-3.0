import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("HANDOVER_DB", tempfile.mktemp(suffix=".db"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


def log_in(client, username, password):
    page = client.get("/login").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    client.post("/login", data={"username": username, "password": password, "csrf": csrf})


@pytest.fixture(scope="module")
def clients():
    from app import app

    with TestClient(app) as reviewer, TestClient(app) as successor:
        log_in(reviewer, "reviewer", "reviewer123")
        log_in(successor, "successor", "successor123")
        yield reviewer, successor
