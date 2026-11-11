import json
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import exports
import pipeline
from db import create_project_share, create_team_account, init_db, log, notify, now, one, query, run, unread_count, user_ids
from security import SecurityHeaders, hash_password, record_attempt, too_many_attempts, verify_password

BASE = Path(__file__).parent
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
MAX_BYTES = 200_000
JOB_TITLES = ("Developer", "Student", "Reviewer", "Volunteer", "Other")
TABS = {"attention": "proposed", "approved": "approved", "rejected": "rejected", "all": None}
GRADE_ORDER = ["Conflicting", "Inferred", "Unknown", "Testimony", "Backed"]


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Handover", lifespan=lifespan)
app.add_middleware(SecurityHeaders)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    session_cookie="handover_session",
    same_site="lax",
    max_age=8 * 3600,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def current_user(request):
    uid = request.session.get("uid")
    return one("SELECT * FROM users WHERE id = ?", (uid,)) if uid else None


def csrf_token(request):
    return request.session.setdefault("csrf", secrets.token_hex(16))


def flash(request, message, kind="ok"):
    request.session["flash"] = request.session.get("flash", []) + [[kind, message]]


def render(request, name, status_code=200, **context):
    user = current_user(request)
    context.update(
        user=user,
        unread=unread_count(user["id"]) if user else 0,
        path=request.url.path,
        csrf=csrf_token(request),
        flashes=request.session.pop("flash", []),
        labels=pipeline.TYPE_LABELS,
        grade_help=pipeline.GRADE_HELP,
        levels=pipeline.LEVELS,
        job_titles=JOB_TITLES,
        tour_prompt=bool(request.session.get("tour_prompt")),
        start_tour=bool(request.session.pop("start_tour", False)),
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)


async def csrf_check(request: Request, csrf: str = Form("")):
    if not secrets.compare_digest(csrf, request.session.get("csrf", "")):
        raise HTTPException(403, "This form expired. Go back, refresh the page and try again.")


def login_required(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(303, headers={"Location": "/login"})
    return user


def reviewer_required(user=Depends(login_required)):
    if user["role"] != "reviewer":
        raise HTTPException(403, "Only reviewers can do this.")
    return user


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return render(request, "error.html", status_code=exc.status_code, code=exc.status_code, message=exc.detail)


def project_or_404(project_id):
    project = one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "That project does not exist.")
    return project


def claim_or_404(claim_id):
    claim = one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    if not claim:
        raise HTTPException(404, "That claim does not exist.")
    return claim


def stats(project_id):
    row = one(
        "SELECT (SELECT COUNT(*) FROM sources WHERE project_id = :p) AS sources,"
        " (SELECT COUNT(*) FROM claims WHERE project_id = :p) AS claims,"
        " (SELECT COUNT(*) FROM claims WHERE project_id = :p AND status = 'proposed') AS proposed,"
        " (SELECT COUNT(*) FROM claims WHERE project_id = :p AND status = 'approved') AS approved,"
        " (SELECT COUNT(*) FROM shares WHERE project_id = :p AND revoked = 0) AS shared",
        {"p": project_id},
    )
    return dict(row)


def share_gate_message(project_id):
    info = stats(project_id)
    if info["proposed"] or not info["approved"]:
        return "Review every claim and approve at least one before sharing."
    rehearsal = pipeline.rehearsal(project_id)
    blockers = [q for q in rehearsal["questions"] if not q["answered"] and q["reason"] != "Hidden from the successor"]
    if blockers:
        return f"Sharing is blocked: {len(blockers)} critical rehearsal question(s) remain unanswered."
    return ""


def project_page(request, template, project_id, step, **context):
    return render(request, template, project=project_or_404(project_id), stats=stats(project_id), step=step, **context)


def project_is_incomplete(project_id):
    return bool(one(
        "SELECT 1 FROM claims WHERE project_id = ? AND status != 'rejected' "
        "AND (status = 'proposed' OR grade = 'Unknown' OR type IN ('unfinished', 'blocker') "
        "OR (type IN ('open_question', 'gap') AND instr(statement, 'Answer:') = 0)) LIMIT 1",
        (project_id,),
    ))


def team_for_user(user):
    return one("SELECT * FROM teams WHERE id = ?", (user["team_id"],)) if user["team_id"] else None


def grant_team_project(project_id, team_id, days, reviewer_name):
    leader = one("SELECT * FROM users WHERE team_id = ? AND role = 'successor' ORDER BY id LIMIT 1", (team_id,))
    if not leader:
        raise HTTPException(404, "That team has no successor login.")
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    share_id = create_project_share(project_id, team_id, leader["id"], expires, reviewer_name)
    return (leader, share_id) if share_id else None


def project_assignment(project_id):
    return one(
        "SELECT pa.*, t.name AS team_name, u.display_name AS leader_name, s.expires_at, s.revoked, "
        "ss.status AS submission_status, ss.summary AS submission_summary, ss.reviewer_feedback "
        "FROM project_assignments pa JOIN teams t ON t.id = pa.team_id "
        "JOIN users u ON u.id = pa.user_id LEFT JOIN shares s ON s.id = pa.share_id "
        "LEFT JOIN successor_submissions ss ON ss.share_id = pa.share_id WHERE pa.project_id = ?",
        (project_id,),
    )


def active_assignment(project_id):
    assignment = project_assignment(project_id)
    if (assignment and assignment["state"] == "active" and assignment["revoked"] == 0
            and assignment["expires_at"] and assignment["expires_at"] > now()):
        return assignment
    return None


def close_other_pending_requests(project_id, winning_team_id, reviewer_name):
    others = query(
        "SELECT id, user_id, team_id FROM project_requests WHERE project_id = ? AND team_id != ? AND status = 'pending'",
        (project_id, winning_team_id),
    )
    feedback = "This project was assigned exclusively to another successor team. You can browse the library for other work."
    for item in others:
        run("UPDATE project_requests SET status = 'declined', reviewer_feedback = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (feedback, reviewer_name, now(), item["id"]))
        notify([item["user_id"]], feedback, "/my-team")


def active_share(project_id, user_id):
    return one(
        "SELECT * FROM shares WHERE project_id = ? AND user_id = ? AND revoked = 0 AND expires_at > ?"
        " ORDER BY id DESC",
        (project_id, user_id, now()),
    )


def back_to_review(claim, tab):
    tab = tab if tab in TABS else "attention"
    return RedirectResponse(f"/project/{claim['project_id']}/review?tab={tab}#claim-{claim['id']}", 303)


@app.get("/")
def home(request: Request):
    current = datetime.now()
    meeting_notes_date = f"{current.day} {current:%B %Y}"
    return render(request, "hero.html", meeting_notes_date=meeting_notes_date, meeting_notes_iso=current.strftime("%Y-%m-%d"))


@app.get("/help")
def help_page(request: Request):
    return render(request, "help.html")


@app.get("/login")
def login_form(request: Request):
    if current_user(request):
        return RedirectResponse("/workspace", 303)
    return render(request, "login.html")


@app.get("/register")
def register_form(request: Request):
    if current_user(request):
        return RedirectResponse("/workspace", 303)
    return render(request, "register.html")


@app.post("/register", dependencies=[Depends(csrf_check)])
def register(request: Request, username: str = Form(""), display_name: str = Form(""),
             password: str = Form(""), confirm_password: str = Form(""), team_name: str = Form(""),
             team_size: int = Form(0), member_names: str = Form(""), job_title: str = Form("Other")):
    if current_user(request):
        return RedirectResponse("/workspace", 303)
    address = request.client.host if request.client else "unknown"
    rate_key = f"register:{address}"
    if too_many_attempts(rate_key):
        flash(request, "Too many registration attempts. Please wait a minute and try again.", "error")
        return RedirectResponse("/register", 303)
    record_attempt(rate_key)

    username = username.strip().lower()
    display_name = display_name.strip()[:60]
    team_name = team_name.strip()[:80]
    members = [name.strip()[:60] for name in member_names.splitlines() if name.strip()]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,29}", username):
        flash(request, "Username must be 3–30 characters: letters, numbers, dot, underscore or hyphen.", "error")
        return RedirectResponse("/register", 303)
    if not display_name:
        flash(request, "Enter the name you want reviewers to see.", "error")
        return RedirectResponse("/register", 303)
    if not team_name or job_title not in JOB_TITLES or not 1 <= team_size <= 12:
        flash(request, "Enter a team name, choose a job category, and set a team size from 1 to 12.", "error")
        return RedirectResponse("/register", 303)
    if len(members) != team_size - 1 or len({name.casefold() for name in [display_name, *members]}) != team_size:
        flash(request, "Enter exactly one name for each additional teammate; team size includes you.", "error")
        return RedirectResponse("/register", 303)
    if len(password) < 12 or len(password) > 128:
        flash(request, "Choose a password between 12 and 128 characters.", "error")
        return RedirectResponse("/register", 303)
    if password != confirm_password:
        flash(request, "The passwords do not match.", "error")
        return RedirectResponse("/register", 303)
    try:
        user_id, team_id = create_team_account(
            username, hash_password(password), display_name, job_title, team_name, members
        )
    except sqlite3.IntegrityError:
        flash(request, "That username is already in use. Choose another.", "error")
        return RedirectResponse("/register", 303)
    log(display_name, "registered successor team", f"{team_name} (#{team_id}, {team_size} members)")
    flash(request, "Your team account is ready. Sign in; a reviewer must assign or share a project before you can see its contents.")
    return RedirectResponse("/login", 303)


@app.post("/login", dependencies=[Depends(csrf_check)])
def login(request: Request, username: str = Form(""), password: str = Form("")):
    key = f"{request.client.host if request.client else 'unknown'}:{username.lower()}"
    user = None if too_many_attempts(key) else one("SELECT * FROM users WHERE username = ?", (username.strip().lower(),))
    if not user or not verify_password(password, user["password_hash"]):
        record_attempt(key)
        log(username[:40], "login failed")
        flash(request, "That username or password is not right. After five tries you must wait a minute.", "error")
        return RedirectResponse("/login", 303)
    request.session.clear()
    request.session["uid"] = user["id"]
    if user["tour_choice"]:
        request.session.pop("tour_prompt", None)
    else:
        request.session["tour_prompt"] = True
    log(user["display_name"], "signed in")
    return RedirectResponse("/workspace", 303)


@app.post("/tour-choice", dependencies=[Depends(csrf_check)])
def save_tour_choice(request: Request, choice: str = Form("later"), do_not_ask_again: bool = Form(False),
                     user=Depends(login_required)):
    if choice not in {"start", "later"}:
        raise HTTPException(400, "Choose Start tour or Not now.")
    request.session.pop("tour_prompt", None)
    if choice == "start":
        run("UPDATE users SET tour_choice = 'started' WHERE id = ?", (user["id"],))
        request.session["start_tour"] = True
        destination = "/workspace" if user["role"] == "reviewer" else "/opportunities"
    else:
        if do_not_ask_again:
            run("UPDATE users SET tour_choice = 'dismissed' WHERE id = ?", (user["id"],))
        destination = "/workspace"
    return RedirectResponse(destination, 303)


@app.post("/logout", dependencies=[Depends(csrf_check)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


@app.get("/workspace")
def workspace(request: Request, user=Depends(login_required)):
    if user["role"] == "reviewer":
        projects = query(
            "SELECT p.*, (SELECT COUNT(*) FROM claims WHERE project_id = p.id) AS claims,"
            " (SELECT COUNT(*) FROM claims WHERE project_id = p.id AND status = 'approved') AS approved"
            " FROM projects p ORDER BY p.id DESC"
        )
    else:
        projects = query(
            "SELECT DISTINCT p.*, 0 AS claims, 0 AS approved FROM projects p JOIN shares s ON s.project_id = p.id"
            " WHERE s.user_id = ? AND s.revoked = 0 AND s.expires_at > ? ORDER BY p.id DESC",
            (user["id"], now()),
        )
    return render(request, "workspace.html", projects=projects, demos=pipeline.DEMOS)


@app.get("/opportunities")
def opportunities(request: Request, category: str = "", q: str = "", user=Depends(login_required)):
    if user["role"] != "successor":
        return RedirectResponse("/teams", 303)
    team = team_for_user(user)
    projects = [dict(row) for row in query(
        "SELECT p.*, (SELECT COUNT(*) FROM claims c WHERE c.project_id = p.id AND c.status != 'rejected' "
        "AND (c.status = 'proposed' OR c.grade = 'Unknown' OR c.type IN ('unfinished','blocker') "
        "OR (c.type IN ('open_question','gap') AND instr(c.statement, 'Answer:') = 0))) AS open_items, "
        "(SELECT COUNT(*) FROM claims c WHERE c.project_id = p.id AND c.status = 'approved') AS approved_items, "
        "(SELECT COUNT(*) FROM claims c WHERE c.project_id = p.id AND c.status = 'approved' "
        "AND c.type = 'next_action' AND c.access_rank <= 1) AS action_items "
        "FROM projects p WHERE p.listing_enabled = 1 ORDER BY p.name COLLATE NOCASE"
    )]
    total_projects = len(projects)
    has_projects = bool(projects)
    selected_category = category if category in pipeline.PROJECT_CATEGORIES else ""
    search_text = q.strip()[:100]
    requests = query(
        "SELECT * FROM project_requests WHERE team_id = ? ORDER BY requested_at DESC", (team["id"],)
    ) if team else []
    request_by_project = {r["project_id"]: r for r in requests}
    for project in projects:
        pid = project["id"]
        ownership = project_assignment(pid)
        active = active_assignment(pid)
        request_row = request_by_project.get(pid)
        project["assigned_to_team"] = bool(ownership and team and ownership["team_id"] == team["id"]
                                            and ownership["state"] in ("active", "completed"))
        project["team_share_active"] = bool(project["assigned_to_team"] and active_share(pid, user["id"]))
        project["assigned_elsewhere"] = bool(ownership and team and ownership["team_id"] != team["id"]
                                               and (ownership["state"] == "completed" or active))
        if ownership and ownership["state"] == "completed" or (ownership and ownership["submission_status"] == "accepted"):
            project["library_status"] = "Completed — reviewer accepted successor work"
            project["can_request"] = False
        elif ownership and ownership["submission_status"] == "submitted":
            project["library_status"] = "Successor work submitted — reviewer review pending"
            project["can_request"] = False
        elif ownership and ownership["submission_status"] == "changes_requested":
            project["library_status"] = "Reviewer requested changes"
            project["can_request"] = False
        elif active and active["team_id"] == (team["id"] if team else None):
            project["library_status"] = "In progress — assigned to your team"
            project["can_request"] = False
        elif active:
            project["library_status"] = "In progress — assigned to another team"
            project["can_request"] = False
        elif request_row and request_row["status"] == "pending":
            project["library_status"] = "Your request is awaiting reviewer decision"
            project["can_request"] = False
        elif request_row and request_row["status"] == "declined":
            project["library_status"] = "Request declined — see reviewer feedback in My team"
            project["can_request"] = bool(project_is_incomplete(pid))
        elif project_is_incomplete(pid):
            project["library_status"] = "Available to request — incomplete work remains"
            project["can_request"] = True
        else:
            project["library_status"] = "No open work currently listed for request"
            project["can_request"] = False
        project["action_done"] = 0
        if project["assigned_to_team"] and ownership:
            project["action_done"] = one(
                "SELECT COUNT(*) AS n FROM tracker WHERE share_id = ? AND state = 'done'", (ownership["share_id"],)
            )["n"]
    for pid, row in list(request_by_project.items()):
        if row["status"] == "approved" and not active_share(pid, user["id"]):
            request_by_project[pid] = dict(row) | {"status": "expired"}
    if selected_category:
        projects = [p for p in projects if p["category"] == selected_category]
    if search_text:
        term = search_text.casefold()
        projects = [p for p in projects if any(term in (p[key] or "").casefold()
                    for key in ("name", "public_summary", "public_scope", "public_skills", "public_outcome"))]
    return render(request, "opportunities.html", projects=projects, team=team, request_by_project=request_by_project,
                  categories=pipeline.PROJECT_CATEGORIES, selected_category=selected_category,
                  search_text=search_text, has_projects=has_projects, total_projects=total_projects)


@app.post("/project/{project_id}/request", dependencies=[Depends(csrf_check)])
def request_project(request: Request, project_id: int, note: str = Form(""), user=Depends(login_required)):
    if user["role"] != "successor":
        raise HTTPException(403, "Only successor teams can request a listed project.")
    project = project_or_404(project_id)
    team = team_for_user(user)
    if not team or not project["listing_enabled"] or not project_is_incomplete(project_id):
        raise HTTPException(404, "That incomplete project is not available to pick.")
    ownership = project_assignment(project_id)
    if ownership and ownership["state"] == "completed":
        flash(request, "This project has been completed and reviewed; it is no longer available to request.")
        return RedirectResponse("/opportunities", 303)
    active = active_assignment(project_id)
    if active and active["team_id"] != team["id"]:
        flash(request, "This project is already assigned to another successor team.", "error")
        return RedirectResponse("/opportunities", 303)
    if active and active["team_id"] == team["id"]:
        flash(request, "Your team already has this project assigned.")
        return RedirectResponse("/my-team", 303)
    existing = one("SELECT * FROM project_requests WHERE project_id = ? AND team_id = ?", (project_id, team["id"]))
    if existing and existing["status"] == "approved" and active_share(project_id, user["id"]):
        flash(request, "Your team already has this project assigned.")
        return RedirectResponse("/my-team", 303)
    run(
        "INSERT INTO project_requests(project_id, team_id, user_id, status, request_note, requested_at) "
        "VALUES (?, ?, ?, 'pending', ?, ?) ON CONFLICT(project_id, team_id) DO UPDATE SET "
        "user_id=excluded.user_id, status='pending', request_note=excluded.request_note, reviewer_feedback='', "
        "requested_at=excluded.requested_at, reviewed_by='', reviewed_at=''",
        (project_id, team["id"], user["id"], note.strip()[:1000], now()),
    )
    reviewer_ids = user_ids("reviewer")
    notify(reviewer_ids, f"{team['name']} requested {project['name']}", "/teams")
    log(user["display_name"], "requested incomplete project", project["name"])
    flash(request, "Request sent. The reviewer will check the project and respond with feedback before sharing its contents.")
    return RedirectResponse("/my-team", 303)


@app.get("/my-team")
def my_team(request: Request, user=Depends(login_required)):
    if user["role"] != "successor":
        return RedirectResponse("/teams", 303)
    team = team_for_user(user)
    members = query("SELECT * FROM team_members WHERE team_id = ? ORDER BY id", (team["id"],)) if team else []
    requests = query(
        "SELECT r.*, p.name AS project_name, p.category, p.public_summary FROM project_requests r "
        "JOIN projects p ON p.id = r.project_id WHERE r.team_id = ? AND r.status != 'approved' "
        "ORDER BY r.requested_at DESC", (team["id"],)
    ) if team else []
    owned_projects = [dict(row) for row in query(
        "SELECT pa.*, p.name AS project_name, p.category, p.public_summary, p.public_scope, p.public_skills, "
        "p.public_outcome, s.expires_at, s.revoked, ss.status AS submission_status, ss.summary AS submission_summary, "
        "ss.reviewer_feedback, r.reviewer_feedback AS assignment_feedback FROM project_assignments pa "
        "JOIN projects p ON p.id = pa.project_id "
        "LEFT JOIN shares s ON s.id = pa.share_id LEFT JOIN successor_submissions ss ON ss.share_id = pa.share_id "
        "LEFT JOIN project_requests r ON r.project_id = pa.project_id AND r.team_id = pa.team_id "
        "WHERE pa.team_id = ? ORDER BY pa.assigned_at DESC", (team["id"],)
    )] if team else []
    assignments = query(
        "SELECT p.name AS project_name, c.statement, tr.assignee, tr.state FROM tracker tr "
        "JOIN shares s ON s.id = tr.share_id JOIN projects p ON p.id = s.project_id "
        "JOIN claims c ON c.id = tr.claim_id WHERE s.user_id = ? AND s.revoked = 0 AND s.expires_at > ? "
        "AND tr.assignee != '' ORDER BY p.name, c.id", (user["id"], now())
    )
    for project in owned_projects:
        project["access_active"] = bool(project["revoked"] == 0 and project["expires_at"]
                                         and project["expires_at"] > now())
    return render(request, "my_team.html", team=team, members=members, requests=requests,
                  owned_projects=owned_projects, assignments=assignments)


@app.post("/project/{project_id}/submit", dependencies=[Depends(csrf_check)])
def submit_successor_work(request: Request, project_id: int, summary: str = Form(""), user=Depends(login_required)):
    if user["role"] != "successor":
        raise HTTPException(403, "Only the assigned successor team can submit completed work.")
    team = team_for_user(user)
    assignment = project_assignment(project_id)
    share = active_share(project_id, user["id"])
    if (not team or not assignment or assignment["team_id"] != team["id"] or assignment["user_id"] != user["id"]
            or assignment["state"] != "active" or not share or share["id"] != assignment["share_id"]):
        raise HTTPException(403, "Only the team currently assigned to this project can submit work.")
    existing = one("SELECT * FROM successor_submissions WHERE share_id = ?", (share["id"],))
    if existing and existing["status"] in ("submitted", "accepted"):
        flash(request, "This completion has already been submitted or accepted.", "error")
        return RedirectResponse(f"/project/{project_id}/plan", 303)
    summary = summary.strip()[:1500]
    if len(summary) < 20:
        flash(request, "Write at least 20 characters describing what your team completed and what remains.", "error")
        return RedirectResponse(f"/project/{project_id}/plan", 303)
    total = one("SELECT COUNT(*) AS n FROM claims WHERE project_id = ? AND type = 'next_action' "
                "AND status = 'approved' AND access_rank <= ?", (project_id, user["clearance"]))["n"]
    done = one("SELECT COUNT(*) AS n FROM tracker tr JOIN claims c ON c.id = tr.claim_id "
               "WHERE tr.share_id = ? AND tr.state = 'done' AND c.type = 'next_action'", (share["id"],))["n"]
    if total and done < total:
        flash(request, f"Mark all plan actions done before submission ({done} of {total} marked done).", "error")
        return RedirectResponse(f"/project/{project_id}/plan", 303)
    unclear = one("SELECT COUNT(*) AS n FROM tracker WHERE share_id = ? AND state = 'unclear'", (share["id"],))["n"]
    if unclear:
        flash(request, f"Resolve the {unclear} item(s) you sent back before submitting completion.", "error")
        return RedirectResponse(f"/project/{project_id}/plan", 303)
    run(
        "INSERT INTO successor_submissions(project_id, team_id, user_id, share_id, status, summary, submitted_at) "
        "VALUES (?, ?, ?, ?, 'submitted', ?, ?) ON CONFLICT(share_id) DO UPDATE SET "
        "status='submitted', summary=excluded.summary, submitted_at=excluded.submitted_at, "
        "reviewer_feedback='', reviewed_by='', reviewed_at=''",
        (project_id, team["id"], user["id"], share["id"], summary, now()),
    )
    notify(user_ids("reviewer"), f"{team['name']} submitted completed work for {project_or_404(project_id)['name']} review.", "/teams")
    log(user["display_name"], "submitted successor work for review", f"project #{project_id}")
    flash(request, "Completion submitted. The reviewer will accept it or request changes with feedback.")
    return RedirectResponse("/my-team", 303)


@app.get("/teams")
def teams_page(request: Request, user=Depends(reviewer_required)):
    teams = query(
        "SELECT t.*, u.id AS user_id, u.username, u.display_name AS leader_name, u.job_title AS leader_job "
        "FROM teams t JOIN users u ON u.team_id = t.id AND u.role = 'successor' ORDER BY t.id DESC"
    )
    groups = []
    for team in teams:
        item = dict(team)
        item["members"] = query("SELECT * FROM team_members WHERE team_id = ? ORDER BY id", (team["id"],))
        groups.append(item)
    requests = query(
        "SELECT r.*, p.name AS project_name, p.category, p.public_summary, p.public_scope, p.public_skills, "
        "p.public_outcome, t.name AS team_name, u.display_name AS leader_name "
        "FROM project_requests r JOIN projects p ON p.id = r.project_id JOIN teams t ON t.id = r.team_id "
        "JOIN users u ON u.id = r.user_id WHERE r.status = 'pending' ORDER BY r.requested_at"
    )
    candidates = query(
        "SELECT p.* FROM projects p WHERE p.listing_enabled = 1 AND EXISTS (SELECT 1 FROM claims c "
        "WHERE c.project_id = p.id AND c.status != 'rejected' AND (c.status = 'proposed' OR c.grade = 'Unknown' "
        "OR c.type IN ('unfinished','blocker') OR (c.type IN ('open_question','gap') AND instr(c.statement, 'Answer:') = 0))) "
        "ORDER BY p.name"
    )
    projects = [p for p in candidates if not active_assignment(p["id"])
                and not (project_assignment(p["id"]) and project_assignment(p["id"])["state"] == "completed")]
    active_assignments = [dict(row) for row in query(
        "SELECT pa.*, p.name AS project_name, p.category, p.public_summary, t.name AS team_name, "
        "u.display_name AS leader_name, s.expires_at, ss.id AS submission_id, ss.status AS submission_status, "
        "ss.summary AS submission_summary, ss.submitted_at "
        "FROM project_assignments pa JOIN projects p ON p.id = pa.project_id JOIN teams t ON t.id = pa.team_id "
        "JOIN users u ON u.id = pa.user_id JOIN shares s ON s.id = pa.share_id "
        "LEFT JOIN successor_submissions ss ON ss.share_id = pa.share_id "
        "WHERE pa.state = 'active' AND s.revoked = 0 AND s.expires_at > ? ORDER BY s.expires_at, p.name", (now(),)
    )]
    for assignment in active_assignments:
        assignment["action_total"] = one(
            "SELECT COUNT(*) AS n FROM claims WHERE project_id = ? AND type = 'next_action' "
            "AND status = 'approved' AND access_rank <= 1", (assignment["project_id"],)
        )["n"]
        assignment["action_done"] = one(
            "SELECT COUNT(*) AS n FROM tracker WHERE share_id = ? AND state = 'done'", (assignment["share_id"],)
        )["n"]
    submissions = query(
        "SELECT ss.*, p.name AS project_name, p.category, p.public_summary, t.name AS team_name, "
        "u.display_name AS leader_name FROM successor_submissions ss JOIN projects p ON p.id = ss.project_id "
        "JOIN teams t ON t.id = ss.team_id JOIN users u ON u.id = ss.user_id "
        "WHERE ss.status = 'submitted' ORDER BY ss.submitted_at"
    )
    completed_assignments = query(
        "SELECT pa.*, p.name AS project_name, p.category, t.name AS team_name, u.display_name AS leader_name, "
        "ss.summary AS submission_summary, ss.reviewer_feedback, ss.reviewed_at "
        "FROM project_assignments pa JOIN projects p ON p.id = pa.project_id JOIN teams t ON t.id = pa.team_id "
        "JOIN users u ON u.id = pa.user_id LEFT JOIN successor_submissions ss ON ss.share_id = pa.share_id "
        "WHERE pa.state = 'completed' ORDER BY ss.reviewed_at DESC"
    )
    return render(request, "teams.html", groups=groups, requests=requests, projects=projects,
                  active_assignments=active_assignments, submissions=submissions,
                  completed_assignments=completed_assignments, demos=pipeline.DEMOS)


@app.post("/teams/demo", dependencies=[Depends(csrf_check)])
def create_demo_team(request: Request, team_name: str = Form(""), display_name: str = Form(""),
                     username: str = Form(""), password: str = Form(""), job_title: str = Form("Other"),
                     team_size: int = Form(0), member_names: str = Form(""), user=Depends(reviewer_required)):
    team_name, display_name = team_name.strip()[:80], display_name.strip()[:60]
    username = username.strip().lower()
    members = [n.strip()[:60] for n in member_names.splitlines() if n.strip()]
    if (not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,29}", username) or not team_name or not display_name
            or job_title not in JOB_TITLES or not 1 <= team_size <= 12 or len(members) != team_size - 1
            or len({n.casefold() for n in [display_name, *members]}) != team_size or len(password) < 12 or len(password) > 128):
        flash(request, "Check the team details, names, job category, username and 12–128 character password.", "error")
        return RedirectResponse("/teams", 303)
    try:
        new_user, team_id = create_team_account(username, hash_password(password), display_name,
                                                job_title, team_name, members)
    except sqlite3.IntegrityError:
        flash(request, "That username is already in use.", "error")
        return RedirectResponse("/teams", 303)
    log(user["display_name"], "created demo successor team", f"{team_name} (#{team_id})")
    flash(request, f"Created successor team {team_name} with login {username}. Share its credentials securely with the team.")
    return RedirectResponse("/teams", 303)


@app.post("/teams/assign", dependencies=[Depends(csrf_check)])
def assign_team_project(request: Request, team_id: int = Form(...), project_id: int = Form(...),
                        feedback: str = Form(""), days: int = Form(7), user=Depends(reviewer_required)):
    if days not in (7, 14, 30):
        raise HTTPException(400, "Choose a valid sharing period.")
    if not feedback.strip():
        flash(request, "Add feedback so the successor team understands the assignment.", "error")
        return RedirectResponse("/teams", 303)
    project = project_or_404(project_id)
    team = one("SELECT * FROM teams WHERE id = ?", (team_id,))
    if not team or not project_is_incomplete(project_id):
        flash(request, "Choose a team and an incomplete project.", "error")
        return RedirectResponse("/teams", 303)
    gate = share_gate_message(project_id)
    if gate:
        flash(request, gate + " Review the project before assigning it.", "error")
        return RedirectResponse("/teams", 303)
    ownership = project_assignment(project_id)
    if ownership and ownership["state"] == "completed" or active_assignment(project_id):
        flash(request, "This project already has an owner or has been completed. End its active assignment before assigning it again.", "error")
        return RedirectResponse("/teams", 303)
    granted = grant_team_project(project_id, team_id, days, user["display_name"])
    if not granted:
        flash(request, "Another team was assigned this project first. Refresh and review the active assignment.", "error")
        return RedirectResponse("/teams", 303)
    leader, share_id = granted
    run(
        "INSERT INTO project_requests(project_id, team_id, user_id, status, reviewer_feedback, requested_at, reviewed_by, reviewed_at) "
        "VALUES (?, ?, ?, 'approved', ?, ?, ?, ?) ON CONFLICT(project_id, team_id) DO UPDATE SET "
        "user_id=excluded.user_id, status='approved', reviewer_feedback=excluded.reviewer_feedback, "
        "reviewed_by=excluded.reviewed_by, reviewed_at=excluded.reviewed_at",
        (project_id, team_id, leader["id"], feedback.strip()[:3000], now(), user["display_name"], now()),
    )
    close_other_pending_requests(project_id, team_id, user["display_name"])
    notify([leader["id"]], f"{user['display_name']} assigned {project['name']} to {team['name']}", f"/project/{project_id}/plan")
    log(user["display_name"], "assigned project to successor team", f"{team['name']}: {project['name']}")
    flash(request, f"Assigned {project['name']} to {team['name']}.")
    return RedirectResponse("/teams", 303)


@app.post("/teams/request/{request_id}", dependencies=[Depends(csrf_check)])
def review_team_request(request: Request, request_id: int, decision: str = Form(""),
                        feedback: str = Form(""), days: int = Form(7), user=Depends(reviewer_required)):
    item = one("SELECT * FROM project_requests WHERE id = ?", (request_id,))
    if not item:
        raise HTTPException(404, "That request does not exist.")
    if item["status"] != "pending" or decision not in ("approve", "decline"):
        raise HTTPException(400, "Choose an active request and a valid decision.")
    if not feedback.strip():
        flash(request, "Add feedback so the team understands the review decision.", "error")
        return RedirectResponse("/teams", 303)
    project = project_or_404(item["project_id"])
    if decision == "approve":
        gate = share_gate_message(project["id"])
        if days not in (7, 14, 30) or not project_is_incomplete(project["id"]) or gate:
            if gate:
                flash(request, gate + " Resolve the review gate before approving the request.", "error")
                return RedirectResponse("/teams", 303)
            flash(request, "This project is no longer incomplete or the sharing period is invalid.", "error")
            return RedirectResponse("/teams", 303)
        ownership = project_assignment(project["id"])
        if ownership and ownership["state"] == "completed" or active_assignment(project["id"]):
            flash(request, "This project is already assigned to a team or has been completed. Decline this request with an explanation instead.", "error")
            return RedirectResponse("/teams", 303)
        granted = grant_team_project(project["id"], item["team_id"], days, user["display_name"])
        if not granted:
            flash(request, "Another team was assigned this project first. Refresh and review the active assignment.", "error")
            return RedirectResponse("/teams", 303)
        leader, _ = granted
        msg = f"Your request for {project['name']} was approved."
    else:
        leader = one("SELECT * FROM users WHERE id = ?", (item["user_id"],))
        msg = f"Your request for {project['name']} was reviewed."
    run(
        "UPDATE project_requests SET status = ?, reviewer_feedback = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        ("approved" if decision == "approve" else "declined", feedback.strip()[:3000], user["display_name"], now(), request_id),
    )
    if decision == "approve":
        close_other_pending_requests(project["id"], item["team_id"], user["display_name"])
    notify([leader["id"]], msg + (f" Reviewer feedback: {feedback.strip()[:400]}" if feedback.strip() else ""), "/my-team")
    log(user["display_name"], f"{decision} successor project request", project["name"])
    flash(request, "Request reviewed; feedback was sent to the team.")
    return RedirectResponse("/teams", 303)


@app.post("/submissions/{submission_id}/review", dependencies=[Depends(csrf_check)])
def review_successor_submission(request: Request, submission_id: int, decision: str = Form(""),
                                feedback: str = Form(""), user=Depends(reviewer_required)):
    submission = one("SELECT * FROM successor_submissions WHERE id = ?", (submission_id,))
    if not submission:
        raise HTTPException(404, "That successor submission does not exist.")
    if submission["status"] != "submitted" or decision not in ("accept", "changes"):
        raise HTTPException(400, "Choose a submitted item and a valid review decision.")
    if len(feedback.strip()) < 10:
        flash(request, "Write at least 10 characters of feedback so the team knows what was reviewed.", "error")
        return RedirectResponse("/teams#submissions", 303)
    status = "accepted" if decision == "accept" else "changes_requested"
    run("UPDATE successor_submissions SET status = ?, reviewer_feedback = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (status, feedback.strip()[:3000], user["display_name"], now(), submission_id))
    if decision == "accept":
        run("UPDATE project_assignments SET state = 'completed' WHERE project_id = ? AND share_id = ?",
            (submission["project_id"], submission["share_id"]))
    project = project_or_404(submission["project_id"])
    team = one("SELECT name FROM teams WHERE id = ?", (submission["team_id"],))
    notify([submission["user_id"]],
           f"Reviewer {('accepted' if decision == 'accept' else 'requested changes to')} your work on {project['name']}: {feedback.strip()[:400]}",
           "/my-team")
    log(user["display_name"], f"{decision} successor completion", f"{team['name'] if team else 'Team'}: {project['name']}")
    flash(request, "Successor work accepted." if decision == "accept" else "Changes requested; feedback sent to the team.")
    return RedirectResponse("/teams#active-assignments", 303)


@app.post("/projects", dependencies=[Depends(csrf_check)])
def create_project(request: Request, name: str = Form(""), user=Depends(reviewer_required)):
    name = name.strip()[:80]
    if not name:
        flash(request, "Give the project a name first.", "error")
        return RedirectResponse("/workspace", 303)
    project_id = run("INSERT INTO projects(name, created_by, created_at) VALUES (?, ?, ?)", (name, user["display_name"], now()))
    log(user["display_name"], "created project", name)
    return RedirectResponse(f"/project/{project_id}/connect", 303)


@app.post("/projects/demo", dependencies=[Depends(csrf_check)])
def create_demo(request: Request, kind: str = Form("events"), user=Depends(reviewer_required)):
    if kind not in pipeline.DEMOS:
        raise HTTPException(404, "That demo does not exist.")
    project_id = pipeline.load_demo(user["display_name"], kind)
    log(user["display_name"], "loaded demo project", kind)
    flash(request, "The demo project is ready. Start by reviewing what was found.")
    return RedirectResponse(f"/project/{project_id}/review", 303)


@app.get("/project/{project_id}")
def overview(request: Request, project_id: int, user=Depends(reviewer_required)):
    counts = {row["grade"]: row["n"] for row in query(
        "SELECT grade, COUNT(*) AS n FROM claims WHERE project_id = ? GROUP BY grade", (project_id,))}
    total = max(sum(counts.values()), 1)
    bars = [(grade, counts[grade], round(counts[grade] * 100 / total)) for grade in GRADE_ORDER if grade in counts]
    return project_page(request, "project.html", project_id, "overview", bars=bars,
                        categories=pipeline.PROJECT_CATEGORIES)


@app.post("/project/{project_id}/opportunities", dependencies=[Depends(csrf_check)])
def update_listing(request: Request, project_id: int, enabled: bool = Form(False),
                   public_summary: str = Form(""), category: str = Form("General Operations"),
                   public_scope: str = Form(""), public_skills: str = Form(""), public_outcome: str = Form(""),
                   user=Depends(reviewer_required)):
    project = project_or_404(project_id)
    summary = public_summary.strip()[:500]
    scope = public_scope.strip()[:1200]
    skills = public_skills.strip()[:500]
    outcome = public_outcome.strip()[:800]
    if category not in pipeline.PROJECT_CATEGORIES:
        flash(request, "Choose a valid project category.", "error")
        return RedirectResponse(f"/project/{project_id}", 303)
    if enabled and (not summary or not scope or not outcome or not project_is_incomplete(project_id)):
        flash(request, "To list a project, add its public summary, scope and expected outcome, and make sure reviewable work remains.", "error")
        return RedirectResponse(f"/project/{project_id}", 303)
    run("UPDATE projects SET listing_enabled = ?, public_summary = ?, category = ?, public_scope = ?, "
        "public_skills = ?, public_outcome = ? WHERE id = ?",
        (1 if enabled else 0, summary, category, scope, skills, outcome, project_id))
    log(user["display_name"], "published incomplete project" if enabled else "removed project from directory", project["name"])
    flash(request, "Project listed with its public brief and live status. Source files, claims and reviewer notes remain private." if enabled
          else "Project removed from the successor directory.")
    return RedirectResponse(f"/project/{project_id}", 303)


@app.get("/project/{project_id}/connect")
def connect(request: Request, project_id: int, user=Depends(reviewer_required)):
    sources = query("SELECT * FROM sources WHERE project_id = ? ORDER BY id", (project_id,))
    return project_page(request, "connect.html", project_id, "connect", sources=sources)


@app.post("/project/{project_id}/connect", dependencies=[Depends(csrf_check)])
async def upload(request: Request, project_id: int, source_type: str = Form("notes"), level: int = Form(1),
                 file: UploadFile = File(...), user=Depends(reviewer_required)):
    project_or_404(project_id)
    filename = Path(file.filename or "").name
    data = await file.read(MAX_BYTES + 1)
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS or len(data) > MAX_BYTES or level not in (0, 1, 2):
        flash(request, "Add a .txt, .md, .csv or .json file smaller than 200 KB.", "error")
    else:
        _, masked, stale = pipeline.add_source(
            project_id, filename, source_type.strip()[:30] or "notes", level, data, user["display_name"]
        )
        log(user["display_name"], "added file" if stale is None else "replaced file", f"{filename}, access {pipeline.LEVELS[level]}")
        message = f"{filename} {'added' if stale is None else 'replaced'}. {masked} sensitive item(s) were hidden."
        if stale:
            message += f" {stale} earlier claim(s) no longer match the file and need another look."
        flash(request, message)
    return RedirectResponse(f"/project/{project_id}/connect", 303)


@app.post("/project/{project_id}/analyse", dependencies=[Depends(csrf_check)])
def analyse(request: Request, project_id: int, user=Depends(reviewer_required)):
    project_or_404(project_id)
    found = pipeline.analyse(project_id, user["display_name"])
    log(user["display_name"], "analysed files", f"{found} claims")
    flash(request, f"Found {found} claims. Check each one before it is shared.")
    return RedirectResponse(f"/project/{project_id}/review", 303)


@app.get("/project/{project_id}/review")
def review(request: Request, project_id: int, tab: str = "attention", user=Depends(reviewer_required)):
    tab = tab if tab in TABS else "attention"
    claims = query(
        "SELECT c.*, s.filename, (SELECT COUNT(*) FROM claim_versions v WHERE v.claim_id = c.id AND v.undone = 0) AS versions,"
        " (SELECT COUNT(*) FROM claim_versions v WHERE v.claim_id = c.id AND v.undone = 1) AS redoable"
        " FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ? AND (? IS NULL OR c.status = ?)"
        " ORDER BY CASE c.grade WHEN 'Conflicting' THEN 0 WHEN 'Inferred' THEN 1 WHEN 'Unknown' THEN 2"
        " WHEN 'Testimony' THEN 3 ELSE 4 END, c.id",
        (project_id, TABS[tab], TABS[tab]),
    )
    return project_page(request, "review.html", project_id, "review", claims=claims, tab=tab)


@app.post("/project/{project_id}/approve-backed", dependencies=[Depends(csrf_check)])
def approve_backed(request: Request, project_id: int, user=Depends(reviewer_required)):
    rows = query("SELECT id FROM claims WHERE project_id = ? AND status = 'proposed' AND grade = 'Backed'", (project_id,))
    for row in rows:
        run("UPDATE claims SET status = 'approved', updated_at = ? WHERE id = ?", (now(), row["id"]))
        pipeline.add_version(row["id"], "approved", user["display_name"])
    log(user["display_name"], "approved all backed claims", f"{len(rows)} claims")
    flash(request, f"{len(rows)} backed claims approved.")
    return RedirectResponse(f"/project/{project_id}/review", 303)


@app.post("/claim/{claim_id}/approve", dependencies=[Depends(csrf_check)])
def approve(request: Request, claim_id: int, reason: str = Form(""), tab: str = Form("attention"),
            user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    if claim["grade"] in ("Inferred", "Unknown"):
        if claim["grade"] == "Inferred":
            message = "A guess cannot be approved as fact. Edit it so the quote matches the source, or reject it."
        else:
            message = "An Unknown claim is an open gap, not a fact. Record testimony from the person leaving, or reject it."
        flash(request, message, "error")
        return back_to_review(claim, tab)
    note = claim["note"]
    if claim["grade"] == "Conflicting":
        if not reason.strip():
            flash(request, "Say which source you trust before approving a claim that conflicts with another.", "error")
            return back_to_review(claim, tab)
        note = f"{claim['note']} Reviewer decision: {reason.strip()[:200]}"
    run("UPDATE claims SET status = 'approved', note = ?, updated_at = ? WHERE id = ?", (note, now(), claim_id))
    pipeline.add_version(claim_id, "approved", user["display_name"])
    log(user["display_name"], "approved claim", f"#{claim_id}")
    flash(request, "Claim approved.")
    return back_to_review(claim, tab)


@app.post("/claim/{claim_id}/reject", dependencies=[Depends(csrf_check)])
def reject(request: Request, claim_id: int, tab: str = Form("attention"), user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    run("UPDATE claims SET status = 'rejected', updated_at = ? WHERE id = ?", (now(), claim_id))
    pipeline.add_version(claim_id, "rejected", user["display_name"])
    log(user["display_name"], "rejected claim", f"#{claim_id}")
    flash(request, "Claim rejected. You can undo this.")
    return back_to_review(claim, tab)


@app.post("/claim/{claim_id}/edit", dependencies=[Depends(csrf_check)])
def edit(request: Request, claim_id: int, statement: str = Form(""), quote: str = Form(""),
         tab: str = Form("attention"), user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    statement, quote = statement.strip()[:500], quote.strip()[:500]
    if not statement:
        flash(request, "The statement cannot be empty.", "error")
        return back_to_review(claim, tab)
    grade = pipeline.regrade(claim, quote)
    run("UPDATE claims SET statement = ?, quote = ?, grade = ?, status = 'proposed', updated_at = ? WHERE id = ?",
        (statement, quote, grade, now(), claim_id))
    pipeline.add_version(claim_id, "edited", user["display_name"])
    log(user["display_name"], "edited claim", f"#{claim_id}")
    flash(request, f"Claim updated and checked again. It is now {grade}.")
    return back_to_review(claim, tab)


@app.post("/claim/{claim_id}/answer", dependencies=[Depends(csrf_check)])
def answer(request: Request, claim_id: int, text: str = Form(""), who: str = Form(""),
           tab: str = Form("attention"), user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    if (claim["grade"] != "Unknown" and claim["type"] != "open_question") or not text.strip():
        flash(request, "Only missing information and open questions can be answered, and the answer cannot be empty.", "error")
        return back_to_review(claim, tab)
    statement = f"{pipeline.question_for(claim)} Answer: {text.strip()[:400]} (stated by {who.strip()[:60] or 'the person leaving'})"
    run("UPDATE claims SET statement = ?, quote = '', grade = 'Testimony', status = 'proposed', updated_at = ? WHERE id = ?",
        (statement, now(), claim_id))
    pipeline.add_version(claim_id, "answered", user["display_name"])
    log(user["display_name"], "recorded an answer", f"#{claim_id}")
    flash(request, "Answer saved as testimony. Approve it when you are happy with it.")
    return back_to_review(claim, tab)


@app.post("/claim/{claim_id}/undo", dependencies=[Depends(csrf_check)])
def undo(request: Request, claim_id: int, tab: str = Form("attention"), user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    done = pipeline.undo(claim_id)
    log(user["display_name"], "undid a change" if done else "undo not possible", f"#{claim_id}")
    flash(request, "Last change undone." if done else "There is nothing to undo.", "ok" if done else "error")
    return back_to_review(claim, tab)


@app.post("/claim/{claim_id}/redo", dependencies=[Depends(csrf_check)])
def redo(request: Request, claim_id: int, tab: str = Form("attention"), user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    done = pipeline.redo(claim_id)
    log(user["display_name"], "redid a change" if done else "redo not possible", f"#{claim_id}")
    flash(request, "Change restored." if done else "There is nothing to redo.", "ok" if done else "error")
    return back_to_review(claim, tab)


@app.get("/claim/{claim_id}/evidence")
def evidence(request: Request, claim_id: int, user=Depends(login_required)):
    claim = claim_or_404(claim_id)
    if user["role"] != "reviewer" and (
        claim["status"] != "approved"
        or claim["access_rank"] > user["clearance"]
        or not active_share(claim["project_id"], user["id"])
    ):
        raise HTTPException(404, "That evidence is not available to you.")
    source = one("SELECT * FROM sources WHERE id = ?", (claim["source_id"],))
    text = source["content"]
    span = pipeline.find_span(text, claim["quote"])
    parts = (text[: span[0]], text[span[0] : span[1]], text[span[1] :]) if span else (text, "", "")
    return render(request, "evidence.html", claim=claim, source=source, parts=parts)


@app.get("/project/{project_id}/share")
def share_page(request: Request, project_id: int, user=Depends(reviewer_required)):
    shares = query(
        "SELECT s.*, u.display_name, t.name AS team_name FROM shares s JOIN users u ON u.id = s.user_id "
        "LEFT JOIN teams t ON t.id = u.team_id WHERE s.project_id = ? ORDER BY s.id DESC",
        (project_id,),
    )
    successors = query("SELECT u.*, t.name AS team_name FROM users u LEFT JOIN teams t ON t.id = u.team_id WHERE u.role = 'successor'")
    sent_back = query(
        "SELECT t.*, c.statement, u.display_name FROM tracker t JOIN claims c ON c.id = t.claim_id"
        " JOIN shares s ON s.id = t.share_id JOIN users u ON u.id = s.user_id"
        " WHERE s.project_id = ? AND t.state = 'unclear' ORDER BY t.updated_at DESC",
        (project_id,),
    )
    assignments = query(
        "SELECT tr.assignee, c.statement, u.display_name, t.name AS team_name FROM tracker tr "
        "JOIN claims c ON c.id = tr.claim_id JOIN shares s ON s.id = tr.share_id JOIN users u ON u.id = s.user_id "
        "LEFT JOIN teams t ON t.id = u.team_id WHERE s.project_id = ? AND tr.assignee != '' ORDER BY c.id",
        (project_id,),
    )
    rehearsal = pipeline.rehearsal(project_id)
    blockers = [item for item in rehearsal["questions"]
                if not item["answered"] and item["reason"] != "Hidden from the successor"]
    ownership = project_assignment(project_id)
    assignment_locked = bool(active_assignment(project_id) or (ownership and ownership["state"] == "completed"))
    return project_page(request, "share.html", project_id, "share", shares=shares, successors=successors,
                        sent_back=sent_back, assignments=assignments, current=now(), readiness=rehearsal["score"],
                        readiness_ready=not blockers, readiness_blockers=blockers,
                        assignment_locked=assignment_locked, current_assignment=ownership)


@app.post("/project/{project_id}/share", dependencies=[Depends(csrf_check)])
def create_share(request: Request, project_id: int, user_id: int = Form(...), days: int = Form(7),
                 assignment_note: str = Form(""),
                 user=Depends(reviewer_required)):
    info = stats(project_id)
    target = one("SELECT * FROM users WHERE id = ? AND role = 'successor'", (user_id,))
    gate = share_gate_message(project_id)
    if gate or not target or not target["team_id"] or days not in (7, 14, 30) or len(assignment_note.strip()) < 10:
        flash(request, gate or "Choose a valid successor group and sharing period, and write an assignment brief of at least 10 characters.", "error")
        return RedirectResponse(f"/project/{project_id}/share", 303)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    share_id = create_project_share(project_id, target["team_id"], target["id"], expires, user["display_name"])
    if not share_id:
        flash(request, "This project is already assigned to one successor team. Revoke or wait for its current assignment to expire before sharing it again.", "error")
        return RedirectResponse(f"/project/{project_id}/share", 303)
    team = one("SELECT * FROM teams WHERE id = ?", (target["team_id"],))
    run(
        "INSERT INTO project_requests(project_id, team_id, user_id, status, reviewer_feedback, requested_at, reviewed_by, reviewed_at) "
        "VALUES (?, ?, ?, 'approved', ?, ?, ?, ?) ON CONFLICT(project_id, team_id) DO UPDATE SET "
        "user_id=excluded.user_id, status='approved', reviewer_feedback=excluded.reviewer_feedback, "
        "reviewed_by=excluded.reviewed_by, reviewed_at=excluded.reviewed_at",
        (project_id, target["team_id"], user_id, assignment_note.strip()[:3000], now(), user["display_name"], now()),
    )
    close_other_pending_requests(project_id, target["team_id"], user["display_name"])
    log(user["display_name"], "shared plan", f"with {target['display_name']} for {days} days")
    notify([user_id], f"{user['display_name']} assigned {project_or_404(project_id)['name']} exclusively to {team['name']}: {assignment_note.strip()[:300]}.", f"/project/{project_id}/plan")
    flash(request, f"Plan assigned exclusively to {team['name']} for {days} days.")
    return RedirectResponse(f"/project/{project_id}/share", 303)


@app.post("/share/{share_id}/revoke", dependencies=[Depends(csrf_check)])
def revoke(request: Request, share_id: int, user=Depends(reviewer_required)):
    share = one("SELECT * FROM shares WHERE id = ?", (share_id,))
    if not share:
        raise HTTPException(404, "That share does not exist.")
    run("UPDATE shares SET revoked = 1 WHERE id = ?", (share_id,))
    run("UPDATE project_assignments SET state = 'revoked' WHERE share_id = ? AND state = 'active'", (share_id,))
    notify([share["user_id"]], "Your access to a handover plan was removed.", "/workspace")
    log(user["display_name"], "revoked share", f"#{share_id}")
    flash(request, "Access removed.")
    return RedirectResponse(f"/project/{share['project_id']}/share", 303)


def visible_plan(request, user, project_id):
    if user["role"] == "reviewer":
        previewing = request.query_params.get("preview") == "successor"
        return (1 if previewing else 2), None, previewing
    share = active_share(project_id, user["id"])
    return (user["clearance"] if share else None), share, False


@app.get("/project/{project_id}/plan")
def plan(request: Request, project_id: int, user=Depends(login_required)):
    project = project_or_404(project_id)
    clearance, share, previewing = visible_plan(request, user, project_id)
    sections = pipeline.plan_sections(project_id, clearance) if clearance is not None else None
    recurring = pipeline.recurring_problems(project_id, clearance, approved_only=True) if clearance is not None else []
    context = dict(project=project, sections=sections, share=share, previewing=previewing, step="plan", tracker=None,
                   recurring=recurring, members=[], submission=None, action_total=0, action_done=0)
    if user["role"] == "reviewer":
        return render(request, "plan.html", stats=stats(project_id), **context)
    if share:
        context["tracker"] = {
            row["claim_id"]: row for row in query("SELECT * FROM tracker WHERE share_id = ?", (share["id"],))
        }
        context["submission"] = one("SELECT * FROM successor_submissions WHERE share_id = ?", (share["id"],))
        context["action_total"] = one(
            "SELECT COUNT(*) AS n FROM claims WHERE project_id = ? AND type = 'next_action' "
            "AND status = 'approved' AND access_rank <= ?", (project_id, user["clearance"])
        )["n"]
        context["action_done"] = one(
            "SELECT COUNT(*) AS n FROM tracker tr JOIN claims c ON c.id = tr.claim_id "
            "WHERE tr.share_id = ? AND tr.state = 'done' AND c.type = 'next_action'", (share["id"],)
        )["n"]
        team = team_for_user(user)
        if team:
            context["members"] = query("SELECT * FROM team_members WHERE team_id = ? ORDER BY id", (team["id"],))
    return render(request, "plan.html", stats=None, **context)


@app.post("/project/{project_id}/acknowledge", dependencies=[Depends(csrf_check)])
def acknowledge(request: Request, project_id: int, user=Depends(login_required)):
    share = active_share(project_id, user["id"])
    if not share:
        raise HTTPException(403, "No plan is shared with you.")
    run("UPDATE shares SET acknowledged_at = ? WHERE id = ?", (now(), share["id"]))
    log(user["display_name"], "acknowledged the plan", f"project #{project_id}")
    notify(user_ids("reviewer"), f"{user['display_name']} confirmed they have read the plan.", f"/project/{project_id}/share")
    flash(request, "Thank you. Your acknowledgement was recorded.")
    return RedirectResponse(f"/project/{project_id}/plan", 303)


def export_rows(request, user, project_id):
    project_or_404(project_id)
    clearance, _, _ = visible_plan(request, user, project_id)
    if clearance is None:
        raise HTTPException(403, "No plan is shared with you.")
    return [
        {"type": item["type"], "statement": item["statement"], "grade": item["grade"], "quote": item["quote"],
         "source": item["filename"], "note": item["note"], "section": title}
        for title, items in pipeline.plan_sections(project_id, clearance) for item in items
    ]


def download(content, media_type, project_id, extension):
    disposition = f'attachment; filename="handover-{project_id}.{extension}"'
    return Response(content, media_type=media_type, headers={"Content-Disposition": disposition})


@app.get("/project/{project_id}/export.json")
def export_json(request: Request, project_id: int, user=Depends(login_required)):
    return download(json.dumps(exports.plain(export_rows(request, user, project_id))), "application/json", project_id, "json")


@app.get("/project/{project_id}/export.csv")
def export_csv(request: Request, project_id: int, user=Depends(login_required)):
    return download(exports.to_csv(export_rows(request, user, project_id)), "text/csv", project_id, "csv")


@app.get("/project/{project_id}/export.xlsx")
def export_xlsx(request: Request, project_id: int, user=Depends(login_required)):
    return download(exports.to_xlsx(export_rows(request, user, project_id)), exports.XLSX_TYPE, project_id, "xlsx")


@app.get("/project/{project_id}/export.docx")
def export_docx(request: Request, project_id: int, user=Depends(login_required)):
    rows = export_rows(request, user, project_id)
    return download(exports.to_docx(rows, project_or_404(project_id)["name"]), exports.DOCX_TYPE, project_id, "docx")


@app.get("/project/{project_id}/export.xml")
def export_xml(request: Request, project_id: int, user=Depends(login_required)):
    rows = export_rows(request, user, project_id)
    return download(exports.to_xml(rows, project_or_404(project_id)["name"]), "application/xml", project_id, "xml")


@app.get("/project/{project_id}/timeline")
def timeline(request: Request, project_id: int, user=Depends(login_required)):
    project = project_or_404(project_id)
    clearance, _, previewing = visible_plan(request, user, project_id)
    entries = pipeline.timeline(project_id, clearance) if clearance is not None else None
    info = stats(project_id) if user["role"] == "reviewer" else None
    return render(request, "timeline.html", project=project, entries=entries, previewing=previewing, stats=info, step="plan")


@app.get("/project/{project_id}/questions")
def questions(request: Request, project_id: int, user=Depends(reviewer_required)):
    return project_page(request, "questions.html", project_id, "review", items=pipeline.open_questions(project_id),
                        terms=pipeline.dark_matter(project_id), people=pipeline.knowledge_map(project_id),
                        recurring=pipeline.recurring_problems(project_id))


@app.get("/project/{project_id}/rehearsal")
def rehearsal_page(request: Request, project_id: int, user=Depends(reviewer_required)):
    return project_page(request, "rehearsal.html", project_id, "share", result=pipeline.rehearsal(project_id))


@app.get("/project/{project_id}/search")
def search(request: Request, project_id: int, q: str = "", user=Depends(login_required)):
    project = project_or_404(project_id)
    clearance, _, previewing = visible_plan(request, user, project_id)
    if clearance is None:
        raise HTTPException(403, "No plan is shared with you.")
    reviewer = user["role"] == "reviewer"
    results = None
    if len(q.strip()) >= 2:
        results = pipeline.search_claims(project_id, q, clearance, approved_only=previewing or not reviewer)
    info = stats(project_id) if reviewer else None
    return render(request, "search.html", project=project, results=results, query_text=q.strip()[:100], stats=info,
                  step="review", reviewer=reviewer)


@app.get("/claim/{claim_id}/history")
def history(request: Request, claim_id: int, user=Depends(reviewer_required)):
    claim = claim_or_404(claim_id)
    versions = [
        dict(row) | json.loads(row["snapshot"])
        for row in query("SELECT * FROM claim_versions WHERE claim_id = ? ORDER BY id DESC", (claim_id,))
    ]
    return render(request, "history.html", claim=claim, versions=versions)


@app.post("/project/{project_id}/delete", dependencies=[Depends(csrf_check)])
def delete(request: Request, project_id: int, user=Depends(reviewer_required)):
    project = project_or_404(project_id)
    pipeline.delete_project(project_id)
    log(user["display_name"], "deleted project", f"#{project_id}")
    flash(request, f"{project['name']} and everything in it was deleted.")
    return RedirectResponse("/workspace", 303)


def action_share(project_id, claim_id, user):
    share = None if user["role"] == "reviewer" else active_share(project_id, user["id"])
    visible = one(
        "SELECT id FROM claims WHERE id = ? AND project_id = ? AND type = 'next_action' AND status = 'approved'"
        " AND access_rank <= ?",
        (claim_id, project_id, user["clearance"]),
    )
    if not share or not visible:
        raise HTTPException(404, "That action is not available to you.")
    return share


@app.post("/project/{project_id}/action/{claim_id}/assign-member", dependencies=[Depends(csrf_check)])
def assign_action_member(request: Request, project_id: int, claim_id: int, member_name: str = Form(""),
                         user=Depends(login_required)):
    if user["role"] != "successor":
        raise HTTPException(403, "Only the assigned successor team can divide its actions.")
    share = action_share(project_id, claim_id, user)
    team = team_for_user(user)
    if not team:
        raise HTTPException(403, "This successor account has no team roster.")
    valid_names = {row["name"] for row in query("SELECT name FROM team_members WHERE team_id = ?", (team["id"],))}
    if member_name and member_name not in valid_names:
        raise HTTPException(400, "Choose a name from your team roster.")
    run(
        "INSERT INTO tracker(share_id, claim_id, state, note, reply, updated_at, assignee) VALUES (?, ?, 'open', '', '', ?, ?) "
        "ON CONFLICT(share_id, claim_id) DO UPDATE SET assignee=excluded.assignee, updated_at=excluded.updated_at",
        (share["id"], claim_id, now(), member_name),
    )
    log(user["display_name"], "assigned team action" if member_name else "unassigned team action",
        f"claim #{claim_id}: {member_name}")
    flash(request, f"Task assigned to {member_name}." if member_name else "Task assignment cleared.")
    return RedirectResponse(f"/project/{project_id}/plan#action-{claim_id}", 303)


@app.post("/project/{project_id}/action/{claim_id}/done", dependencies=[Depends(csrf_check)])
def toggle_done(request: Request, project_id: int, claim_id: int, user=Depends(login_required)):
    share = action_share(project_id, claim_id, user)
    row = one("SELECT * FROM tracker WHERE share_id = ? AND claim_id = ?", (share["id"], claim_id))
    if row and row["state"] == "done":
        run("DELETE FROM tracker WHERE id = ?", (row["id"],))
    else:
        pipeline.set_tracker(share["id"], claim_id, "done")
    return RedirectResponse(f"/project/{project_id}/plan#action-{claim_id}", 303)


@app.post("/project/{project_id}/action/{claim_id}/unclear", dependencies=[Depends(csrf_check)])
def send_back(request: Request, project_id: int, claim_id: int, note: str = Form(""), user=Depends(login_required)):
    share = action_share(project_id, claim_id, user)
    if not note.strip():
        flash(request, "Say what is unclear so the reviewer can help.", "error")
    else:
        pipeline.set_tracker(share["id"], claim_id, "unclear", note.strip()[:400])
        log(user["display_name"], "sent an action back", f"claim #{claim_id}")
        notify(user_ids("reviewer"), f"{user['display_name']} sent an action back and needs help.", f"/project/{project_id}/share")
        flash(request, "Sent back to the reviewer.")
    return RedirectResponse(f"/project/{project_id}/plan#action-{claim_id}", 303)


@app.post("/tracker/{tracker_id}/answer", dependencies=[Depends(csrf_check)])
def answer_question(request: Request, tracker_id: int, reply: str = Form(""), user=Depends(reviewer_required)):
    row = one("SELECT t.*, s.project_id FROM tracker t JOIN shares s ON s.id = t.share_id WHERE t.id = ?", (tracker_id,))
    if not row:
        raise HTTPException(404, "That question does not exist.")
    if not reply.strip():
        flash(request, "Write a reply first.", "error")
    else:
        run("UPDATE tracker SET state = 'answered', reply = ?, updated_at = ? WHERE id = ?",
            (reply.strip()[:400], now(), tracker_id))
        log(user["display_name"], "answered a question", f"#{tracker_id}")
        asker = one("SELECT user_id FROM shares WHERE id = ?", (row["share_id"],))
        notify([asker["user_id"]], "The reviewer replied to your question.", f"/project/{row['project_id']}/plan")
        flash(request, "Reply sent.")
    return RedirectResponse(f"/project/{row['project_id']}/share", 303)


@app.get("/activity")
def activity(request: Request, user=Depends(reviewer_required)):
    return render(request, "activity.html", entries=query("SELECT * FROM audit ORDER BY id DESC LIMIT 100"))


@app.get("/evaluation")
def evaluation_page(request: Request, user=Depends(reviewer_required)):
    return render(request, "evaluation.html", results=None)


@app.post("/evaluation", dependencies=[Depends(csrf_check)])
def run_evaluation(request: Request, user=Depends(reviewer_required)):
    results = [pipeline.evaluate(key) for key in pipeline.DEMOS]
    log(user["display_name"], "ran the self-check")
    return render(request, "evaluation.html", results=results)


@app.get("/notifications")
def notifications(request: Request, user=Depends(login_required)):
    items = query("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50", (user["id"],))
    return render(request, "notifications.html", items=items)


@app.post("/notifications/read", dependencies=[Depends(csrf_check)])
def mark_read(request: Request, user=Depends(login_required)):
    run("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user["id"],))
    return RedirectResponse("/notifications", 303)
