# Round 2 PDF requirements audit

## Overall verdict

The attached PDF describes the Round 2 build. The current project is a later Round 3 build, so the PDF's historical statuses are not the current statuses.

Current verification:

- **37 of 37 planned deliverables: verified complete**
- Full current automated suite: **103 passed**
- Python compilation: passed
- Template/static asset audit: passed
- Live login, main project pages, and all six export formats: passed

The formerly partial **knowledge-at-risk map** is now complete for supported repository evidence: it parses git-log text or JSON commit exports, combines author/path activity with claim ownership, and shows the evidence source in the reviewer view.

## Feature-by-feature status

| # | Feature | Current status | Evidence / remaining gap |
|---:|---|---|---|
| 1 | Claim ledger | Verified complete | SQLite schema stores claims, quotes, grades, access, status, notes, owners, areas, timestamps, and versions. Tests cover history, undo/redo, grades, and deletion. |
| 2 | Source ingestion and masking | Verified complete | Supports TXT, Markdown, CSV, and JSON, with a 200 KB limit, access levels, and masking for emails, phones, passwords, and keys. Masking is heuristic, not perfect for every secret format. |
| 3 | Project-knowledge extraction | Verified complete | Nine claim types are supported with rule extraction and optional AI extraction. The live Anthropic path is not validated in this environment. |
| 4 | Quote verification and grades | Verified complete | Source quotes are checked with whitespace-tolerant matching. Missing quotes are downgraded; Backed, Testimony, Inferred, Conflicting, and Unknown are implemented. |
| 5 | Click-to-evidence viewer | Verified complete | Evidence pages highlight the matching source passage and enforce approval/clearance rules. |
| 6 | Timeline | Verified complete | ISO dates are extracted and ordered with clearance filtering. Only ISO `YYYY-MM-DD` date formats are recognized. |
| 7 | Project State page | Verified complete | Round 3 added cross-source entities, owners, blockers, decisions, actions, trails, aliases, and restricted-view filtering. |
| 8 | Review workflow | Verified complete | Edit, reject, approve, answer, conflict reasons, approval restrictions, versions, undo/redo, and sharing readiness gates are implemented and tested. |
| 9 | Roles and controlled sharing | Verified complete | Reviewer/successor permissions, database-level clearance filtering, exclusive assignment, expiry, revoke, and successor preview are implemented. |
| 10 | Acknowledgement and action tracker | Verified complete | Actions support completion, unclear/send-back, replies, and named assignees. Round 3 added per-section quizzes and acknowledgement gates. |
| 11 | Audit log and version history | Verified complete | Activity log, claim snapshots, word-level diffs, and shared-plan view logging are implemented. View logging is intentionally deduplicated per page per minute. |
| 12 | Login | Verified complete | Reviewer and successor accounts, successor registration, team accounts, and later leaver accounts are implemented. |
| 13 | Session timeout | Verified complete | Signed session cookie with an eight-hour absolute lifetime. It is not idle-timeout based. |
| 14 | Password hashing | Verified complete | Salted PBKDF2-SHA256 with constant-time verification and malformed-hash protection. |
| 15 | Hero and one-click demo | Verified complete | Hero, demo entry, seeded demo accounts, and demo project loading are implemented. |
| 16 | Light/dark mode | Verified complete | Theme switching exists and both themes are covered by automated accessibility checks. |
| 17 | Help drawer | Verified complete | Help UI and Escape-to-close behavior are implemented. |
| 18 | First-run guided tour | Verified complete | Start, later, and do-not-ask-again choices are persisted and tested. |
| 19 | Animations | Verified complete | Motion/polish effects include reduced-motion support. |
| 20 | Notifications | Verified complete | Covers sharing, assignment, replies, send-backs, removal, source changes, failed-login security findings, interview answers, acknowledgements, and completion workflows. Notifications are in-app only. |
| 21 | Report layout and PDF | Verified complete | The app now generates a real PDF through `simplepdf.py`; it also supports browser printing. The PDF layout is intentionally minimal Helvetica text. |
| 22 | Excel export | Verified complete | Generates Plan and Summary sheets, a grade chart, filtered content, and formula-injection protection. |
| 23 | JSON export | Verified complete | Valid, clearance-filtered JSON with approval metadata. |
| 24 | Word export | Verified complete | Generates valid DOCX files and is tested by reopening the output. |
| 25 | XML export | Verified complete | Generates parseable XML. No formal XSD validation is included. |
| 26 | CSV export | Verified complete | One row per claim with formula-injection protection. |
| 27 | Charts of grades, risks, and gaps | Verified complete | Web overview includes grade/type/open-work visual bars; Excel includes a grade chart. The web version uses server-rendered bars rather than a chart library. |
| 28 | Search | Verified complete | Parameterized keyword search over claim content with clearance and approval filtering. It is LIKE search, not FTS5. |
| 29 | Empty/error states | Verified complete | Global error rendering and empty states are present and covered by browser/a11y checks. |
| 30 | Data deletion | Verified complete | Reviewer deletion removes project data, including Round 3 tables such as quizzes, views, aliases, leavers, submissions, and assignments. |
| 31 | Accessibility checks | Verified complete | axe/Chromium checks cover themes, roles, viewports, pages, forms, focus, reduced motion, and keyboard controls. A human screen-reader test has not been performed. |
| 32 | Data-use notice | Verified complete | Public `/data-use` page explains masking, storage, optional AI, Google Fonts, and deletion. |
| 33 | Targeted leaver questions | Verified complete | Leaver Interview Mode generates questions from gaps, open questions, blockers, dark matter, and concentrated ownership; answers become Testimony. |
| 34 | Knowledge-at-risk map | Verified complete | The app flags concentrated ownership from handover claims and supported repository git-log/JSON commit metadata, including author names, changed paths, commit counts, and evidence source. |
| 35 | Continuity Rehearsal | Verified complete | Generates successor questions, scores answerability, filters by clearance, and blocks sharing while critical questions remain unanswered. |
| 36 | Dark-Matter Detector | Verified complete | Finds repeated unexplained/unowned phrases across sources without using a model. |
| 37 | Drift detection | Verified complete | Replacing a source downgrades claims whose quotes disappear, versions them as source-changed, and sends notifications. |

## Round 3 commitments

All three major Round 3 commitments are implemented and tested:

1. **Leaver Interview Mode** — scoped leaver login, restricted routes, targeted questions, answers, Testimony, coverage, and self-approved labeling.
2. **Cross-source links and Project State** — entities, trails, aliases, clearance filtering, owner mismatch checks, no-owner checks, and decision-without-follow-up checks.
3. **Comprehension Check** — section quizzes, 80% pass mark, retries, cited wrong-answer evidence, per-section acknowledgement, whole-plan acknowledgement gate, and reviewer results.

The supporting Round 3 housekeeping items are also implemented: data-use notice, generated PDF, web overview charts, secure cookie behavior, AI retry-once behavior, prompt-injection tests, additional notifications, shared-plan view logs, and self-approved labels.

## Remaining limitations

These are not unimplemented core features, but they remain limitations or unverified areas:

- Repository metadata is supported through uploaded git-log text or JSON commit exports; direct live Git provider synchronization is not included.
- The live Anthropic API path has not been tested; the app works with the rule-based extractor when no key is configured.
- No OWASP ZAP baseline scan has been run.
- The login rate limiter is in memory and resets on restart; it is not shared across workers.
- Accessibility evidence is automated; no human screen-reader or keyboard-only trial has been completed.
- The seven demos use synthetic planted data, so they prove the mechanics but not accuracy on arbitrary real projects.
- No independent classmate/usability handover trial is included.
- Production deployment review, backups, retention policies, and external notification delivery are outside this build.

## Current live demo

https://8001-ido3005ltpmp3n0o6keqa-4c39a963.sg2.manus.computer/

Demo accounts:

- Reviewer: `reviewer` / `reviewer123`
- Successor: `successor` / `successor123`
