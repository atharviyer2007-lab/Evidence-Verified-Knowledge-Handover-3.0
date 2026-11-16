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


def ack_all(client, project_id):
    """Pass every section check with the right answers and acknowledge each section, as a careful successor would."""
    import db
    import quiz

    csrf = lambda html: re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    share = db.one("SELECT id FROM shares WHERE project_id = ? AND revoked = 0 ORDER BY id DESC", (project_id,))
    for index, title in enumerate(quiz.section_titles()):
        page = client.get(f"/project/{project_id}/check/{index}")
        if page.status_code != 200:
            continue
        data = {"csrf": csrf(page.text)}
        for question in quiz.questions_for(share["id"], title):
            data[f"q{question['id']}"] = question["correct_index"]
        if len(data) > 1:
            client.post(f"/project/{project_id}/check/{index}", data=data)
        client.post(f"/project/{project_id}/check/{index}/acknowledge", data={"csrf": data["csrf"]})
