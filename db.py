import json
import os
import sqlite3
from datetime import datetime, timezone

from security import hash_password

DB_PATH = os.environ.get("HANDOVER_DB", "handover.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
    role TEXT, clearance INTEGER, display_name TEXT, job_title TEXT DEFAULT '', team_id INTEGER,
    tour_choice TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY, name TEXT, created_by TEXT, created_at TEXT,
    listing_enabled INTEGER DEFAULT 0, public_summary TEXT DEFAULT '', category TEXT DEFAULT 'General Operations',
    public_scope TEXT DEFAULT '', public_skills TEXT DEFAULT '', public_outcome TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY, project_id INTEGER, filename TEXT, source_type TEXT,
    access_rank INTEGER, content TEXT, masked_count INTEGER, uploaded_at TEXT);
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY, project_id INTEGER, source_id INTEGER, type TEXT,
    statement TEXT, quote TEXT, grade TEXT, status TEXT, access_rank INTEGER,
    note TEXT, created_at TEXT, updated_at TEXT, owner TEXT DEFAULT '', area TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS claim_versions (
    id INTEGER PRIMARY KEY, claim_id INTEGER, snapshot TEXT, action TEXT,
    by_user TEXT, at TEXT, undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY, project_id INTEGER, user_id INTEGER, expires_at TEXT,
    revoked INTEGER DEFAULT 0, acknowledged_at TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS tracker (
    id INTEGER PRIMARY KEY, share_id INTEGER, claim_id INTEGER, state TEXT, note TEXT,
    reply TEXT, updated_at TEXT, assignee TEXT DEFAULT '', UNIQUE (share_id, claim_id));
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY, name TEXT, job_title TEXT, created_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS team_members (
    id INTEGER PRIMARY KEY, team_id INTEGER, name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS project_requests (
    id INTEGER PRIMARY KEY, project_id INTEGER, team_id INTEGER, user_id INTEGER,
    status TEXT DEFAULT 'pending', request_note TEXT DEFAULT '', reviewer_feedback TEXT DEFAULT '',
    requested_at TEXT, reviewed_by TEXT DEFAULT '', reviewed_at TEXT DEFAULT '',
    UNIQUE (project_id, team_id));
CREATE TABLE IF NOT EXISTS project_assignments (
    project_id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, user_id INTEGER NOT NULL, share_id INTEGER NOT NULL,
    assigned_by TEXT DEFAULT '', assigned_at TEXT, state TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS successor_submissions (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, team_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    share_id INTEGER NOT NULL UNIQUE, status TEXT DEFAULT 'submitted', summary TEXT DEFAULT '', submitted_at TEXT,
    reviewer_feedback TEXT DEFAULT '', reviewed_by TEXT DEFAULT '', reviewed_at TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, user_id INTEGER, message TEXT, link TEXT, created_at TEXT, is_read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at TEXT, user TEXT, action TEXT, detail TEXT);
"""

MIGRATIONS = [
    ("owner", "claims", "ALTER TABLE claims ADD COLUMN owner TEXT DEFAULT ''"),
    ("area", "claims", "ALTER TABLE claims ADD COLUMN area TEXT DEFAULT ''"),
    ("undone", "claim_versions", "ALTER TABLE claim_versions ADD COLUMN undone INTEGER DEFAULT 0"),
    ("job_title", "users", "ALTER TABLE users ADD COLUMN job_title TEXT DEFAULT ''"),
    ("team_id", "users", "ALTER TABLE users ADD COLUMN team_id INTEGER"),
    ("listing_enabled", "projects", "ALTER TABLE projects ADD COLUMN listing_enabled INTEGER DEFAULT 0"),
    ("public_summary", "projects", "ALTER TABLE projects ADD COLUMN public_summary TEXT DEFAULT ''"),
    ("category", "projects", "ALTER TABLE projects ADD COLUMN category TEXT DEFAULT 'General Operations'"),
    ("assignee", "tracker", "ALTER TABLE tracker ADD COLUMN assignee TEXT DEFAULT ''"),
    ("tour_choice", "users", "ALTER TABLE users ADD COLUMN tour_choice TEXT DEFAULT ''"),
    ("public_scope", "projects", "ALTER TABLE projects ADD COLUMN public_scope TEXT DEFAULT ''"),
    ("public_skills", "projects", "ALTER TABLE projects ADD COLUMN public_skills TEXT DEFAULT ''"),
    ("public_outcome", "projects", "ALTER TABLE projects ADD COLUMN public_outcome TEXT DEFAULT ''"),
]

DEMO_USERS = [
    ("reviewer", "reviewer123", "reviewer", 2, "Asha (reviewer)"),
    ("successor", "successor123", "successor", 1, "Meera (successor)"),
]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql, args=()):
    conn = connect()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def run(sql, args=()):
    conn = connect()
    try:
        with conn:
            return conn.execute(sql, args).lastrowid
    finally:
        conn.close()


def run_all(statements):
    conn = connect()
    try:
        with conn:
            for sql, args in statements:
                conn.execute(sql, args)
    finally:
        conn.close()


def migrate():
    for column, table, statement in MIGRATIONS:
        names = {row["name"] for row in query("SELECT name FROM pragma_table_info(?)", (table,))}
        if column not in names:
            run(statement)


def user_ids(role):
    return [row["id"] for row in query("SELECT id FROM users WHERE role = ?", (role,))]


def notify(recipients, message, link=""):
    run_all([
        ("INSERT INTO notifications(user_id, message, link, created_at) VALUES (?, ?, ?, ?)",
         (recipient, message, link, now()))
        for recipient in recipients
    ])


def unread_count(user_id):
    return one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,))["n"]


def log(user, action, detail=""):
    run("INSERT INTO audit(at, user, action, detail) VALUES (?, ?, ?, ?)", (now(), user, action, detail))


def init_db():
    conn = connect()
    try:
        with conn:
            conn.executescript(SCHEMA)
    finally:
        conn.close()
    migrate()
    if not query("SELECT id FROM users"):
        for username, password, role, clearance, name in DEMO_USERS:
            run(
                "INSERT INTO users(username, password_hash, role, clearance, display_name) VALUES (?, ?, ?, ?, ?)",
                (username, hash_password(password), role, clearance, name),
            )
    ensure_legacy_teams()
    backfill_project_assignments()


def create_team_account(username, password_hash, display_name, job_title, team_name, member_names):
    conn = connect()
    try:
        with conn:
            team_id = conn.execute(
                "INSERT INTO teams(name, job_title, created_at) VALUES (?, ?, ?)",
                (team_name, job_title, now()),
            ).lastrowid
            user_id = conn.execute(
                "INSERT INTO users(username, password_hash, role, clearance, display_name, job_title, team_id) "
                "VALUES (?, ?, 'successor', 1, ?, ?, ?)",
                (username, password_hash, display_name, job_title, team_id),
            ).lastrowid
            conn.execute("UPDATE teams SET created_by = ? WHERE id = ?", (user_id, team_id))
            conn.executemany(
                "INSERT INTO team_members(team_id, name, created_at) VALUES (?, ?, ?)",
                [(team_id, name, now()) for name in [display_name, *member_names]],
            )
        return user_id, team_id
    finally:
        conn.close()


def ensure_legacy_teams():
    for user in query("SELECT * FROM users WHERE role = 'successor' AND team_id IS NULL"):
        conn = connect()
        try:
            with conn:
                team_id = conn.execute(
                    "INSERT INTO teams(name, job_title, created_by, created_at) VALUES (?, ?, ?, ?)",
                    (f"{user['display_name']}'s team", user["job_title"] or "Other", user["id"], now()),
                ).lastrowid
                conn.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, user["id"]))
                conn.execute(
                    "INSERT INTO team_members(team_id, name, created_at) VALUES (?, ?, ?)",
                    (team_id, user["display_name"], now()),
                )
        finally:
            conn.close()


def create_project_share(project_id, team_id, user_id, expires_at, reviewer_name):
    """Create a share and claim exclusive project ownership in one write transaction."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT pa.state, s.revoked, s.expires_at FROM project_assignments pa "
            "LEFT JOIN shares s ON s.id = pa.share_id WHERE pa.project_id = ?", (project_id,)
        ).fetchone()
        if existing and existing["state"] == "completed":
            conn.rollback()
            return None
        if (existing and existing["state"] == "active" and existing["revoked"] == 0
                and existing["expires_at"] and existing["expires_at"] > now()):
            conn.rollback()
            return None
        created = now()
        share_id = conn.execute(
            "INSERT INTO shares(project_id, user_id, expires_at, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, user_id, expires_at, reviewer_name, created),
        ).lastrowid
        conn.execute(
            "INSERT INTO project_assignments(project_id, team_id, user_id, share_id, assigned_by, assigned_at, state) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active') ON CONFLICT(project_id) DO UPDATE SET "
            "team_id=excluded.team_id, user_id=excluded.user_id, share_id=excluded.share_id, "
            "assigned_by=excluded.assigned_by, assigned_at=excluded.assigned_at, state='active'",
            (project_id, team_id, user_id, share_id, reviewer_name, created),
        )
        conn.commit()
        return share_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backfill_project_assignments():
    """Keep legacy projects exclusive: the latest still-valid share is the owner."""
    active = query("SELECT * FROM shares WHERE revoked = 0 AND expires_at > ? ORDER BY project_id, id DESC", (now(),))
    grouped = {}
    for share in active:
        grouped.setdefault(share["project_id"], []).append(share)
    for project_id, shares in grouped.items():
        prior = one("SELECT * FROM project_assignments WHERE project_id = ?", (project_id,))
        if prior and prior["state"] == "completed":
            keep_id = prior["share_id"]
            chosen = next((item for item in shares if item["id"] == keep_id), None)
        else:
            chosen = next((item for item in shares if prior and item["id"] == prior["share_id"]), shares[0])
            keep_id = chosen["id"] if chosen else None
        if not chosen:
            continue
        owner = one("SELECT id, team_id FROM users WHERE id = ? AND role = 'successor'", (chosen["user_id"],))
        if not owner or not owner["team_id"]:
            continue
        for other in shares:
            if other["id"] != keep_id:
                run("UPDATE shares SET revoked = 1 WHERE id = ?", (other["id"],))
                notify([other["user_id"]], "This project is assigned to one successor team; this account’s access was removed.", "/workspace")
        if not prior or prior["state"] != "completed":
            run(
                "INSERT INTO project_assignments(project_id, team_id, user_id, share_id, assigned_by, assigned_at, state) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active') ON CONFLICT(project_id) DO UPDATE SET "
                "team_id=excluded.team_id, user_id=excluded.user_id, share_id=excluded.share_id, state='active'",
                (project_id, owner["team_id"], owner["id"], chosen["id"], chosen["created_by"], chosen["created_at"]),
            )


def snapshot(claim):
    return json.dumps({key: claim[key] for key in ("statement", "quote", "grade", "status", "note")})
