"""Cross-source links and the Project State page.

Everything here is derived from claims and source text on demand, so it can never drift from
the review decisions. Claims are loaded at the viewer's clearance first, and entities are built
only from what was loaded: an entity whose every claim is restricted does not exist for a
successor, and its name never reaches their page.
"""

import re
from collections import defaultdict

import pipeline
from db import query

ID_PATTERN = re.compile(r"\b[A-Z]{2,6}-\d{1,6}\b")
AUTHOR_LINE = re.compile(r"^\[[^\]]*\]\s+([A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+)?):", re.M)
CONTACT_NAME = re.compile(r"\b(?:Ask|Contact|Talk to|Reach out to|ask|contact)\s+([A-Z][a-z]{2,})")
STATUS_IN_OWNER = re.compile(r"\((?P<s>[^,()]+), due (?P<d>\d{4}-\d{2}-\d{2}|not set)\)")
STATUS_IN_UNFINISHED = re.compile(r"is not finished: (?P<s>[^,]+), due (?P<d>\d{4}-\d{2}-\d{2}|not set)")
GENERIC = frozenset(
    "decided agreed chose chosen team because after before about from with that this have been will would should need needs "
    "next step reason weekly single form plan".split()
)
FOLLOW_UP_TYPES = ("next_action", "unfinished", "responsibility", "blocker")
KINDS = ("area", "person", "id")
KIND_LABELS = {"area": "Work area or system", "person": "Person", "id": "Identifier"}


def _plain(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", "", (text or "").lower())).strip()


def _title(name):
    return name[:1].upper() + name[1:] if name else name


def load_claims(project_id, clearance, approved_only):
    return query(
        "SELECT c.*, s.filename FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.project_id = ? "
        "AND c.status != 'rejected' AND c.access_rank <= ? AND (? = 0 OR c.status = 'approved') ORDER BY c.id",
        (project_id, clearance, int(approved_only)),
    )


def load_aliases(project_id):
    canonical, aliases = {}, defaultdict(list)
    for row in query("SELECT * FROM entity_aliases WHERE project_id = ? ORDER BY id", (project_id,)):
        canonical[(row["kind"], row["alias"])] = row["canonical"]
        aliases[(row["kind"], _alias_key(row["kind"], row["canonical"]))].append(row["alias"])
    return canonical, aliases


def _alias_key(kind, name):
    return _plain(name) if kind == "area" else (name or "").strip().lower()


def _canon(kind, name, canonical):
    key = _alias_key(kind, name)
    return canonical.get((kind, key), _plain(name) if kind == "area" else (name or "").strip())


def _mentions(claim, kind, name, aliases):
    """True when the claim is about this entity, by its own owner or area field or by words in its text."""
    names = [name, *aliases]
    text = f"{claim['statement']} {claim['quote']}"
    if kind == "area":
        flat = _plain(text)
        targets = [_plain(item) for item in names if len(_plain(item)) >= 4]
        if _plain(claim["area"]) in targets:
            return True
        return any(re.search(r"(?<![\w-])" + re.escape(target) + r"(?![\w-])", flat) for target in targets)
    if kind == "person":
        if (claim["owner"] or "").strip().lower() in {item.lower() for item in names}:
            return True
        return any(re.search(r"(?<!\w)" + re.escape(item) + r"(?!\w)", text, re.I) for item in names if len(item) >= 3)
    return any(item in text for item in names)


def _author_of(claim, content):
    """Who wrote the chat line this claim's quote sits on (empty when the source is not a chat export)."""
    span = pipeline.find_span(content or "", claim["quote"])
    if not span:
        return ""
    start = content.rfind("\n", 0, span[0]) + 1
    match = AUTHOR_LINE.match(content[start : content.find("\n", span[1]) if content.find("\n", span[1]) != -1 else len(content)])
    return match.group(1) if match else ""


def _claim_date(claim, sources_by_id):
    return pipeline.claim_date(claim, sources_by_id.get(claim["source_id"], ""))


def build(project_id, clearance, approved_only):
    """All entities visible at this clearance, each with the claims that mention it."""
    claims = load_claims(project_id, clearance, approved_only)
    sources = {
        row["id"]: row for row in query(
            "SELECT id, filename, content FROM sources WHERE project_id = ? AND access_rank <= ?", (project_id, clearance))
    }
    sources_text = {key: row["content"] for key, row in sources.items()}
    canonical, alias_lists = load_aliases(project_id)
    authors = {claim["id"]: _author_of(claim, sources_text.get(claim["source_id"], "")) for claim in claims}

    wanted = {"area": {}, "person": {}, "id": {}}

    def want(kind, name, display=None):
        wanted[kind].setdefault(_alias_key(kind, name), (name, display or name))

    for claim in claims:
        if claim["area"]:
            name = _canon("area", claim["area"], canonical)
            want("area", name, _title(name))
        if claim["statement"].startswith(pipeline.OWNER_GAP):
            task = _plain(claim["statement"][len(pipeline.OWNER_GAP):].rstrip("."))
            name = _canon("area", task, canonical)
            if len(name) >= 4:
                want("area", name, _title(name))
        if claim["owner"]:
            want("person", _canon("person", claim["owner"], canonical))
        for match in CONTACT_NAME.finditer(claim["statement"]):
            want("person", _canon("person", match.group(1), canonical))
        for match in ID_PATTERN.finditer(f"{claim['statement']} {claim['quote']}"):
            want("id", match.group())
    for row in sources.values():
        for match in AUTHOR_LINE.finditer(row["content"]):
            want("person", _canon("person", match.group(1), canonical))

    entities = []
    for kind in KINDS:
        for key, (name, display) in wanted[kind].items():
            alias_names = alias_lists.get((kind, key), [])
            linked = [claim for claim in claims if _mentions(claim, kind, name, alias_names)]
            if kind == "person":
                mine = {name.lower(), *[alias.lower() for alias in alias_names]}
                linked += [claim for claim in claims if claim not in linked and authors.get(claim["id"], "").lower() in mine]
            if not linked:
                continue
            entities.append(_summarise(kind, name, display, alias_names, linked, claims, sources_text))
    order = {"area": 0, "person": 1, "id": 2}
    entities.sort(key=lambda e: (order[e["kind"]], -len(e["sources"]), -len(e["claims"]), e["display"].lower()))
    return entities


def _summarise(kind, name, display, alias_names, linked, claims, sources_text):
    files = sorted({claim["filename"] for claim in linked})
    owners = []
    if kind == "area":
        seen = set()
        for claim in linked:
            if claim["owner"] and (claim["owner"], claim["filename"]) not in seen:
                seen.add((claim["owner"], claim["filename"]))
                owners.append({"name": claim["owner"], "file": claim["filename"], "claim": claim})
    status, due = _status(linked) if kind == "area" else ("", "")
    blockers = [claim for claim in linked if claim["type"] == "blocker"]
    decisions = [claim for claim in linked if claim["type"] == "decision"]
    actions = [claim for claim in linked if claim["type"] in ("next_action", "unfinished")]

    def when(claim):
        return (_claim_date(claim, sources_text) or "", claim["id"])

    trail = sorted(linked, key=when)
    areas = []
    if kind == "person":
        mine = {name.lower(), *[alias.lower() for alias in alias_names]}
        areas = sorted({claim["area"] for claim in claims if claim["owner"] and claim["owner"].strip().lower() in mine and claim["area"]})
    return {
        "kind": kind, "name": name, "display": display, "aliases": alias_names, "claims": linked, "sources": files,
        "owners": owners, "owner_names": sorted({item["name"] for item in owners}), "status": status, "due": due,
        "blockers": blockers, "decision": max(decisions, key=when) if decisions else None, "actions": actions,
        "trail": [(_claim_date(claim, sources_text), claim) for claim in trail], "areas": [_title(item) for item in areas],
        "cross_source": len(files) > 1,
    }


def _status(linked):
    if any(claim["type"] == "blocker" for claim in linked):
        return "Blocked", _first_due(linked)
    for claim in linked:
        match = STATUS_IN_UNFINISHED.search(claim["statement"])
        if match:
            return match.group("s").strip().capitalize(), match.group("d")
    for claim in linked:
        match = STATUS_IN_OWNER.search(claim["statement"])
        if match:
            return match.group("s").strip().capitalize(), match.group("d")
    return "No status recorded", ""


def _first_due(linked):
    for claim in linked:
        for pattern in (STATUS_IN_UNFINISHED, STATUS_IN_OWNER):
            match = pattern.search(claim["statement"])
            if match:
                return match.group("d")
    return ""


def find(project_id, clearance, approved_only, kind, name):
    for entity in build(project_id, clearance, approved_only):
        if entity["kind"] == kind and entity["name"] == name:
            return entity
    return None


# ---- the three cross-source checks (reviewer view) -------------------------------------------

def _content_words(text):
    return {word for word in re.findall(r"[a-z]{4,}", (text or "").lower()) if word not in pipeline.STOPWORDS and word not in GENERIC}


def checks(project_id):
    """Owner mismatch across sources, tasks with no owner, decisions with no follow-up action."""
    claims = load_claims(project_id, 2, False)
    canonical, alias_lists = load_aliases(project_id)
    flags = []

    by_area = defaultdict(list)
    for claim in claims:
        if claim["area"] and claim["owner"]:
            by_area[_canon("area", claim["area"], canonical)].append(claim)
    for area, group in sorted(by_area.items()):
        owners = {_canon("person", claim["owner"], canonical) for claim in group}
        files = {claim["filename"] for claim in group}
        if len(owners) > 1 and len(files) > 1:
            parts = sorted({f"{_canon('person', claim['owner'], canonical)} ({claim['filename']})" for claim in group})
            flags.append({"kind": "owner_mismatch", "title": "Different owners in different files", "entity": ("area", area),
                          "message": f"{_title(area)} has more than one owner: " + ", ".join(parts) + ".",
                          "claims": [claim["id"] for claim in group]})

    for claim in claims:
        if not claim["statement"].startswith(pipeline.OWNER_GAP):
            continue
        task = claim["statement"][len(pipeline.OWNER_GAP):].rstrip(".")
        area = _canon("area", task, canonical)
        named = [other for other in by_area.get(area, [])]
        if named:
            who = ", ".join(sorted({other["owner"] for other in named}))
            message = f"{task} has no owner in {claim['filename']}, but {named[0]['filename']} says {who}. Confirm it."
        else:
            message = f"{task} has no owner in any file."
        flags.append({"kind": "no_owner", "title": "Task with no owner", "entity": ("area", area), "message": message, "claims": [claim["id"]]})

    entities = [entity for entity in build(project_id, 2, False) if entity["kind"] in ("area", "id")]
    follow_ups = [claim for claim in claims if claim["type"] in FOLLOW_UP_TYPES]
    for claim in claims:
        if claim["type"] != "decision":
            continue
        words = _content_words(claim["statement"])
        linked = False
        for other in follow_ups:
            if other["id"] != claim["id"] and len(words & _content_words(other["statement"])) >= 2:
                linked = True
                break
        if not linked:
            linked = any(
                entity for entity in entities
                if _mentions(claim, entity["kind"], entity["name"], entity["aliases"])
                and any(other["id"] != claim["id"] and other["type"] in FOLLOW_UP_TYPES for other in entity["claims"])
            )
        if not linked:
            flags.append({"kind": "decision_no_action", "title": "Decision with no follow-up", "entity": None,
                          "message": f"No next action, owner or unfinished task follows from: {claim['statement']}", "claims": [claim["id"]]})
    return flags


def leak_text(project_id):
    """Everything a successor-level Project State page would print (used by the self-check's leak test)."""
    parts = []
    for entity in build(project_id, 1, True):
        parts += [entity["display"], entity["status"], *entity["owner_names"], *entity["aliases"]]
        parts += [f"{claim['statement']} {claim['quote']} {claim['note']}" for claim in entity["claims"]]
    return " ".join(parts)
