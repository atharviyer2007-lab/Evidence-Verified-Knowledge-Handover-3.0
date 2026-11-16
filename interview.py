"""Leaver Interview Mode: the question queue, answers stored as Testimony, and the coverage meter.

The queue is rebuilt from the claims every time, so it always matches the review state. Answers become
ordinary claims graded Testimony: they still need an independent reviewer's approval, and a leaver
has no route that can approve anything.
"""

import re

import pipeline
from db import now, one, query, run

INTERVIEW_FILE = "leaver-interview.md"
ANSWERED = "Answer:"


def _interview_source(project_id):
    row = one("SELECT id FROM sources WHERE project_id = ? AND filename = ?", (project_id, INTERVIEW_FILE))
    if row:
        return row["id"]
    return run(
        "INSERT INTO sources(project_id, filename, source_type, access_rank, content, masked_count, uploaded_at) "
        "VALUES (?, ?, 'interview', 1, '', 0, ?)", (project_id, INTERVIEW_FILE, now()))


def queue(project_id):
    """Every question worth asking, in a stable order, with its current state."""
    claims = query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ? "
        "AND c.status != 'rejected' ORDER BY c.id", (project_id,))
    known_owners = {claim["owner"] for claim in claims if claim["owner"]}
    saved = {row["item_key"]: row for row in query("SELECT * FROM interview_items WHERE project_id = ?", (project_id,))}
    items = []

    def add(key, kind, prompt, claim=None, where=""):
        row = saved.get(key)
        state = "open"
        if claim is not None and ANSWERED in claim["statement"]:
            state = "answered"
        elif row and row["status"] in ("answered", "refer"):
            linked = one("SELECT id FROM claims WHERE id = ?", (row["claim_id"],)) if row["claim_id"] else None
            state = row["status"] if linked else "open"
        elif row and row["status"] == "dont_remember":
            state = "dont_remember"
        items.append({"key": key, "kind": kind, "prompt": prompt, "state": state, "claim": claim, "where": where,
                      "answer": (row["answer"] if row else ""), "who": (row["who"] if row else "")})

    for claim in claims:
        if claim["filename"] == INTERVIEW_FILE:
            continue  # answers the leaver wrote are not questions themselves
        answered = ANSWERED in claim["statement"]
        if claim["grade"] == "Unknown" or claim["type"] == "open_question" or (claim["type"] == "gap" and answered):
            add(f"claim:{claim['id']}", "gap", pipeline.question_for(claim).split(f" {ANSWERED}")[0], claim, claim["filename"])
    for claim in claims:
        if claim["filename"] == INTERVIEW_FILE:
            continue
        if claim["type"] == "blocker" and not any(name and name in f"{claim['statement']} {claim['quote']}" for name in known_owners):
            add(f"claim:{claim['id']}", "blocker",
                f"Who is working on this blocker, and what would unblock it? {claim['statement']}", claim, claim["filename"])
    for term in pipeline.dark_matter(project_id):
        add(f"term:{term['term']}", "term", f"What does \u201c{term['term']}\u201d mean, and who owns it?", None, ", ".join(term["sources"]))
    for person in pipeline.knowledge_map(project_id):
        if person["at_risk"]:
            add(f"owner:{person['name']}", "owner",
                f"{person['name']} owns {person['count']} areas ({', '.join(person['areas'])}). Who is the backup for each?", None, "task board and notes")
    return items


def coverage(items):
    raised = len(items)
    answered = sum(1 for item in items if item["state"] in ("answered", "refer"))
    logged = sum(1 for item in items if item["state"] == "dont_remember")
    return {"raised": raised, "answered": answered, "logged": logged, "open": raised - answered - logged,
            "percent": round(100 * answered / raised) if raised else 100}


def _rank_for(project_id, key, claim):
    if claim is not None:
        return claim["access_rank"]
    if key.startswith("owner:"):
        row = one("SELECT MAX(access_rank) AS r FROM claims WHERE project_id = ? AND owner = ?", (project_id, key[6:]))
        return max(1, row["r"] or 1) if row else 1
    term = key[5:]
    rank = 1
    for source in query("SELECT content, access_rank FROM sources WHERE project_id = ?", (project_id,)):
        if term in " ".join(source["content"].lower().split()):
            rank = max(rank, source["access_rank"])
    return rank


def _new_claim(project_id, kind, statement, rank, author, key=None):
    previous = one("SELECT claim_id FROM interview_items WHERE project_id = ? AND item_key = ?", (project_id, key)) if key else None
    if previous and previous["claim_id"]:
        old = one("SELECT * FROM claims WHERE id = ? AND type = ? AND status = 'proposed' AND authored_by = ?",
                  (previous["claim_id"], kind, author))
        if old:
            run("UPDATE claims SET statement = ?, updated_at = ? WHERE id = ?", (statement[:600], now(), old["id"]))
            pipeline.add_version(old["id"], "answered", author)
            return old["id"]
    source_id = _interview_source(project_id)
    claim_id = run(
        "INSERT INTO claims(project_id, source_id, type, statement, quote, grade, status, access_rank, note, created_at, "
        "updated_at, owner, area, authored_by) VALUES (?, ?, ?, ?, '', 'Testimony', 'proposed', ?, '', ?, ?, '', '', ?)",
        (project_id, source_id, kind, statement[:600], rank, now(), now(), author))
    pipeline.add_version(claim_id, "answered", author)
    return claim_id


def record(project_id, key, action, text, who, user):
    """Save one interview answer. Returns (ok, message). Never approves anything."""
    item = next((entry for entry in queue(project_id) if entry["key"] == key), None)
    if not item:
        return False, "That question is no longer on the list."
    claim = item["claim"]
    if claim is not None and claim["status"] == "approved" and ANSWERED in claim["statement"]:
        return False, "A reviewer already approved this answer, so it is locked."
    text, who = " ".join(text.split())[:400], " ".join(who.split())[:60]
    author = user["username"]
    name = who or user["display_name"]
    claim_id = claim["id"] if claim is not None else None
    if action == "dont_remember":
        status, text = "dont_remember", ""
        if claim is not None:
            run("UPDATE claims SET note = ?, updated_at = ? WHERE id = ?", ("The person leaving says they do not remember.", now(), claim["id"]))
    elif action == "refer":
        if not who:
            return False, "Write the name of the person to ask."
        status = "refer"
        short = item["prompt"].split("?")[0][:120]
        claim_id = _new_claim(project_id, "contact", f"For \u201c{short}\u201d, ask {who}. (suggested by {user['display_name']})",
                              _rank_for(project_id, key, claim), author, key)
    elif action == "answer":
        if not text:
            return False, "Write an answer first, or choose \u201cI do not remember\u201d."
        status = "answered"
        if claim is not None and item["kind"] == "gap":
            statement = f"{pipeline.question_for(claim).split(' Answer:')[0]} {ANSWERED} {text} (stated by {name})"
            run("UPDATE claims SET statement = ?, quote = '', grade = 'Testimony', status = 'proposed', authored_by = ?, "
                "approved_by = '', self_approved = 0, updated_at = ? WHERE id = ?", (statement, author, now(), claim["id"]))
            pipeline.add_version(claim["id"], "answered", author)
        elif item["kind"] == "blocker":
            claim_id = _new_claim(project_id, "next_action", f"To unblock this: {text} (stated by {name})", _rank_for(project_id, key, claim), author, key)
        elif item["kind"] == "owner":
            claim_id = _new_claim(project_id, "contact", f"Backup for {key[6:]}: {text} (stated by {name})", _rank_for(project_id, key, claim), author, key)
        else:
            claim_id = _new_claim(project_id, "gap", f"What is {key[5:]}? {ANSWERED} {text} (stated by {name})", _rank_for(project_id, key, claim), author, key)
    else:
        return False, "Choose answer, I do not remember, or ask someone else."
    run(
        "INSERT INTO interview_items(project_id, item_key, kind, prompt, status, answer, who, claim_id, user_id, answered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, item_key) DO UPDATE SET status = excluded.status, "
        "answer = excluded.answer, who = excluded.who, claim_id = excluded.claim_id, user_id = excluded.user_id, "
        "answered_at = excluded.answered_at",
        (project_id, key, item["kind"], item["prompt"][:300], status, text, who, claim_id, user["id"], now()))
    return True, {"answer": "Answer saved. A reviewer will check it before it reaches the plan.",
                  "refer": "Saved. The person you named will appear under Who to ask once a reviewer approves it.",
                  "dont_remember": "Logged as an open gap. It stays visible to the reviewer."}[action]


def leaver_for_user(user_id):
    return one("SELECT l.*, p.name AS project_name FROM leavers l JOIN projects p ON p.id = l.project_id "
               "WHERE l.user_id = ? AND l.revoked = 0", (user_id,))


def valid_username(name):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,29}", name))
