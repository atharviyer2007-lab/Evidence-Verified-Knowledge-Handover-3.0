# Handover v3 review and fixes

## Result

The project was reviewed, corrected, and verified.

- Full automated suite: **103 passed**
- Python compilation: passed
- Template audit: no missing rendered templates
- Static asset audit: passed
- Live login flow: passed
- Live project pages: passed
- Live exports: JSON, CSV, XLSX, DOCX, XML, and PDF all returned HTTP 200
- Repository git-log author/path evidence feeds the knowledge-at-risk map

## Fix applied

The session cookie previously used `SameSite=Lax` unconditionally. That can prevent authentication cookies from being sent when the app is embedded in an HTTPS preview iframe.

The configuration now uses:

- Secure HTTPS deployment: `SameSite=None; Secure`
- Local HTTP development: `SameSite=Lax`

This preserves local development while making embedded HTTPS preview login work correctly.

The knowledge-at-risk map now also accepts repository evidence uploaded as a git-log text export or JSON commit export with author and changed-file/path fields. It reports commit/path evidence alongside handover-claim ownership and flags concentrated repository activity.

## Live demo

https://8001-ido3005ltpmp3n0o6keqa-4c39a963.sg2.manus.computer/

Demo accounts from the README:

- Reviewer: `reviewer` / `reviewer123`
- Successor: `successor` / `successor123`

The demo database contains the seven synthetic projects seeded by `seed_demo_board.py`.
