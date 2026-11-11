import io
import re

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import db
import exports
import llm
import pipeline
from app import app, hash_password
from test_core import claims_where, sign_in, token

NOTES = (
    b"Priya owns the billing report.\n"
    b"We decided to pause refunds because audits are open.\n"
    b"The refund queue is blocked until 2026-12-01.\n"
    b"Sam needs to send the report before 2026-12-08.\n"
    b"Contact Priya if the billing report is unclear.\n"
)
BOARD = b"task,owner,status,due,note\nBilling report,Sam,In progress,2026-12-10,\n"
SECRET = b"We decided to drop the legacy vendor because fees doubled on 2026-12-05.\n"


def upload(client, pid, name, content, level):
    client.post(
        f"/project/{pid}/connect",
        data={"csrf": token(client), "source_type": "notes", "level": level},
        files={"file": (name, content, "text/plain")},
    )


def new_project(client, name="Small project"):
    response = client.post("/projects", data={"csrf": token(client), "name": name}, follow_redirects=False)
    pid = int(re.search(r"/project/(\d+)/connect", response.headers["location"]).group(1))
    for filename, content, level in (("notes.md", NOTES, 1), ("board.csv", BOARD, 1), ("secret.md", SECRET, 2)):
        upload(client, pid, filename, content, level)
    client.post(f"/project/{pid}/analyse", data={"csrf": token(client)})
    return pid


def approve_all(client, pid):
    for claim in claims_where(pid, "status = 'proposed'"):
        if claim["grade"] == "Unknown":
            continue
        action = "reject" if claim["grade"] == "Inferred" else "approve"
        client.post(f"/claim/{claim['id']}/{action}", data={"csrf": token(client), "reason": "Newer source."})


def resolve_for_share(client, pid):
    for claim in claims_where(pid, "status != 'rejected' AND (grade = 'Unknown' OR type = 'open_question')"):
        if claim["grade"] == "Unknown" or claim["type"] == "open_question":
            client.post(
                f"/claim/{claim['id']}/answer",
                data={"csrf": token(client), "text": "Confirmed with the person leaving.", "who": "Project owner"},
            )
    approve_all(client, pid)


def share(client, pid):
    resolve_for_share(client, pid)
    successor_id = db.one("SELECT id FROM users WHERE username = 'successor'")["id"]
    client.post(f"/project/{pid}/share", data={"csrf": token(client), "user_id": successor_id, "days": 7,
                                               "assignment_note": "Review and complete the remaining project actions."})


@pytest.fixture(scope="module")
def shared(clients):
    reviewer, _ = clients
    pid = new_project(reviewer)
    approve_all(reviewer, pid)
    share(reviewer, pid)
    return pid


def test_claim_date_prefers_the_claim_then_the_source_line():
    content = "[2026-01-02] Rahul: Rahul will test it.\nNo date here."
    assert pipeline.claim_date({"quote": "Rahul will test it.", "statement": "x"}, content) == "2026-01-02"
    assert pipeline.claim_date({"quote": "", "statement": "Due 2026-03-04."}, content) == "2026-03-04"
    assert pipeline.claim_date({"quote": "No date here.", "statement": "x"}, content) is None


def test_registration_creates_successor_group_with_roster(clients):
    with TestClient(app) as newcomer:
        page = newcomer.get("/register")
        assert page.status_code == 200 and "Register a successor team" in page.text
        password = "correct-horse-battery"
        response = newcomer.post(
            "/register",
            data={"csrf": token(newcomer, "/register"), "username": "new.successor", "display_name": "New Successor",
                  "team_name": "Build Club", "team_size": "3", "member_names": "Riya\nOmar", "job_title": "Developer",
                  "password": password, "confirm_password": password},
            follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["location"] == "/login"
        user = db.one("SELECT * FROM users WHERE username = 'new.successor'")
        assert user["role"] == "successor" and user["clearance"] == 1 and user["job_title"] == "Developer"
        assert user["password_hash"] != password and "$" in user["password_hash"]
        roster = db.query("SELECT name FROM team_members WHERE team_id = ? ORDER BY id", (user["team_id"],))
        assert [row["name"] for row in roster] == ["New Successor", "Riya", "Omar"]
        assert sign_in(newcomer, "new.successor", password).status_code == 303


def test_registration_rejects_invalid_and_duplicate_accounts():
    with TestClient(app) as newcomer:
        csrf = token(newcomer, "/register")
        response = newcomer.post(
            "/register", data={"csrf": csrf, "username": "x", "display_name": "X", "password": "short",
                               "team_name": "X team", "team_size": "1", "member_names": "", "job_title": "Other",
                               "confirm_password": "short"}, follow_redirects=False,
        )
        assert response.status_code == 303
        assert not db.one("SELECT id FROM users WHERE username = 'x'")

        data = {"csrf": csrf, "username": "registered.user", "display_name": "Registered User", "team_name": "Registered team",
                "team_size": "1", "member_names": "", "job_title": "Reviewer",
                "password": "a-secure-registration-password", "confirm_password": "a-secure-registration-password"}
        newcomer.post("/register", data=data, follow_redirects=False)
        duplicate = newcomer.post("/register", data=data, follow_redirects=False)
        assert duplicate.status_code == 303
        account = db.one("SELECT * FROM users WHERE username = 'registered.user'")
        assert db.one("SELECT COUNT(*) AS n FROM users WHERE username = 'registered.user'")["n"] == 1
        assert account["role"] == "successor" and account["job_title"] == "Reviewer"


def test_successor_requests_listed_project_and_reviewer_responds_with_feedback(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Directory test project")
    reviewer.post(
        f"/project/{pid}/opportunities",
        data={"csrf": token(reviewer), "enabled": "true", "public_summary": "A small portal needs its open tasks completed.",
              "public_scope": "Complete the portal’s remaining testing and documentation work.",
              "public_outcome": "A tested, documented portal handover."},
    )
    listing = successor.get("/opportunities").text
    assert "Directory test project" in listing and "A small portal needs its open tasks completed." in listing
    assert "legacy vendor" not in listing and "fees doubled" not in listing

    successor.post(f"/project/{pid}/request", data={"csrf": token(successor), "note": "We can help with testing."})
    request_row = db.one("SELECT * FROM project_requests WHERE project_id = ?", (pid,))
    assert request_row["status"] == "pending"
    assert not db.one("SELECT id FROM shares WHERE project_id = ? AND user_id = ? AND revoked = 0",
                      (pid, request_row["user_id"]))
    dashboard = reviewer.get("/teams").text
    assert "Requested projects — review incoming requests" in dashboard and "We can help with testing." in dashboard

    resolve_for_share(reviewer, pid)
    reviewer.post(
        f"/teams/request/{request_row['id']}",
        data={"csrf": token(reviewer, "/teams"), "decision": "approve", "feedback": "Start with the test suite; the main blocker is unverified billing behavior.", "days": 7},
    )
    assert db.one("SELECT status FROM project_requests WHERE id = ?", (request_row["id"],))["status"] == "approved"
    share_row = db.one("SELECT * FROM shares WHERE project_id = ? AND user_id = ? AND revoked = 0",
                       (pid, request_row["user_id"]))
    assert share_row
    my_team = successor.get("/my-team").text
    assert "Start with the test suite" in my_team
    plan = successor.get(f"/project/{pid}/plan").text
    assert "Start with the test suite" not in plan
    assert "fees doubled" not in plan


def test_successor_board_filters_and_searches_by_project_category(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Synthetic clinic scheduling handover")
    reviewer.post(
        f"/project/{pid}/opportunities",
        data={"csrf": token(reviewer), "enabled": "true", "category": "Healthcare",
              "public_summary": "Synthetic clinic referral and appointment handover.",
              "public_scope": "Complete the fictional clinic referral workflow checks.",
              "public_outcome": "A documented, checked referral handover."},
    )
    saved = db.one("SELECT category, listing_enabled FROM projects WHERE id = ?", (pid,))
    assert saved["category"] == "Healthcare" and saved["listing_enabled"] == 1

    all_projects = successor.get("/opportunities").text
    assert "Synthetic clinic scheduling handover" in all_projects and "Healthcare" in all_projects
    filtered = successor.get("/opportunities", params={"category": "Healthcare"}).text
    assert "Synthetic clinic scheduling handover" in filtered
    assert "Showing 1 of" in filtered
    searched = successor.get("/opportunities", params={"q": "clinic"}).text
    assert "Synthetic clinic scheduling handover" in searched
    assert "No projects match those filters" not in searched
    empty = successor.get("/opportunities", params={"category": "Cybersecurity", "q": "no such synthetic project"}).text
    assert "No projects match those filters" in empty


def test_successor_can_assign_shared_action_to_named_team_member(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "Team task assignment")
    action = claims_where(pid, "type = 'next_action'")[0]
    db.run("UPDATE claims SET status = 'approved' WHERE id = ?", (action["id"],))
    with TestClient(app) as teammate:
        password = "a-secure-team-password"
        teammate.post(
            "/register",
            data={"csrf": token(teammate, "/register"), "username": "task.team", "display_name": "Leader",
                  "team_name": "Task Team", "team_size": "2", "member_names": "Riya", "job_title": "Student",
                  "password": password, "confirm_password": password},
            follow_redirects=False,
        )
        account = db.one("SELECT * FROM users WHERE username = 'task.team'")
        sign_in(teammate, "task.team", password)
        db.run("INSERT INTO shares(project_id, user_id, expires_at, created_by, created_at) VALUES (?, ?, '2099-01-01 00:00:00', 'test', ?)",
               (pid, account["id"], db.now()))
        page = teammate.get(f"/project/{pid}/plan").text
        assert "Assigned team member" in page
        teammate.post(
            f"/project/{pid}/action/{action['id']}/assign-member",
            data={"csrf": token(teammate, f"/project/{pid}/plan"), "member_name": "Riya"},
        )
        tracker = db.one("SELECT * FROM tracker WHERE claim_id = ?", (action["id"],))
        assert tracker["assignee"] == "Riya"
        assert "Riya" in teammate.get("/my-team").text


def test_reviewer_can_create_demo_team_and_assign_a_reviewed_project(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "Directly assigned demo")
    resolve_for_share(reviewer, pid)
    reviewer.post(
        f"/project/{pid}/opportunities",
        data={"csrf": token(reviewer), "enabled": "true", "public_summary": "A demo project with unfinished billing tasks.",
              "public_scope": "Complete the billing workflow and document ownership.",
              "public_outcome": "A reviewed billing handover with assigned owners."},
    )
    password = "secure-reviewer-created-password"
    reviewer.post(
        "/teams/demo",
        data={"csrf": token(reviewer, "/teams"), "team_name": "Demo Reviewers", "display_name": "Demo Leader",
              "username": "demo.team", "password": password, "job_title": "Reviewer", "team_size": "2",
              "member_names": "Casey"},
    )
    account = db.one("SELECT * FROM users WHERE username = 'demo.team'")
    assert account["role"] == "successor" and account["job_title"] == "Reviewer"
    reviewer.post(
        "/teams/assign",
        data={"csrf": token(reviewer, "/teams"), "team_id": account["team_id"], "project_id": pid,
              "feedback": "Begin with the billing action; the unresolved blocker is the vendor confirmation.", "days": "14"},
    )
    assert db.one("SELECT status FROM project_requests WHERE project_id = ? AND team_id = ?", (pid, account["team_id"]))["status"] == "approved"
    assert db.one("SELECT id FROM shares WHERE project_id = ? AND user_id = ? AND revoked = 0", (pid, account["id"]))


def test_unknown_claim_cannot_be_approved_until_it_becomes_testimony(clients):
    reviewer, _ = clients
    response = reviewer.post("/projects/demo", data={"csrf": token(reviewer)}, follow_redirects=False)
    pid = int(re.search(r"/project/(\d+)/review", response.headers["location"]).group(1))
    claim = claims_where(pid, "grade = 'Unknown'")[0]
    reviewer.post(f"/claim/{claim['id']}/approve", data={"csrf": token(reviewer)})
    row = db.one("SELECT grade, status FROM claims WHERE id = ?", (claim["id"],))
    assert row["grade"] == "Unknown" and row["status"] == "proposed"
    page = reviewer.get(f"/project/{pid}/review").text
    assert "cannot be approved as fact" in page
    reviewer.post(
        f"/claim/{claim['id']}/answer",
        data={"csrf": token(reviewer), "text": "The owner chose the lower-cost option.", "who": "Project owner"},
    )
    reviewer.post(f"/claim/{claim['id']}/approve", data={"csrf": token(reviewer)})
    row = db.one("SELECT grade, status FROM claims WHERE id = ?", (claim["id"],))
    assert row["grade"] == "Testimony" and row["status"] == "approved"


def test_share_is_blocked_until_critical_rehearsal_questions_are_answered(clients):
    reviewer, _ = clients
    pid = db.run("INSERT INTO projects(name, created_by, created_at) VALUES ('Readiness gate', 'test', '2026-11-10')")
    source_id, _, _ = pipeline.add_source(pid, "question.md", "notes", 1, b"Who will approve the migration?\n")
    pipeline.analyse(pid, "test")
    question = claims_where(pid, "type = 'open_question'")[0]
    db.run("UPDATE claims SET status = 'approved' WHERE id = ?", (question["id"],))
    successor_id = db.one("SELECT id FROM users WHERE username = 'successor'")["id"]
    response = reviewer.post(
        f"/project/{pid}/share", data={"csrf": token(reviewer), "user_id": successor_id, "days": 7},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert not db.query("SELECT id FROM shares WHERE project_id = ?", (pid,))
    page = reviewer.get(f"/project/{pid}/share").text
    assert "Critical rehearsal questions answered" in page
    assert "review the rehearsal" in page


def test_timeline_is_ordered_and_hides_restricted_dates(clients, shared):
    reviewer, successor = clients
    page = successor.get(f"/project/{shared}/timeline").text
    assert page.index("2026-12-01") < page.index("2026-12-08") < page.index("2026-12-10")
    assert "2026-12-05" not in page and "legacy vendor" not in page
    assert "2026-12-05" in reviewer.get(f"/project/{shared}/timeline").text
    assert "2026-12-05" not in reviewer.get(f"/project/{shared}/timeline?preview=successor").text


def test_history_lists_every_version_of_a_claim(clients, shared):
    reviewer, _ = clients
    claim = claims_where(shared, "type = 'decision'")[0]
    reviewer.post(f"/claim/{claim['id']}/edit", data={"csrf": token(reviewer), "statement": "Reworded.", "quote": ""})
    page = reviewer.get(f"/claim/{claim['id']}/history").text
    assert "Edited" in page and "Approved" in page and "Found" in page and "Reworded." in page


def test_successor_can_tick_off_and_send_back_actions(clients, shared):
    reviewer, successor = clients
    action = claims_where(shared, "type = 'next_action' AND status = 'approved'")[0]
    done = f"/project/{shared}/action/{action['id']}/done"
    successor.post(done, data={"csrf": token(successor)})
    assert "Mark as not done" in successor.get(f"/project/{shared}/plan").text
    successor.post(done, data={"csrf": token(successor)})
    assert "Mark as done" in successor.get(f"/project/{shared}/plan").text
    successor.post(f"/project/{shared}/action/{action['id']}/unclear", data={"csrf": token(successor), "note": "Which report?"})
    assert "Which report?" in reviewer.get(f"/project/{shared}/share").text
    row = db.one("SELECT id FROM tracker WHERE claim_id = ?", (action["id"],))
    reviewer.post(f"/tracker/{row['id']}/answer", data={"csrf": token(reviewer), "reply": "The billing report."})
    assert "The billing report." in successor.get(f"/project/{shared}/plan").text


def test_action_tracker_refuses_everyone_else(clients, shared):
    reviewer, successor = clients
    action = claims_where(shared, "type = 'next_action'")[0]
    assert reviewer.post(f"/project/{shared}/action/{action['id']}/done", data={"csrf": token(reviewer)}).status_code == 404
    restricted = claims_where(shared, "access_rank = 2")[0]
    response = successor.post(f"/project/{shared}/action/{restricted['id']}/done", data={"csrf": token(successor)})
    assert response.status_code == 404


def test_exports_follow_the_same_visibility_as_the_plan(clients, shared):
    reviewer, successor = clients
    csv_text = successor.get(f"/project/{shared}/export.csv").text
    assert csv_text.startswith("type,statement,grade,quote,source,note")
    assert "legacy vendor" not in csv_text and "legacy vendor" in reviewer.get(f"/project/{shared}/export.csv").text
    book = load_workbook(io.BytesIO(successor.get(f"/project/{shared}/export.xlsx").content))
    assert book.sheetnames == ["Plan", "Summary"] and book["Plan"]["A1"].value == "type"
    assert "legacy vendor" not in " ".join(str(cell.value) for row in book["Plan"].iter_rows() for cell in row)


def test_exports_defuse_spreadsheet_formulas():
    assert exports.safe("=SUM(A1:A9)") == "'=SUM(A1:A9)"
    assert exports.safe("Plain text") == "Plain text"
    row = {"type": "risk", "statement": "=1+1", "grade": "Backed", "quote": "@x", "source": "a.md", "note": ""}
    assert "'=1+1" in exports.to_csv([row]) and "'@x" in exports.to_csv([row])


def test_replacing_a_file_flags_claims_whose_words_vanished(clients, shared):
    reviewer, _ = clients
    assert claims_where(shared, "type = 'blocker' AND status = 'approved'")
    upload(reviewer, shared, "notes.md", b"Priya owns the billing report.\nSam needs to send the report before 2026-12-08.\n", 1)
    assert len(db.query("SELECT id FROM sources WHERE project_id = ? AND filename = 'notes.md'", (shared,))) == 1
    stale = claims_where(shared, f"note = '{pipeline.DRIFT_NOTE}'")
    assert stale and all(c["status"] == "proposed" and c["grade"] == "Inferred" for c in stale)
    assert any("blocked" in c["statement"] for c in stale)
    kept = claims_where(shared, "statement LIKE '%Sam needs to send%' AND status = 'approved'")
    assert kept
    other = claims_where(shared, "access_rank = 2 AND status = 'approved'")
    assert other


def test_replacing_and_reanalysing_a_file_never_lowers_its_visibility(clients):
    reviewer, _ = clients
    pid = new_project(reviewer, "Visibility floor")
    upload(reviewer, pid, "board.csv", BOARD, 2)
    board = "source_id = (SELECT id FROM sources WHERE filename = 'board.csv' AND project_id = {})".format(pid)
    assert all(c["access_rank"] == 2 for c in claims_where(pid, board))
    upload(reviewer, pid, "board.csv", BOARD, 0)
    source = db.one("SELECT id, access_rank FROM sources WHERE project_id = ? AND filename = 'board.csv'", (pid,))
    assert source["access_rank"] == 2
    assert all(c["access_rank"] == 2 for c in claims_where(pid, board))
    reviewer.post(f"/project/{pid}/analyse", data={"csrf": token(reviewer)})
    source = db.one("SELECT access_rank FROM sources WHERE id = ?", (source["id"],))
    assert source["access_rank"] == 2
    assert all(c["access_rank"] == 2 for c in claims_where(pid, board))


def test_questions_are_written_in_plain_words():
    gap = {"statement": pipeline.REASON_GAP + "We chose Saturdays."}
    owner = {"statement": pipeline.OWNER_GAP + "Event budget report."}
    assert pipeline.question_for(gap) == "Why was this decided? We chose Saturdays."
    assert pipeline.question_for(owner) == "Who owns Event budget report?"
    assert pipeline.question_for({"statement": "Who approves the budget?"}) == "Who approves the budget?"


def test_dark_matter_finds_unowned_unexplained_phrases_only():
    pid = db.run("INSERT INTO projects(name, created_by, created_at) VALUES ('Terms', 'test', '2026-01-01')")
    first = b"The nimbus scheduler pauses overnight. Dana owns the nightly backup. The orbit dashboard is a tool for charts."
    second = b"Nobody has explained the nimbus scheduler yet. The nightly backup runs late. The orbit dashboard feeds the weekly report."
    pipeline.add_source(pid, "a.md", "notes", 1, first)
    pipeline.add_source(pid, "b.md", "notes", 1, second)
    pipeline.analyse(pid, "test")
    assert [item["term"] for item in pipeline.dark_matter(pid)] == ["nimbus scheduler"]


def test_questions_page_lists_gaps_and_terms(clients):
    reviewer, _ = clients
    pid = int(re.search(r"/project/(\d+)/", reviewer.post("/projects/demo", data={"csrf": token(reviewer)}, follow_redirects=False).headers["location"]).group(1))
    page = reviewer.get(f"/project/{pid}/questions").text
    assert "Who owns Event budget report?" in page and "Why was this decided?" in page
    assert "email server" in page


def test_club_demo_is_a_different_kind_of_project(clients):
    reviewer, _ = clients
    response = reviewer.post("/projects/demo", data={"csrf": token(reviewer), "kind": "club"}, follow_redirects=False)
    pid = int(re.search(r"/project/(\d+)/", response.headers["location"]).group(1))
    assert {"Backed", "Inferred", "Conflicting", "Unknown"} <= {c["grade"] for c in claims_where(pid, "1 = 1")}
    assert any("exhibition budget" in c["note"] for c in claims_where(pid, "grade = 'Conflicting'"))
    stored = " ".join(row["content"] for row in db.query("SELECT content FROM sources WHERE project_id = ?", (pid,)))
    assert "Frame#2026" not in stored and "sponsor.desk@" not in stored and "98123" not in stored
    assert reviewer.post("/projects/demo", data={"csrf": token(reviewer), "kind": "nope"}).status_code == 404


def test_deleting_a_project_removes_everything_in_it(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "To delete")
    approve_all(reviewer, pid)
    share(reviewer, pid)
    reviewer.post(f"/project/{pid}/delete", data={"csrf": token(reviewer)})
    for table in ("sources", "claims", "shares"):
        assert not db.query(f"SELECT id FROM {table} WHERE project_id = ?", (pid,))
    assert not db.query("SELECT id FROM projects WHERE id = ?", (pid,))
    assert successor.get(f"/project/{pid}/plan").status_code == 404
    assert successor.post(f"/project/{pid}/delete", data={"csrf": token(successor)}).status_code == 403


def test_ai_replies_are_parsed_defensively():
    reply = 'Here you go: [{"type": "risk", "statement": "A", "quote": "a"}, {"type": "bogus", "statement": "B"}, "text"] done'
    assert llm.parse_items(reply) == [{"type": "risk", "statement": "A", "quote": "a"}]
    assert llm.parse_items("no list here") is None
    assert llm.llm_extract("anything") is None



def test_project_assignment_is_exclusive_to_one_successor_group(clients):
    reviewer, successor = clients
    password = "another-secure-team-password"
    _, other_team_id = db.create_team_account(
        "exclusive.team", hash_password(password), "Other Lead", "Student", "Other Group", []
    )
    with TestClient(app) as other:
        sign_in(other, "exclusive.team", password)
        primary = db.one("SELECT * FROM users WHERE username = 'successor'")
        pid = new_project(reviewer, "Exclusive library project")
        reviewer.post(
            f"/project/{pid}/opportunities",
            data={"csrf": token(reviewer), "enabled": "true", "public_summary": "Synthetic work with one successor owner.",
                  "public_scope": "Complete the remaining testing and handover tasks.",
                  "public_outcome": "A tested and reviewed project handover."},
        )
        other.post(f"/project/{pid}/request", data={"csrf": token(other), "note": "We can help with testing."})
        competing = db.one("SELECT * FROM project_requests WHERE project_id = ? AND team_id = ?", (pid, other_team_id))
        resolve_for_share(reviewer, pid)
        reviewer.post(
            "/teams/assign",
            data={"csrf": token(reviewer, "/teams"), "team_id": primary["team_id"], "project_id": pid,
                  "feedback": "Start with the testing plan and record any remaining blocker.", "days": "14"},
        )
        assignment = db.one("SELECT * FROM project_assignments WHERE project_id = ?", (pid,))
        assert assignment["team_id"] == primary["team_id"] and assignment["state"] == "active"
        assert db.one("SELECT COUNT(*) AS n FROM shares WHERE project_id = ? AND revoked = 0", (pid,))["n"] == 1
        assert db.one("SELECT status FROM project_requests WHERE id = ?", (competing["id"],))["status"] == "declined"
        board = other.get("/opportunities").text
        assert "In progress — assigned to another team" in board
        assert f'action="/project/{pid}/request"' not in board
        other.post(f"/project/{pid}/request", data={"csrf": token(other), "note": "Please give us access."})
        assert db.one("SELECT COUNT(*) AS n FROM shares WHERE project_id = ? AND revoked = 0", (pid,))["n"] == 1
        assert other.get(f"/project/{pid}/plan").status_code == 200
        assert "Sam needs to send the report" not in other.get(f"/project/{pid}/plan").text


def test_successor_completion_requires_done_actions_and_reviewer_decision(clients):
    reviewer, successor = clients
    pid = new_project(reviewer, "Completion review project")
    reviewer.post(
        f"/project/{pid}/opportunities",
        data={"csrf": token(reviewer), "enabled": "true", "public_summary": "Synthetic billing handover with unfinished actions.",
              "public_scope": "Complete the documented billing tasks and confirm their owners.",
              "public_outcome": "A checked billing handover and an explicit completion report."},
    )
    resolve_for_share(reviewer, pid)
    share(reviewer, pid)
    actions = claims_where(pid, "type = 'next_action' AND status = 'approved' AND access_rank <= 1")
    assert actions, "The test project should include at least one plan action."
    summary = "We completed the listed billing actions, checked the source evidence, and documented remaining limitations."
    early = successor.post(f"/project/{pid}/submit", data={"csrf": token(successor), "summary": summary}, follow_redirects=False)
    assert early.status_code == 303 and not db.query("SELECT id FROM successor_submissions WHERE project_id = ?", (pid,))
    for action in actions:
        successor.post(f"/project/{pid}/action/{action['id']}/done", data={"csrf": token(successor, f"/project/{pid}/plan")})
    successor.post(f"/project/{pid}/submit", data={"csrf": token(successor, f"/project/{pid}/plan"), "summary": summary})
    submission = db.one("SELECT * FROM successor_submissions WHERE project_id = ?", (pid,))
    assert submission["status"] == "submitted"
    assert "Successor work submitted" in reviewer.get("/teams").text
    reviewer.post(
        f"/submissions/{submission['id']}/review",
        data={"csrf": token(reviewer, "/teams"), "decision": "changes", "feedback": "Please clarify how the last exception was verified."},
    )
    assert db.one("SELECT status FROM successor_submissions WHERE id = ?", (submission["id"],))["status"] == "changes_requested"
    assert "Please clarify how the last exception was verified" in successor.get("/my-team").text
    successor.post(f"/project/{pid}/submit", data={"csrf": token(successor, f"/project/{pid}/plan"), "summary": summary + " Exception checks are now documented."})
    reviewer.post(
        f"/submissions/{submission['id']}/review",
        data={"csrf": token(reviewer, "/teams"), "decision": "accept", "feedback": "Reviewed the completion report and accepted the handover."},
    )
    assert db.one("SELECT state FROM project_assignments WHERE project_id = ?", (pid,))["state"] == "completed"
    assert "Completed — reviewer accepted successor work" in successor.get("/opportunities").text
    assert "Reviewed the completion report" in reviewer.get("/teams").text
