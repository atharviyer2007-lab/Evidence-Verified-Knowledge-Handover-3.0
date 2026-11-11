"""Seed the successor project library with synthetic demo projects.

Run from this folder with the project's virtual environment active:
    python seed_demo_board.py

Set HANDOVER_DB to choose a different database path. Re-running this script does
not duplicate demo projects; it refreshes their safe public briefs.
"""

import db
import pipeline

PUBLIC_BRIEFS = {
    "events": {
        "summary": "Complete the event registration flow, resolve ownership gaps, and test the handover actions. Synthetic data only.",
        "scope": "Review the registration workflow, fill documentation gaps, test the primary user path, and assign remaining actions.",
        "skills": "Software testing, user experience, documentation, and workflow design.",
        "outcome": "A tested registration handover with clear owners, known risks, and sequenced follow-up actions.",
    },
    "club": {
        "summary": "Finish the club membership and equipment-booking handover, confirm open responsibilities, and divide remaining tasks.",
        "scope": "Clarify membership operations, document equipment booking, and confirm who owns recurring club activities.",
        "skills": "Community coordination, process documentation, and basic scheduling.",
        "outcome": "A practical club operations guide with assigned owners and a week-one checklist.",
    },
    "healthcare": {
        "summary": "Synthetic clinic scheduling example: resolve referral-import gaps and document reminder and escalation checks. No patient data.",
        "scope": "Review a fictional referral-import workflow, document after-hours escalation, and complete safe reminder checks.",
        "skills": "Healthcare operations, process mapping, quality assurance, and privacy-aware documentation.",
        "outcome": "A validated synthetic workflow map, documented escalation route, and prioritized test checklist.",
    },
    "banking": {
        "summary": "Synthetic finance sandbox: finish ledger reconciliation controls and document exception approvals. No account records.",
        "scope": "Complete sample ledger reconciliation controls, document approval steps, and test repeated-file protection.",
        "skills": "Process controls, reconciliation, spreadsheet analysis, and audit-friendly documentation.",
        "outcome": "A documented sample reconciliation procedure with exception owners and control checks.",
    },
    "cybersecurity": {
        "summary": "Synthetic tabletop exercise: finish incident escalation and evidence-retention handoff steps. No live incident data.",
        "scope": "Complete a tabletop response checklist, clarify escalation ownership, and document evidence-retention steps.",
        "skills": "Security operations, incident coordination, tabletop facilitation, and clear decision logs.",
        "outcome": "A reviewed exercise runbook with named roles, escalation steps, and closure criteria.",
    },
    "operations": {
        "summary": "Synthetic facilities example: complete open work orders, confirm backup ownership, and document weekly operations.",
        "scope": "Prioritize fictional work orders, document the weekly triage routine, and fill backup-owner gaps.",
        "skills": "Operations coordination, service tracking, prioritization, and procedural writing.",
        "outcome": "A usable work-order handover with a clear weekly checklist and backup responsibilities.",
    },
    "education": {
        "summary": "Synthetic learning-support example: update the course handover guide and confirm a backup facilitator. No learner records.",
        "scope": "Update a fictional course-support guide, check the next-term schedule, and assign backup facilitation.",
        "skills": "Education support, content editing, schedule coordination, and accessible documentation.",
        "outcome": "A current course-support pack, named backup owner, and ready-to-use next-term checklist.",
    },
}


def seed_demo_board():
    db.init_db()
    seeded = []
    for key, brief in PUBLIC_BRIEFS.items():
        title = pipeline.DEMOS[key]["title"]
        existing = db.one("SELECT id FROM projects WHERE name = ? ORDER BY id LIMIT 1", (title,))
        project_id = existing["id"] if existing else pipeline.load_demo("Demo seed", key)
        db.run(
            "UPDATE projects SET listing_enabled = 1, public_summary = ?, category = ?, public_scope = ?, "
            "public_skills = ?, public_outcome = ? WHERE id = ?",
            (brief["summary"], pipeline.DEMOS[key]["category"], brief["scope"], brief["skills"], brief["outcome"], project_id),
        )
        open_items = db.one(
            "SELECT COUNT(*) AS n FROM claims WHERE project_id = ? AND status != 'rejected' "
            "AND (status = 'proposed' OR grade = 'Unknown' OR type IN ('unfinished','blocker') "
            "OR (type IN ('open_question','gap') AND instr(statement, 'Answer:') = 0))",
            (project_id,),
        )["n"]
        seeded.append((project_id, title, open_items))
    return seeded


if __name__ == "__main__":
    for project_id, title, open_items in seed_demo_board():
        print(f"Published #{project_id}: {title} ({open_items} open items)")
