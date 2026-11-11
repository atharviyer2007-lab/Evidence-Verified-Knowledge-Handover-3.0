import io
import re
import sqlite3
import xml.etree.ElementTree as ET

import pytest
from docx import Document

import db
import exports
import pipeline
from test_core import claims_where, token
from test_features import approve_all, new_project, share, upload


def demo_project(client, kind="events"):
    response = client.post("/projects/demo", data={"csrf": token(client), "kind": kind}, follow_redirects=False)
    return int(re.search(r"/project/(\d+)/", response.headers["location"]).group(1))


@pytest.fixture(scope="module")
def shared_demo(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    approve_all(reviewer, pid)
    share(reviewer, pid)
    return pid


def test_redo_restores_what_undo_removed(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "Redo project")
    claim = claims_where(pid, "type = 'decision'")[0]
    base = f"/claim/{claim['id']}"
    reviewer.post(f"{base}/approve", data={"csrf": token(reviewer)})
    reviewer.post(f"{base}/undo", data={"csrf": token(reviewer)})
    assert db.one("SELECT status FROM claims WHERE id = ?", (claim["id"],))["status"] == "proposed"
    reviewer.post(f"{base}/redo", data={"csrf": token(reviewer)})
    assert db.one("SELECT status FROM claims WHERE id = ?", (claim["id"],))["status"] == "approved"
    assert not pipeline.redo(claim["id"])


def test_a_new_change_clears_redo(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "Redo clears")
    claim = claims_where(pid, "type = 'decision'")[0]
    base = f"/claim/{claim['id']}"
    reviewer.post(f"{base}/approve", data={"csrf": token(reviewer)})
    reviewer.post(f"{base}/undo", data={"csrf": token(reviewer)})
    reviewer.post(f"{base}/reject", data={"csrf": token(reviewer)})
    assert not pipeline.redo(claim["id"])
    page = reviewer.get(f"/claim/{claim['id']}/history").text
    assert "Undone" not in page


def test_undone_versions_are_labelled_in_the_history(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "History label")
    claim = claims_where(pid, "type = 'decision'")[0]
    reviewer.post(f"/claim/{claim['id']}/approve", data={"csrf": token(reviewer)})
    reviewer.post(f"/claim/{claim['id']}/undo", data={"csrf": token(reviewer)})
    assert "Undone" in reviewer.get(f"/claim/{claim['id']}/history").text


def test_old_databases_are_upgraded_in_place(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    connection = sqlite3.connect(old)
    connection.executescript(
        "CREATE TABLE claims (id INTEGER PRIMARY KEY, project_id INTEGER, source_id INTEGER, type TEXT, statement TEXT,"
        " quote TEXT, grade TEXT, status TEXT, access_rank INTEGER, note TEXT, created_at TEXT, updated_at TEXT);"
        "CREATE TABLE claim_versions (id INTEGER PRIMARY KEY, claim_id INTEGER, snapshot TEXT, action TEXT, by_user TEXT, at TEXT);"
    )
    connection.close()
    monkeypatch.setattr(db, "DB_PATH", str(old))
    db.init_db()
    db.init_db()
    assert {"owner", "area"} <= {row["name"] for row in db.query("SELECT name FROM pragma_table_info('claims')")}
    assert "undone" in {row["name"] for row in db.query("SELECT name FROM pragma_table_info('claim_versions')")}


def test_search_respects_visibility_and_escapes_wildcards(clients, shared_demo):
    reviewer, successor = clients
    assert "vendor contract" in reviewer.get(f"/project/{shared_demo}/search?q=vendor").text
    assert "vendor contract" not in successor.get(f"/project/{shared_demo}/search?q=vendor").text
    assert "vendor contract" not in reviewer.get(f"/project/{shared_demo}/search?q=vendor&preview=successor").text
    assert "Type at least two letters" in successor.get(f"/project/{shared_demo}/search?q=a").text
    assert "Nothing matches" in reviewer.get(f"/project/{shared_demo}/search?q=%25%25").text
    assert pipeline.search_claims(shared_demo, "100%", 2, False) == []


def test_search_hides_unapproved_claims_from_the_successor(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Unapproved")
    approve_all(reviewer, pid)
    share(reviewer, pid)
    found = "because audits are open"
    assert found in successor.get(f"/project/{pid}/search?q=pause refunds").text
    db.run("UPDATE claims SET status = 'proposed' WHERE project_id = ? AND statement LIKE '%pause refunds%'", (pid,))
    assert found not in successor.get(f"/project/{pid}/search?q=pause refunds").text
    assert found in reviewer.get(f"/project/{pid}/search?q=pause refunds").text


def test_unfinished_work_comes_from_status_columns_and_sentences():
    row = {"task": "Report", "owner": "Sam", "status": "In progress", "due": "2026-12-01", "note": ""}
    assert [c["type"] for c in pipeline.csv_claims(row, "line")] == ["responsibility", "unfinished"]
    assert [c["type"] for c in pipeline.csv_claims(dict(row, status="Done"), "line")] == ["responsibility"]
    assert [c["type"] for c in pipeline.csv_claims(dict(row, status="Blocked", note="Waiting"), "line")] == ["responsibility", "blocker"]
    assert pipeline.classify("Priya is still working on the poster designs.") == "unfinished"
    assert pipeline.classify("The migration is half finished.") == "unfinished"


def test_unfinished_work_shows_in_the_plan(clients, shared_demo):
    _, successor = clients
    page = successor.get(f"/project/{shared_demo}/plan").text
    assert "Unfinished work" in page and "is not finished: In progress" in page


def test_knowledge_map_ranks_owners_by_areas(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    people = pipeline.knowledge_map(pid)
    assert people[0]["name"] == "Rahul" and people[0]["count"] == 3 and people[0]["at_risk"]
    assert all(not person["at_risk"] for person in people[1:])
    assert "May be a single point of failure" in reviewer.get(f"/project/{pid}/questions").text


def test_knowledge_map_ignores_rejected_claims(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    for claim in claims_where(pid, "owner = 'Rahul'"):
        reviewer.post(f"/claim/{claim['id']}/reject", data={"csrf": token(reviewer)})
    assert "Rahul" not in [person["name"] for person in pipeline.knowledge_map(pid)]


def test_recurring_problems_group_repeats_across_files(clients, shared_demo):
    reviewer, successor = clients
    terms = [group["term"] for group in pipeline.recurring_problems(shared_demo)]
    assert "email server" in terms
    assert all(len({c["filename"] for c in g["claims"]}) > 1 for g in pipeline.recurring_problems(shared_demo))
    assert "Problems that keep coming up" in successor.get(f"/project/{shared_demo}/plan").text


def test_recurring_problems_need_more_than_one_file():
    pid = db.run("INSERT INTO projects(name, created_by, created_at) VALUES ('One file', 'test', '2026-01-01')")
    pipeline.add_source(pid, "only.md", "notes", 1, b"The upload queue might fail overnight. The upload queue fails when it is busy.")
    pipeline.analyse(pid, "test")
    assert pipeline.recurring_problems(pid) == []


def test_rehearsal_scores_improve_as_claims_are_approved(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    before = pipeline.rehearsal(pid)
    approve_all(reviewer, pid)
    after = pipeline.rehearsal(pid)
    assert after["score"] > before["score"]
    reasons = {item["reason"] for item in after["questions"] if not item["answered"]}
    assert "Hidden from the successor" in reasons and "Not approved yet" in reasons
    assert "Not approved yet" in {item["reason"] for item in before["questions"]}


def test_rehearsal_questions_become_answerable_with_testimony(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    approve_all(reviewer, pid)
    gap = claims_where(pid, "grade = 'Unknown' AND statement LIKE 'No owner%'")[0]
    asked = lambda: next(q for q in pipeline.rehearsal(pid)["questions"] if "Event budget report" in q["question"])
    assert not asked()["answered"]
    reviewer.post(f"/claim/{gap['id']}/answer", data={"csrf": token(reviewer), "text": "Asha does.", "who": "Priya"})
    reviewer.post(f"/claim/{gap['id']}/approve", data={"csrf": token(reviewer)})
    assert asked()["answered"]
    assert "Who owns Event budget report? Answer: Asha does." in db.one("SELECT statement FROM claims WHERE id = ?", (gap["id"],))["statement"]


def test_open_questions_can_be_answered_and_then_count_as_answered(clients):
    reviewer, _ = clients
    pid = demo_project(reviewer)
    approve_all(reviewer, pid)
    question = claims_where(pid, "type = 'open_question'")[0]
    asked = lambda: next(q for q in pipeline.rehearsal(pid)["questions"] if q["question"] == question["statement"])
    assert asked()["reason"] == "Nobody has answered this"
    reviewer.post(f"/claim/{question['id']}/answer", data={"csrf": token(reviewer), "text": "The treasurer.", "who": "Priya"})
    reviewer.post(f"/claim/{question['id']}/approve", data={"csrf": token(reviewer)})
    assert next(q for q in pipeline.rehearsal(pid)["questions"] if "The treasurer." in q["question"])["answered"]


def test_rehearsal_page_is_reviewer_only(clients, shared_demo):
    reviewer, successor = clients
    assert "can be answered" in reviewer.get(f"/project/{shared_demo}/rehearsal").text
    assert successor.get(f"/project/{shared_demo}/rehearsal").status_code == 403
    assert "Readiness check" in reviewer.get(f"/project/{shared_demo}/share").text


def test_self_check_finds_every_planted_problem_and_cleans_up():
    before = len(db.query("SELECT id FROM projects"))
    for key in pipeline.DEMOS:
        result = pipeline.evaluate(key)
        assert result["quotes"][0] == result["quotes"][1] > 0
        assert all(found for _, found in result["gaps"] + result["conflicts"])
        assert result["leaks"] == [] and result["exposed"] == []
        assert result["rehearsal"] > 0
    assert len(db.query("SELECT id FROM projects")) == before


def test_self_check_page_runs_on_request_only(clients):
    reviewer, successor = clients
    assert "Planted gap found" not in reviewer.get("/evaluation").text
    assert "Planted gap found" in reviewer.post("/evaluation", data={"csrf": token(reviewer)}).text
    assert successor.get("/evaluation").status_code == 403


def unread(client):
    match = re.search(r"Notifications, (\d+) unread", client.get("/workspace").text)
    return int(match.group(1))


def test_notifications_reach_the_right_people(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Notify")
    approve_all(reviewer, pid)
    before_successor, before_reviewer = unread(successor), unread(reviewer)
    share(reviewer, pid)
    assert unread(successor) == before_successor + 1
    assert unread(reviewer) == before_reviewer
    successor.post(f"/project/{pid}/acknowledge", data={"csrf": token(successor)})
    assert unread(reviewer) == before_reviewer + 1
    page = successor.get("/notifications").text
    assert "assigned Notify exclusively" in page and "confirmed they have read" not in page
    successor.post("/notifications/read", data={"csrf": token(successor)})
    assert unread(successor) == 0 and unread(reviewer) == before_reviewer + 1


def test_sent_back_actions_and_replies_notify(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Notify actions")
    approve_all(reviewer, pid)
    share(reviewer, pid)
    action = claims_where(pid, "type = 'next_action'")[0]
    before = unread(reviewer)
    successor.post(f"/project/{pid}/action/{action['id']}/unclear", data={"csrf": token(successor), "note": "What report?"})
    assert unread(reviewer) == before + 1
    mine = unread(successor)
    row = db.one("SELECT id FROM tracker WHERE claim_id = ?", (action["id"],))
    reviewer.post(f"/tracker/{row['id']}/answer", data={"csrf": token(reviewer), "reply": "The billing one."})
    assert unread(successor) == mine + 1
    revoked = db.one("SELECT id FROM shares WHERE project_id = ?", (pid,))
    reviewer.post(f"/share/{revoked['id']}/revoke", data={"csrf": token(reviewer)})
    assert unread(successor) == mine + 2


def test_word_and_xml_downloads_follow_visibility(clients, shared_demo):
    reviewer, successor = clients
    document = Document(io.BytesIO(successor.get(f"/project/{shared_demo}/export.docx").content))
    text = " ".join(paragraph.text for paragraph in document.paragraphs)
    assert "Project state" in text and "vendor contract" not in text
    assert "vendor contract" in " ".join(p.text for p in Document(io.BytesIO(reviewer.get(f"/project/{shared_demo}/export.docx").content)).paragraphs)
    tree = ET.fromstring(successor.get(f"/project/{shared_demo}/export.xml").text)
    assert tree.tag == "handover" and len(tree) > 5
    assert all(child.find("statement") is not None for child in tree)
    assert "vendor contract" not in ET.tostring(tree, encoding="unicode")


def test_xml_and_word_exports_survive_awkward_text():
    row = {"type": "risk", "statement": 'A <b> & "quote"\x00', "grade": "Backed", "quote": "", "source": "a&b.md",
           "note": "n", "section": "Risks & more"}
    tree = ET.fromstring(exports.to_xml([row], 'Name "x" <y>'))
    assert tree.attrib["project"] == 'Name "x" <y>'
    assert tree[0].find("statement").text == 'A <b> & "quote"'
    Document(io.BytesIO(exports.to_docx([row], "Title\x0b")))


def test_json_download_keeps_its_original_shape(clients, shared_demo):
    reviewer, _ = clients
    first = reviewer.get(f"/project/{shared_demo}/export.json").json()[0]
    assert set(first) == {"type", "statement", "grade", "quote", "source", "note"}
