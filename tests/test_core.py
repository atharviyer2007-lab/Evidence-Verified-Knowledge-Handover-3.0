import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["HANDOVER_DB"] = tempfile.mktemp(suffix=".db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import db
import pipeline
from app import app


def token(client, path="/workspace"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def sign_in(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf": token(client, "/login")},
        follow_redirects=False,
    )


def claims_where(project_id, condition):
    return db.query(f"SELECT * FROM claims WHERE project_id = ? AND {condition}", (project_id,))


@pytest.fixture(scope="module")
def clients():
    with TestClient(app) as reviewer, TestClient(app) as successor:
        sign_in(reviewer, "reviewer", "reviewer123")
        sign_in(successor, "successor", "successor123")
        yield reviewer, successor


@pytest.fixture(scope="module")
def demo(clients):
    reviewer, _ = clients
    response = reviewer.post("/projects/demo", data={"csrf": token(reviewer)}, follow_redirects=False)
    return int(re.search(r"/project/(\d+)/review", response.headers["location"]).group(1))


def test_masking_hides_sensitive_details_but_keeps_dates():
    text, count = pipeline.mask("Email a@b.example, call 98765 43210, password is Hunter2 on 2026-09-14.")
    assert count == 3
    assert "a@b.example" not in text and "Hunter2" not in text and "98765" not in text
    assert "2026-09-14" in text


def test_quote_matching_ignores_line_breaks():
    assert pipeline.find_span("We decided\nto  move it.", "decided to move") is not None
    assert pipeline.find_span("We decided to move it.", "never said this") is None


def test_demo_project_shows_every_grade_except_testimony(demo):
    grades = {row["grade"] for row in claims_where(demo, "1 = 1")}
    assert {"Backed", "Inferred", "Conflicting", "Unknown"} <= grades


def test_conflicting_owners_are_flagged(demo):
    rows = claims_where(demo, "grade = 'Conflicting'")
    assert len(rows) == 2
    assert all("deploy pipeline" in row["note"] for row in rows)


def test_secrets_are_never_stored(demo):
    stored = " ".join(row["content"] for row in db.query("SELECT content FROM sources WHERE project_id = ?", (demo,)))
    assert "Sunrise#2026" not in stored and "finance.lead@" not in stored and "98765" not in stored


def test_a_guess_cannot_be_approved(clients, demo):
    reviewer, _ = clients
    guess = claims_where(demo, "grade = 'Inferred'")[0]
    reviewer.post(f"/claim/{guess['id']}/approve", data={"csrf": token(reviewer)})
    assert db.one("SELECT status FROM claims WHERE id = ?", (guess["id"],))["status"] == "proposed"


def test_cannot_share_before_every_claim_is_reviewed(clients, demo):
    reviewer, _ = clients
    successor_id = db.one("SELECT id FROM users WHERE username = 'successor'")["id"]
    reviewer.post(f"/project/{demo}/share", data={"csrf": token(reviewer), "user_id": successor_id, "days": 7,
                                                  "assignment_note": "Review and complete the remaining project actions."})
    assert not db.query("SELECT id FROM shares WHERE project_id = ?", (demo,))


def test_leaver_answer_becomes_testimony_and_can_be_undone(clients, demo):
    reviewer, _ = clients
    gap = claims_where(demo, "grade = 'Unknown'")[0]
    reviewer.post(f"/claim/{gap['id']}/answer", data={"csrf": token(reviewer), "text": "It was cheaper.", "who": "Priya"})
    assert db.one("SELECT grade FROM claims WHERE id = ?", (gap["id"],))["grade"] == "Testimony"
    reviewer.post(f"/claim/{gap['id']}/undo", data={"csrf": token(reviewer)})
    assert db.one("SELECT grade FROM claims WHERE id = ?", (gap["id"],))["grade"] == "Unknown"


def test_successor_cannot_open_the_review_page(clients, demo):
    _, successor = clients
    assert successor.get(f"/project/{demo}/review").status_code == 403


def test_restricted_claims_never_reach_the_successor(clients, demo):
    reviewer, successor = clients
    for claim in claims_where(demo, "status = 'proposed'"):
        base = f"/claim/{claim['id']}"
        if claim["grade"] == "Inferred":
            reviewer.post(f"{base}/reject", data={"csrf": token(reviewer)})
        else:
            if claim["grade"] == "Unknown" or claim["type"] == "open_question":
                reviewer.post(
                    f"{base}/answer",
                    data={"csrf": token(reviewer), "text": "Confirmed with the person leaving.", "who": "Project owner"},
                )
            reviewer.post(f"{base}/approve", data={"csrf": token(reviewer), "reason": "The task board is newer."})
    assert not claims_where(demo, "status = 'proposed'")
    successor_id = db.one("SELECT id FROM users WHERE username = 'successor'")["id"]
    reviewer.post(f"/project/{demo}/share", data={"csrf": token(reviewer), "user_id": successor_id, "days": 7,
                                                  "assignment_note": "Review and complete the remaining project actions."})
    plan = successor.get(f"/project/{demo}/plan").text
    assert "single form" in plan
    assert "vendor contract" not in plan and "sponsorship" not in plan
    restricted = claims_where(demo, "access_rank = 2 AND status = 'approved'")[0]
    assert successor.get(f"/claim/{restricted['id']}/evidence").status_code == 404
    assert reviewer.get(f"/claim/{restricted['id']}/evidence").status_code == 200
    exported = successor.get(f"/project/{demo}/export.json").text
    assert "vendor contract" not in exported


def test_successor_can_acknowledge(clients, demo):
    _, successor = clients
    successor.post(f"/project/{demo}/acknowledge", data={"csrf": token(successor)})
    assert db.one("SELECT acknowledged_at FROM shares WHERE project_id = ?", (demo,))["acknowledged_at"]


def test_revoking_access_removes_the_plan(clients, demo):
    reviewer, successor = clients
    share = db.one("SELECT id FROM shares WHERE project_id = ?", (demo,))
    reviewer.post(f"/share/{share['id']}/revoke", data={"csrf": token(reviewer)})
    assert "Nothing is shared with you" in successor.get(f"/project/{demo}/plan").text


def test_forms_without_a_security_token_are_refused(clients):
    reviewer, _ = clients
    assert reviewer.post("/projects", data={"name": "Sneaky"}).status_code == 403


def test_wrong_password_is_rejected():
    with TestClient(app) as client:
        response = sign_in(client, "nobody", "wrong")
        assert response.headers["location"] == "/login"
        assert client.get("/workspace", follow_redirects=False).headers["location"] == "/login"
