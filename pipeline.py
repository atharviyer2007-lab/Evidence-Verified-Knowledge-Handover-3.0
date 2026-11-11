import csv
import json
import re
from collections import Counter
from pathlib import Path

from db import now, one, query, run, run_all, snapshot
from llm import llm_extract

LEVELS = ["public", "team", "restricted"]
SAMPLE_DIR = Path(__file__).parent / "sample_data"
PROJECT_CATEGORIES = [
    "Software", "Healthcare", "Banking & Finance", "Cybersecurity", "Education",
    "General Operations", "Community & Nonprofit",
]
DEMOS = {
    "events": {
        "title": "Campus Events Portal (demo)",
        "category": "Software",
        "files": [
            ("overview.md", "notes", 0),
            ("team_notes.md", "meeting notes", 1),
            ("task_board.csv", "task board", 1),
            ("chat_export.json", "chat", 1),
            ("leadership_notes.md", "meeting notes", 2),
        ],
    },
    "club": {
        "title": "Lens Club Handover (demo)",
        "category": "Community & Nonprofit",
        "files": [
            ("club_overview.md", "notes", 0),
            ("committee_minutes.md", "meeting notes", 1),
            ("club_tasks.csv", "task board", 1),
            ("club_chat.json", "chat", 1),
            ("treasurer_notes.md", "meeting notes", 2),
        ],
    },
    "healthcare": {
        "title": "Riverside Clinic Scheduling (demo)",
        "category": "Healthcare",
        "files": [("overview.md", "notes", 0), ("clinic_notes.md", "meeting notes", 1), ("tasks.csv", "task board", 1)],
    },
    "banking": {
        "title": "Sandbox Ledger Reconciliation (demo)",
        "category": "Banking & Finance",
        "files": [("overview.md", "notes", 0), ("reconciliation_notes.md", "meeting notes", 1), ("tasks.csv", "task board", 1)],
    },
    "cybersecurity": {
        "title": "Security Incident Handover Drill (demo)",
        "category": "Cybersecurity",
        "files": [("overview.md", "notes", 0), ("response_notes.md", "meeting notes", 1), ("tasks.csv", "task board", 1)],
    },
    "operations": {
        "title": "Facilities Work-Order Handover (demo)",
        "category": "General Operations",
        "files": [("overview.md", "notes", 0), ("operations_notes.md", "meeting notes", 1), ("tasks.csv", "task board", 1)],
    },
    "education": {
        "title": "Learning Lab Course Handover (demo)",
        "category": "Education",
        "files": [("overview.md", "notes", 0), ("course_notes.md", "meeting notes", 1), ("tasks.csv", "task board", 1)],
    },
}
SPOF_THRESHOLD = 3
DONE_STATUS = re.compile(r"^(?:done|complete[d]?|closed|finished|resolved|shipped|cancel+ed)$", re.I)
REASON_GAP = "The reason for this decision is not recorded: "
OWNER_GAP = "No owner is recorded for "
DRIFT_NOTE = "The source file changed and these words are no longer in it."

TYPE_LABELS = {
    "decision": "Decision",
    "responsibility": "Owner",
    "risk": "Risk",
    "dependency": "Dependency",
    "blocker": "Blocker",
    "open_question": "Open question",
    "next_action": "Next action",
    "contact": "Who to ask",
    "unfinished": "Unfinished work",
    "gap": "Missing information",
}
GRADE_HELP = {
    "Backed": "The quoted words were found in the source.",
    "Testimony": "A person stated this. There is no source passage.",
    "Inferred": "A guess made by the tool. There is no matching quote, so it cannot be approved as fact.",
    "Conflicting": "Two sources disagree. Explain which one you trust before approving.",
    "Unknown": "Something important is missing from the sources.",
}
SECTIONS = [
    ("Project state", ("responsibility", "blocker")),
    ("Unfinished work", ("unfinished",)),
    ("Week-one actions", ("next_action",)),
    ("Who to ask", ("contact",)),
    ("Decisions", ("decision",)),
    ("Risks and dependencies", ("risk", "dependency")),
    ("Open questions and missing information", ("open_question", "gap")),
]

MASKS = [
    ("secret", re.compile(r"\b(?:password|passwd|pwd|token|secret|api[_ ]?key)\b\s*(?:is|=|:)\s*\S+", re.I)),
    ("key", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone", re.compile(r"(?<![\d-])(?:\+\d{1,3}[ -]?)?\d{5}[ -]?\d{5}(?![\d-])")),
]
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
CHAT_PREFIX = re.compile(r"^\[[^\]]*\]\s+[^:]+:\s*")
RULES = [
    ("blocker", re.compile(r"\b(?:blocked|waiting on|waiting for|stuck)\b", re.I)),
    ("decision", re.compile(r"\b(?:decided|agreed|chose|chosen|settled on|approved|switched to)\b|\b(?:I|We|we) (?:added|set|changed|removed)\b")),
    ("risk", re.compile(r"\b(?:risk|worr(?:y|ies|ied)|concern|fragile|single point|might fail|could fail|fails?)\b", re.I)),
    ("dependency", re.compile(r"\b(?:depends on|dependency|relies on|requires)\b", re.I)),
    ("responsibility", re.compile(r"\b(?:owns|owner|responsible for|in charge of|assigned to|maintains|handles)\b", re.I)),
    ("contact", re.compile(r"\b(?:[Aa]sk|[Cc]ontact|[Tt]alk to|[Rr]each out to)\s+[A-Z][a-z]+")),
    ("unfinished", re.compile(r"\b(?:in progress|unfinished|not finished|half[- ]?(?:done|finished)|still (?:working|needs?|to do)|not yet|partially|incomplete)\b", re.I)),
    ("next_action", re.compile(r"\b(?:todo|to do|next step|need to|needs to|must|should|action item)\b", re.I)),
]
OWNER = re.compile(r"\b([A-Z][a-z]+) (?:owns|is responsible for|maintains|handles|is in charge of) ([^.]+)")
RATIONALE = re.compile(r"\b(?:because|since|due to|so that|in order to|reason)\b", re.I)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DEFINITION = r"[^.]{0,40}\b(?:is an?|means|refers to|stands for)\b"
STOPWORDS = frozenset(
    "a about after all also an and any are as at be been but by can could did do does for from had has have he her his how i if in"
    " into is it its just may might more most must new no not of on or our out she should so some than that the their them then"
    " there these they this to up us very was we were what when where which who why will with would you your next masked".split()
)


def mask(text):
    total = 0
    for label, pattern in MASKS:
        text, count = pattern.subn(f"[masked {label}]", text)
        total += count
    return text, total


def find_span(text, quote):
    words = (quote or "").split()
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), text)
    return match.span() if match else None


def normalise(name):
    name = re.sub(r"[^\w\s]", "", name.lower()).strip()
    return re.sub(r"^the\s+", "", name)


def render_json(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    items = data if isinstance(data, list) else [data]
    lines = [
        f"[{item.get('date', '')}] {item.get('author', 'Unknown')}: {item.get('text', item.get('message', ''))}"
        for item in items
        if isinstance(item, dict)
    ]
    return "\n".join(lines) or raw


def prepare(filename, data):
    text = data.decode("utf-8", errors="replace")
    if filename.lower().endswith(".json"):
        text = render_json(text)
    return mask(text)


def recheck_source(source_id, text, user_name):
    stale = [
        claim
        for claim in query(
            "SELECT * FROM claims WHERE source_id = ? AND quote != '' AND status != 'rejected' AND grade != 'Inferred'",
            (source_id,),
        )
        if not find_span(text, claim["quote"])
    ]
    for claim in stale:
        run("UPDATE claims SET grade = 'Inferred', status = 'proposed', note = ?, updated_at = ? WHERE id = ?",
            (DRIFT_NOTE, now(), claim["id"]))
        add_version(claim["id"], "source changed", user_name)
    return len(stale)


def add_source(project_id, filename, source_type, rank, data, user_name="system"):
    text, masked = prepare(filename, data)
    existing = one(
        "SELECT s.id, s.access_rank, COALESCE(MAX(c.access_rank), s.access_rank) AS claim_rank "
        "FROM sources s LEFT JOIN claims c ON c.source_id = s.id "
        "WHERE s.project_id = ? AND s.filename = ? GROUP BY s.id",
        (project_id, filename),
    )
    if not existing:
        source_id = run(
            "INSERT INTO sources(project_id, filename, source_type, access_rank, content, masked_count, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, filename, source_type, rank, text, masked, now()),
        )
        return source_id, masked, None
    # Visibility is a floor, not a replaceable setting: once data has been
    # restricted, re-uploading the filename at a lower level must not make it
    # public. Include existing claim ranks to repair databases created by
    # versions that lowered the source rank while retaining higher-ranked claims.
    effective_rank = max(rank, existing["access_rank"], existing["claim_rank"])
    run_all([
        ("UPDATE sources SET source_type = ?, access_rank = MAX(access_rank, ?), content = ?, "
         "masked_count = ?, uploaded_at = ? WHERE id = ?",
         (source_type, effective_rank, text, masked, now(), existing["id"])),
        ("UPDATE claims SET access_rank = MAX(access_rank, ?) WHERE source_id = ?",
         (effective_rank, existing["id"])),
    ])
    return existing["id"], masked, recheck_source(existing["id"], text, user_name)


def make_claim(kind, statement, quote, grade="Backed", **extra):
    return {"type": kind, "statement": statement, "quote": quote, "grade": grade, "note": "", **extra}


def sentences(text):
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        line = CHAT_PREFIX.sub("", re.sub(r"^\s*(?:[-*>]+|\d+[.)])\s*", "", line))
        for sentence in SENTENCE_END.split(line):
            sentence = sentence.strip()
            if len(sentence) > 12:
                yield sentence


def classify(sentence):
    if sentence.endswith("?"):
        return "open_question"
    for kind, pattern in RULES:
        if pattern.search(sentence):
            return kind
    return None


def csv_claims(row, line):
    task = row.get("task", "").strip()
    owner = row.get("owner", "").strip()
    status = row.get("status", "").strip()
    if not task:
        return []
    claims = []
    if owner:
        text = f"{owner} is responsible for {task} ({status}, due {row.get('due', 'not set')})."
        claims.append(make_claim("responsibility", text, line, area=normalise(task), owner=owner))
    else:
        claims.append(make_claim("gap", f"{OWNER_GAP}{task}.", line, grade="Unknown"))
    if status.lower() == "blocked":
        claims.append(make_claim("blocker", f"{task} is blocked: {row.get('note') or 'no reason recorded'}.", line))
    if status and status.lower() != "blocked" and not DONE_STATUS.match(status):
        who = f" (owner: {owner})" if owner else ""
        claims.append(make_claim("unfinished", f"{task} is not finished: {status}, due {row.get('due') or 'not set'}{who}.", line))
    return claims


def text_claims(sentence, kind):
    claims = [make_claim(kind, sentence, sentence)]
    if kind == "responsibility":
        match = OWNER.search(sentence)
        if match:
            claims[0].update(owner=match.group(1), area=normalise(match.group(2)))
    if kind == "decision" and not RATIONALE.search(sentence):
        claims.append(make_claim("gap", f"{REASON_GAP}{sentence}", sentence, grade="Unknown"))
    return claims


def extract(source):
    text, name = source["content"], source["filename"].lower()
    if name.endswith(".csv"):
        lines = text.splitlines()
        headers = [header.strip().lower() for header in lines[0].split(",")] if lines else []
        claims = []
        for line in lines[1:]:
            if line.strip():
                claims += csv_claims(dict(zip(headers, next(csv.reader([line])))), line.strip())
        return claims
    found = llm_extract(text)
    if found:
        return [make_claim(item["type"], item["statement"], item.get("quote", "")) for item in found]
    claims = []
    for sentence in sentences(text):
        kind = classify(sentence)
        if kind:
            claims += text_claims(sentence, kind)
    return claims


def mark_conflicts(claims):
    owners = {}
    for claim in claims:
        if claim.get("area"):
            owners.setdefault(claim["area"], {}).setdefault(claim["owner"], []).append(claim)
    for area, by_owner in owners.items():
        if len(by_owner) > 1:
            names = ", ".join(sorted(by_owner))
            for group in by_owner.values():
                for claim in group:
                    claim["grade"] = "Conflicting"
                    claim["note"] = f"Sources disagree on who owns {area}: {names}."


def add_single_point_risks(claims):
    counts = Counter(claim["owner"] for claim in claims if claim.get("owner"))
    for owner, total in counts.items():
        if total >= SPOF_THRESHOLD:
            mine = [claim for claim in claims if claim.get("owner") == owner]
            risk = make_claim(
                "risk", f"{owner} owns {total} areas, so they may be a single point of failure.", "", grade="Inferred"
            )
            risk.update(source_id=mine[0]["source_id"], rank=max(claim["rank"] for claim in mine))
            claims.append(risk)


def add_version(claim_id, action, user_name):
    claim = one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    run_all([
        ("DELETE FROM claim_versions WHERE claim_id = ? AND undone = 1", (claim_id,)),
        ("INSERT INTO claim_versions(claim_id, snapshot, action, by_user, at) VALUES (?, ?, ?, ?, ?)",
         (claim_id, snapshot(claim), action, user_name, now())),
    ])


def apply_snapshot(claim_id, text):
    state = json.loads(text)
    run(
        "UPDATE claims SET statement = ?, quote = ?, grade = ?, status = ?, note = ?, updated_at = ? WHERE id = ?",
        (state["statement"], state["quote"], state["grade"], state["status"], state["note"], now(), claim_id),
    )


def undo(claim_id):
    versions = query("SELECT * FROM claim_versions WHERE claim_id = ? AND undone = 0 ORDER BY id DESC LIMIT 2", (claim_id,))
    if len(versions) < 2:
        return False
    run("UPDATE claim_versions SET undone = 1 WHERE id = ?", (versions[0]["id"],))
    apply_snapshot(claim_id, versions[1]["snapshot"])
    return True


def redo(claim_id):
    version = one("SELECT * FROM claim_versions WHERE claim_id = ? AND undone = 1 ORDER BY id LIMIT 1", (claim_id,))
    if not version:
        return False
    run("UPDATE claim_versions SET undone = 0 WHERE id = ?", (version["id"],))
    apply_snapshot(claim_id, version["snapshot"])
    return True


def regrade(claim, quote):
    if claim["grade"] not in ("Backed", "Inferred"):
        return claim["grade"]
    source = one("SELECT content FROM sources WHERE id = ?", (claim["source_id"],))
    return "Backed" if find_span(source["content"], quote) else "Inferred"


def analyse(project_id, user_name):
    run("DELETE FROM claim_versions WHERE claim_id IN (SELECT id FROM claims WHERE project_id = ?)", (project_id,))
    run("DELETE FROM claims WHERE project_id = ?", (project_id,))
    claims = []
    for source in query("SELECT * FROM sources WHERE project_id = ? ORDER BY id", (project_id,)):
        for claim in extract(source):
            claim.update(source_id=source["id"], rank=source["access_rank"])
            if claim["grade"] == "Backed" and not find_span(source["content"], claim["quote"]):
                claim["grade"] = "Inferred"
                claim["note"] = "The quoted words were not found in the source, so this claim was downgraded."
            claims.append(claim)
    mark_conflicts(claims)
    add_single_point_risks(claims)
    for claim in claims:
        claim_id = run(
            "INSERT INTO claims(project_id, source_id, type, statement, quote, grade, status, access_rank, note,"
            " created_at, updated_at, owner, area) VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?)",
            (project_id, claim["source_id"], claim["type"], claim["statement"], claim["quote"], claim["grade"],
             claim["rank"], claim["note"], now(), now(), claim.get("owner", ""), claim.get("area", "")),
        )
        add_version(claim_id, "found", "system")
    return len(claims)


def load_demo(user_name, key="events"):
    demo = DEMOS[key]
    project_id = run(
        "INSERT INTO projects(name, created_by, created_at, category) VALUES (?, ?, ?, ?)",
        (demo["title"], user_name, now(), demo.get("category", "General Operations")),
    )
    for filename, source_type, rank in demo["files"]:
        add_source(project_id, filename, source_type, rank, (SAMPLE_DIR / key / filename).read_bytes())
    analyse(project_id, user_name)
    return project_id


def delete_project(project_id):
    run_all([
        ("DELETE FROM successor_submissions WHERE project_id = ?", (project_id,)),
        ("DELETE FROM project_requests WHERE project_id = ?", (project_id,)),
        ("DELETE FROM project_assignments WHERE project_id = ?", (project_id,)),
        ("DELETE FROM tracker WHERE share_id IN (SELECT id FROM shares WHERE project_id = ?)", (project_id,)),
        ("DELETE FROM claim_versions WHERE claim_id IN (SELECT id FROM claims WHERE project_id = ?)", (project_id,)),
        ("DELETE FROM claims WHERE project_id = ?", (project_id,)),
        ("DELETE FROM shares WHERE project_id = ?", (project_id,)),
        ("DELETE FROM sources WHERE project_id = ?", (project_id,)),
        ("DELETE FROM projects WHERE id = ?", (project_id,)),
    ])


def set_tracker(share_id, claim_id, state, note=""):
    run(
        "INSERT INTO tracker(share_id, claim_id, state, note, reply, updated_at) VALUES (?, ?, ?, ?, '', ?)"
        " ON CONFLICT(share_id, claim_id) DO UPDATE SET state = excluded.state, note = excluded.note,"
        " reply = '', updated_at = excluded.updated_at",
        (share_id, claim_id, state, note, now()),
    )


def plan_sections(project_id, clearance):
    rows = query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id"
        " WHERE c.project_id = ? AND c.status = 'approved' AND c.access_rank <= ? ORDER BY c.id",
        (project_id, clearance),
    )
    sections = [(title, [row for row in rows if row["type"] in kinds]) for title, kinds in SECTIONS]
    return [(title, items) for title, items in sections if items]


def claim_date(claim, content):
    for text in (claim["quote"], claim["statement"]):
        match = ISO_DATE.search(text or "")
        if match:
            return match.group()
    span = find_span(content, claim["quote"])
    if not span:
        return None
    start = content.rfind("\n", 0, span[0]) + 1
    end = content.find("\n", span[1])
    match = ISO_DATE.search(content[start : end if end != -1 else len(content)])
    return match.group() if match else None


def timeline(project_id, clearance):
    rows = query(
        "SELECT c.*, s.filename, s.content FROM claims c JOIN sources s ON s.id = c.source_id"
        " WHERE c.project_id = ? AND c.status = 'approved' AND c.access_rank <= ?",
        (project_id, clearance),
    )
    dated = [(claim_date(row, row["content"]), row["id"], row) for row in rows]
    groups = {}
    for date, _, row in sorted((item for item in dated if item[0]), key=lambda item: item[:2]):
        groups.setdefault(date, []).append(row)
    return list(groups.items())


def question_for(claim):
    statement = claim["statement"]
    if statement.startswith(REASON_GAP):
        return "Why was this decided? " + statement[len(REASON_GAP):]
    if statement.startswith(OWNER_GAP):
        return f"Who owns {statement[len(OWNER_GAP):].rstrip('.')}?"
    return statement


def open_questions(project_id):
    rows = query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id"
        " WHERE c.project_id = ? AND c.status != 'rejected' AND (c.grade = 'Unknown' OR c.type = 'open_question')"
        " ORDER BY c.id",
        (project_id,),
    )
    return [(row, question_for(row)) for row in rows]


def bigrams(text):
    for sentence in sentences(text):
        for chunk in re.split(r"[.,;:()?!]", sentence.lower()):
            run_of_words = []
            for word in re.findall(r"[a-z][a-z-]*", chunk) + [""]:
                if word and word not in STOPWORDS and len(word) > 2:
                    run_of_words.append(word)
                else:
                    yield from (f"{a} {b}" for a, b in zip(run_of_words, run_of_words[1:]))
                    run_of_words = []


def dark_matter(project_id, limit=8):
    sources = query("SELECT filename, content FROM sources WHERE project_id = ?", (project_id,))
    owned = " ".join(
        row["statement"].lower()
        for row in query("SELECT statement FROM claims WHERE project_id = ? AND type = 'responsibility'", (project_id,))
    )
    everything = " ".join(source["content"] for source in sources).lower()
    mentions, where = Counter(), {}
    for source in sources:
        for term in bigrams(source["content"]):
            mentions[term] += 1
            where.setdefault(term, set()).add(source["filename"])
    found = [
        {"term": term, "mentions": count, "sources": sorted(where[term])}
        for term, count in mentions.items()
        if len(where[term]) > 1 and term not in owned and not re.search(re.escape(term) + DEFINITION, everything)
    ]
    found.sort(key=lambda item: (-len(item["sources"]), -item["mentions"], item["term"]))
    chosen = []
    for item in found:
        words, places = set(item["term"].split()), set(item["sources"])
        if not any(words & set(other["term"].split()) and places <= set(other["sources"]) for other in chosen):
            chosen.append(item)
    return chosen[:limit]


def search_claims(project_id, text, clearance, approved_only):
    pattern = "%" + re.sub(r"([\\%_])", r"\\\1", text.strip()[:100]) + "%"
    return query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ?"
        " AND c.access_rank <= ? AND (? = 0 OR c.status = 'approved')"
        " AND (c.statement LIKE ? ESCAPE '\\' OR c.quote LIKE ? ESCAPE '\\' OR c.note LIKE ? ESCAPE '\\')"
        " ORDER BY c.id LIMIT 50",
        (project_id, clearance, int(approved_only), pattern, pattern, pattern),
    )


def knowledge_map(project_id):
    owners = {}
    for row in query(
        "SELECT owner, area FROM claims WHERE project_id = ? AND status != 'rejected' AND owner != '' AND area != ''",
        (project_id,),
    ):
        owners.setdefault(row["owner"], set()).add(row["area"])
    total = len(set().union(*owners.values())) if owners else 0
    people = [
        {"name": name, "areas": sorted(areas), "count": len(areas), "share": round(100 * len(areas) / total),
         "at_risk": len(areas) >= SPOF_THRESHOLD}
        for name, areas in owners.items()
    ]
    return sorted(people, key=lambda person: (-person["count"], person["name"]))


def recurring_problems(project_id, clearance=2, approved_only=False, limit=6):
    rows = query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ?"
        " AND c.type IN ('risk', 'blocker') AND c.status != 'rejected' AND c.access_rank <= ?"
        " AND (? = 0 OR c.status = 'approved') ORDER BY c.id",
        (project_id, clearance, int(approved_only)),
    )
    by_term = {}
    for row in rows:
        for term in set(bigrams(row["statement"])):
            by_term.setdefault(term, []).append(row)
    groups = [
        {"term": term, "claims": items}
        for term, items in by_term.items()
        if len({item["filename"] for item in items}) > 1
    ]
    groups.sort(key=lambda group: (-len(group["claims"]), group["term"]))
    chosen = []
    for group in groups:
        ids = {item["id"] for item in group["claims"]}
        if not any(ids <= {item["id"] for item in other["claims"]} for other in chosen):
            chosen.append(group)
    return chosen[:limit]


def rehearsal(project_id, clearance=1):
    claims = query("SELECT * FROM claims WHERE project_id = ? AND status != 'rejected' ORDER BY id", (project_id,))

    def problem(claim, needs_answer=False):
        if claim["status"] != "approved":
            return "Not approved yet"
        if claim["access_rank"] > clearance:
            return "Hidden from the successor"
        if claim["grade"] == "Inferred":
            return "Only a guess"
        if claim["grade"] == "Unknown":
            return "Nothing is recorded"
        if needs_answer and claim["grade"] != "Testimony":
            return "Nobody has answered this"
        return ""

    questions = []

    def ask(text, needed=(), answers=()):
        reasons = [problem(claim) for claim in needed] + [problem(claim, True) for claim in answers]
        reason = next((item for item in reasons if item), "")
        questions.append({"question": text, "answered": not reason, "reason": reason})

    decisions = {(claim["source_id"], claim["quote"]) for claim in claims if claim["type"] == "decision"}
    gaps = [claim for claim in claims if claim["type"] == "gap"]
    for claim in claims:
        kind = claim["type"]
        if kind == "decision":
            related = [gap for gap in gaps if (gap["source_id"], gap["quote"]) == (claim["source_id"], claim["quote"])]
            ask("Why was this decided? " + claim["statement"], [claim], related)
        elif kind == "gap" and (claim["source_id"], claim["quote"]) not in decisions:
            ask(question_for(claim), answers=[claim])
        elif kind == "responsibility":
            ask(f"Who owns {claim['area'] or claim['statement']}?", [claim])
        elif kind == "blocker":
            ask("What is blocking this? " + claim["statement"], [claim])
        elif kind == "unfinished":
            ask("What is left to do? " + claim["statement"], [claim])
        elif kind == "open_question":
            ask(claim["statement"], answers=[claim])
    for kind, text in (("next_action", "What should I do first?"), ("contact", "Who can I ask for help?")):
        found = any(not problem(claim) for claim in claims if claim["type"] == kind)
        questions.append({"question": text, "answered": found, "reason": "" if found else "No approved item the successor can see"})
    merged = {}
    for item in questions:
        earlier = merged.get(item["question"])
        if earlier is None or (earlier["answered"] and not item["answered"]):
            merged[item["question"]] = item
    questions = sorted(merged.values(), key=lambda item: item["answered"])
    answered = sum(1 for item in questions if item["answered"])
    return {"score": round(100 * answered / len(questions)) if questions else None, "answered": answered, "questions": questions}


def evaluate(key):
    planted = json.loads((SAMPLE_DIR / key / "planted.json").read_text())
    project_id = load_demo("self-check", key)
    try:
        claims = query("SELECT c.*, s.content FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ?", (project_id,))
        quoted = [claim for claim in claims if claim["quote"]]
        found_quotes = [claim for claim in quoted if find_span(claim["content"], claim["quote"])]
        gaps = [(text, any(text in claim["statement"] for claim in claims if claim["grade"] == "Unknown")) for text in planted["expected_gaps"]]
        conflicts = [(text, any(text in claim["note"] for claim in claims if claim["grade"] == "Conflicting")) for text in planted["expected_conflicts"]]
        run("UPDATE claims SET status = 'approved' WHERE project_id = ? AND grade != 'Inferred'", (project_id,))
        shown = " ".join(
            f"{claim['statement']} {claim['quote']} {claim['note']}"
            for _, items in plan_sections(project_id, 1) for claim in items
        ) + " ".join(claim["statement"] for _, items in timeline(project_id, 1) for claim in items)
        stored = " ".join(row["content"] for row in query("SELECT content FROM sources WHERE project_id = ?", (project_id,)))
        return {
            "title": DEMOS[key]["title"],
            "claims": len(claims),
            "quotes": (len(found_quotes), len(quoted)),
            "gaps": gaps,
            "conflicts": conflicts,
            "leaks": [text for text in planted["restricted"] if text.lower() in shown.lower()],
            "restricted_total": len(planted["restricted"]),
            "exposed": [text for text in planted["secrets"] if text in stored],
            "secrets_total": len(planted["secrets"]),
            "rehearsal": rehearsal(project_id)["score"],
        }
    finally:
        delete_project(project_id)
