# Handover

Handover turns scattered project files (notes, task lists, chat exports) into a plan that someone else can take over. Every statement in the plan points to the exact words it came from, guesses are labelled as guesses, and each person only sees what they are allowed to see.

The landing page includes a date-aware meeting-notes proof panel: it always shows the current day, month, and year (for example, `10 November 2026`, then `11 November 2026` the next day). Its hero entrance animation is decorative, responsive, and automatically respects reduced-motion settings.

## What you need

- Python 3.10 or newer. Check with `python --version` (on some systems the command is `python3`).
- Internet access the first time you install dependencies. After that, the app can run offline; fonts fall back to system fonts if Google Fonts are unavailable.
- VS Code is recommended, but any terminal and browser will work.

## Fastest start: one command

Open a terminal **inside this `handover` folder** and paste the command for your operating system. It creates the virtual environment, installs everything from `requirements.txt`, loads the existing seven synthetic demo projects into the Project library, and starts the website. You do not need to activate the environment first.

**macOS or Linux**

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && .venv/bin/python seed_demo_board.py && .venv/bin/python -m uvicorn app:app --reload
```

**Windows PowerShell**

```powershell
python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt; .venv\Scripts\python.exe seed_demo_board.py; .venv\Scripts\python.exe -m uvicorn app:app --reload
```

When the terminal shows that Uvicorn is running, open **http://127.0.0.1:8000**. Keep the terminal open while using the site. Press `Ctrl+C` to stop it.

The database file `handover.db` is created automatically and populated with the synthetic demo projects. It is local development data and is intentionally not included in the ZIP handoff.

## VS Code: friendly step-by-step start

1. Extract the ZIP and open the `handover` folder in VS Code (**File → Open Folder**).
2. Open **Terminal → New Terminal**.
3. Run the one-shot command above for your operating system.
4. Open `http://127.0.0.1:8000` in your browser.
5. If VS Code asks which Python interpreter to use, select `.venv/bin/python` on macOS/Linux or `.venv\Scripts\python.exe` on Windows.

## Verify the installation

After the dependencies are installed, run the complete automated check from the same folder:

**macOS or Linux**

```bash
.venv/bin/python -m pytest -q
```

**Windows PowerShell**

```powershell
.venv\Scripts\python.exe -m pytest -q
```

All tests should pass. A harmless dependency deprecation warning may appear; it does not affect the application.

## Optional: fill the Project library with demo projects

After starting the app once, open a second terminal in this folder and run:

**macOS or Linux**

```bash
.venv/bin/python seed_demo_board.py
```

**Windows PowerShell**

```powershell
.venv\Scripts\python.exe seed_demo_board.py
```

This is safe to rerun: it refreshes public briefs without duplicating projects. The seven synthetic examples cover Software, Healthcare, Banking & Finance, Cybersecurity, Education, General Operations, and Community & Nonprofit. Raw sources and claim details stay private until a team is assigned.

## If something goes wrong

- **`python` is not found:** install Python 3.10+ and reopen VS Code. On macOS/Linux, use `python3`.
- **PowerShell blocks activation:** use the one-shot Windows command above; it does not require activation.
- **Port 8000 is busy:** start on another port with `.venv/bin/python -m uvicorn app:app --reload --port 8001` or the Windows equivalent, then open the matching URL.
- **The page looks stale:** stop Uvicorn with `Ctrl+C`, run the one-shot command again, and hard-refresh the browser.
- **Fonts look different:** the app is working; it is using system-font fallback because Google Fonts could not load.

The runtime and test dependencies are listed in `requirements.txt`; do not install packages individually unless you are debugging a special environment.

## Demo accounts

| Username | Password | What this person can do |
| --- | --- | --- |
| reviewer | reviewer123 | Add files, review claims, share the plan, see all activity |
| successor | successor123 | Open the plan assigned to their group, allocate/tick off actions, confirm reading, and submit completed work for review |

Successor teams can register from the sign-in page. One team-leader login represents the group; registration records the team name, total size, member names and a job category. The category is profile information only: selecting “Reviewer” does not create a reviewer account. A reviewer must assign or share a project before the team can see its contents.

## What you can do

| Feature | Where to find it |
| --- | --- |
| Add notes, task lists and chat exports with a visibility level | Add files |
| Register a successor team with a named roster | Sign in, then "Register here"; one login represents the group |
| Browse/search/filter the project library and inspect public scope, skills, outcome and status | Project library; private source evidence remains hidden until assignment |
| Review incoming requests separately from direct assignments and active project owners | Reviewer navigation, "Teams & requests" |
| Give one successor group exclusive project access; close competing requests | Reviewer project desk or Share; access has an expiry and can be revoked |
| Review successor completion reports; accept or request changes with feedback | Reviewer project desk, "Successor work submitted" |
| Divide approved week-one actions among named team members | Plan, "Assigned team member" |
| Hide passwords, keys, emails and phone numbers automatically | Happens when a file is added |
| Find decisions, owners, risks, dependencies, blockers, questions, actions and contacts | Add files, then Find claims |
| Check every claim against the source and grade it | Review |
| See the exact highlighted words behind a claim | "See the evidence" |
| Approve, reject, edit, undo, redo and see the full history of a claim | Review, then History |
| Record the answer from the person leaving | Review, under an Unknown claim |
| List the questions to ask the person leaving | Review, "See the questions for the person leaving" |
| Spot phrases that are mentioned often but never explained or owned | Same Questions page |
| See who owns the most areas, and so who would be hardest to replace | Same Questions page |
| See risks and blockers that keep coming up in different files | Questions page and the plan |
| See work that is still unfinished | Plan, "Unfinished work" |
| Search claims by their wording | Search box on the project, review and plan pages |
| Check how many of a successor's likely questions can be answered | Share, "Readiness check", or the project page |
| Get notified when a plan is shared, read, replied to or sent back | The bell in the top bar |
| Choose a guided tour on first sign-in; choose “Not now” or “Don’t ask again” | First-login prompt; restart a page tour from Help & tour |
| Run the app on the demo projects and check it finds what was planted there | Projects, "Run the self-check on the demo projects" |
| Share the plan with an expiry date, and remove access later | Share |
| Preview exactly what the successor will see | Share or Plan |
| Read the plan as a list or as a timeline | Plan |
| Tick off week-one actions or send one back with a note | Plan (successor) |
| Assign a plan action to a named team member | Plan (successor team login) |
| Reply to a sent-back action | Share (reviewer) |
| Replace a file and flag approved claims that no longer match it | Add files, same file name |
| Download the plan as Excel (with a chart), Word, CSV, XML or JSON, or print it | Plan |
| See who did what | Activity |
| Delete a project and everything in it | Project page, "Delete this project" |
| Try seven cross-industry synthetic examples | Reviewer "Teams & requests" demo buttons, or `python seed_demo_board.py` to seed the board |

## A five-minute tour

1. Sign in as **reviewer** and press **Load the demo project**.
2. On the Review page press **Approve all backed claims**. Then work through the rest:
   - A **Conflicting** claim needs a reason before you can approve it.
   - An **Inferred** claim is a guess and cannot be approved. Edit it so the quote matches the source, or reject it.
   - An **Unknown** claim is an open gap and cannot be approved as fact. Open "Add the answer from the person leaving" and type what they told you. It becomes **Testimony**.
3. Click **See the evidence** on any claim to see the highlighted words in the original file.
4. Open "See the questions for the person leaving" to see everything that is missing.
5. Open **Share**. Sharing stays blocked while critical rehearsal questions are unanswered; answer them (or reject claims that are not relevant), then share the plan.
6. For the group workflow, sign in as a successor team, request a reviewer-published project, and check **My team** for the decision and assignment brief. The reviewer handles requests and direct assignments in separate sections of **Teams & requests**. Only one team can own the active project.
7. As the owning successor, mark each plan action done, then submit a short completion report. The reviewer can request changes or accept it; the team sees the written decision in **My team**.
8. Restricted items are not in the successor plan. Try **Unclear? Send it back**, acknowledge the plan, and review your team’s task allocations.
9. Sign back in as **reviewer**. The bell shows notifications, Share shows sent-back questions, the reviewer desk shows pending completion reports, and Activity records actions.
10. Open the project page and try **Readiness rehearsal**, the **Questions** page, and **Search**.

The round Help button in the corner of every page explains the page you are on.

## What is in this folder

| File or folder | What it does |
| --- | --- |
| `app.py` | The web pages and what each button does |
| `pipeline.py` | The core logic: hiding secrets, finding claims, checking quotes, grading, timeline, questions, building the plan |
| `exports.py` | Builds the Excel, Word, CSV, XML and JSON downloads and protects them from spreadsheet formula tricks |
| `db.py` | The database. Plain SQLite with a few small helpers: `query`, `one`, `run` and `run_all` |
| `security.py` | Password hashing, login limits and security headers |
| `llm.py` | Optional AI helper, off unless you set a key |
| `templates/` | The pages (HTML) |
| `static/` | The look and animations (CSS and JavaScript) |
| `sample_data/` | Synthetic project files for seven sectors, each with a `planted.json` list of problems hidden on purpose |
| `tests/` | Automated checks |
| `security_report.txt` | The result of the last security scans |
| `accessibility_report.txt` | The result of the last accessibility scan |
| `requirements.txt` | The Python packages to install |

## How it works in plain words

1. **Add files.** Each file gets a visibility level: anyone with the plan, team members, or reviewers only. Emails, phone numbers, passwords and keys are replaced with `[masked ...]` before anything is saved. Adding a file with the same name replaces it.
2. **Find claims.** The app looks for decisions, owners, risks, dependencies, blockers, open questions, next actions and contacts. It also notices missing reasons, missing owners, owners that disagree, and people who own many areas.
3. **Check the evidence.** For every claim the app looks for the quoted words in the file. If they are there the claim is **Backed**. If not, it is downgraded.
4. **Review.** You approve, reject or edit. Inferred guesses and Unknown gaps cannot be approved as facts; answer an Unknown as testimony or reject it. Every change is saved as a version, so you can undo and see the history.
5. **Share.** You can share only when every claim has a decision, at least one claim is approved, and critical Continuity Rehearsal questions are answered. Deliberately restricted facts are not treated as unresolved successor-visible gaps. The plan is built from approved claims at the successor's visibility level or lower. Restricted claims are filtered out before the plan, the timeline and the downloads are built.
6. **Assign exclusively.** A reviewer assigns or approves exactly one successor group at a time, with an expiry and written assignment brief. Other groups cannot open or request an actively owned project.
7. **Complete and review.** The owning group marks plan actions done and submits a completion report. The reviewer accepts it or requests changes with feedback; acceptance records the project as completed.
8. **Acknowledge.** The successor confirms they have read the plan. A reviewer can revoke access at any time.

## The labels

| Label | Meaning |
| --- | --- |
| Backed | The quoted words were found in the source |
| Testimony | A person stated it. There is no source passage |
| Inferred | A guess by the tool. It cannot be approved as fact |
| Conflicting | Two sources disagree. You must say which one you trust |
| Unknown | Something important is missing |

## How the newer features decide things

- **Timeline.** A claim is placed on a date only if the source writes that date as `2026-11-20`, either in the claim itself or on the same line of the file. Claims without such a date are in the plan but not on the timeline.
- **Replacing a file.** Approved claims whose quoted words are no longer in the new file go back to review as Inferred. Claims still found are left alone. New sentences in the new file are not picked up until you press Find claims again, which replaces earlier decisions after asking you to confirm. A file's visibility can be raised by replacing it but never lowered this way, so a claim is never exposed by accident.
- **Phrases never explained or owned.** The app lists two-word phrases that appear in more than one file, are not part of any owner claim, and are not defined by a sentence like "X is a ...". It is a hint to prompt a conversation, not a verdict, and it works best on plain English notes.
- **Downloads.** Cells that start with `=`, `+`, `-` or `@` get a leading apostrophe so a spreadsheet never runs them as a formula.

- **Redo.** Undo marks the latest change as undone and restores the one before it. Redo brings it back. Making any new change clears what could be redone.
- **Unfinished work.** A task-board row is unfinished when its status is not something like done, complete, closed, finished, resolved or shipped. Blocked rows become blockers instead. In plain text, phrases such as "in progress", "not yet" or "half finished" are picked up.
- **Problems that keep coming up.** Risks and blockers that share a two-word phrase across more than one file are grouped. The plan only uses approved claims the reader may see.
- **Who holds the knowledge.** Counts the areas each person owns in claims that are not rejected. Three or more areas is flagged as a possible single point of failure. This needs claims found by this version, so find claims again on projects made earlier.
- **Readiness rehearsal.** Writes the questions a successor is likely to ask from the claims (why was this decided, who owns this, what is blocking this, what is left, plus "what should I do first" and "who can I ask"). A question counts as answered only if the claims behind it are approved, visible to the successor, and not a guess. Questions that rest on missing information or open questions count as answered only after someone records an answer. It is a rough guide, not proof.
- **Open questions can be answered.** Open questions found in the files can be answered the same way as missing information. The question is kept in front of the answer.
- **Self-check.** Runs the app on each demo project, checks that every planted gap and conflict was found, that no restricted fact reaches the successor view, and that no secret is stored, then deletes the test project. It runs on made-up files, so it shows the design works and does not measure accuracy on real notes.
- **Notifications.** Written when a plan is shared, read, replied to, sent back or removed. Each person only sees their own.
- **Tour.** A per-account first-sign-in prompt offers Start, Not now, and “Don’t ask again.” Not now can be revisited on a later sign-in; Help & tour can restart page guidance.
- **Project library and group ownership.** Reviewer-authored safe briefs include scope, useful skills, expected outcome and computed status. The project lock is transactional; one group owns an active assignment. Competing pending requests are closed with an explanation.
- **Completion review.** The assigned group submits only after all visible next actions are marked done and no item is awaiting a reviewer reply. Reviewers accept or request changes with required written feedback.
- **Tests.** The current automated suite has 62 passing tests, including exclusive-team access and successor completion review. This does not replace a live classmate/usability trial or production security deployment review.
- **Upgrading.** If you already have a `handover.db` from an earlier version, new columns are added automatically when the app starts.

## Security built in

- Passwords are stored as salted PBKDF2 hashes, never as plain text.
- Every form has a security token, and every page checks permissions on the server.
- Login is limited to five tries a minute.
- Signed session cookies, content security policy, no framing, and no content sniffing.
- File uploads are limited to `.txt`, `.md`, `.csv` and `.json` under 200 KB.
- Every database query uses placeholders, and every page escapes what it shows.
- Every sign-in, upload, approval, share and deletion is recorded on the Activity page.

## Accessibility

Every page was scanned in light and dark mode with axe-core in a real browser. The scan found low-contrast status labels and skipped heading levels, which were fixed, and the last run found no violations. The page also has a skip link, labelled forms, visible keyboard focus, a keyboard-closable help panel and tour, and respects reduced-motion settings. Automated scans catch only part of the problems, so a screen-reader and keyboard-only test by a person is still worth doing. Results are in `accessibility_report.txt`.

### Check it yourself

```
pip install bandit pip-audit
bandit -r . -x ./tests
pip-audit -r requirements.txt
```

The last run found no issues and no known vulnerable packages. The results are in `security_report.txt`. A scan of the running site with OWASP ZAP has not been done yet.

## Optional settings

Set these before starting the app if you want them.

| Setting | What it does |
| --- | --- |
| `SECRET_KEY` | Keeps people signed in after a restart. Any long random text works |
| `HANDOVER_DB` | Uses a different database file |
| `ANTHROPIC_API_KEY` | Lets an AI model suggest claims from text files instead of the built-in rules |
| `LLM_MODEL` | Which model to use with the key above |

Example on macOS or Linux: `ANTHROPIC_API_KEY=your-key uvicorn app:app`

If you turn the AI helper on, the text of your files is sent to that provider. Use made-up or permitted data only. Quotes suggested by the AI are checked against your file exactly like every other claim, and anything it cannot prove is downgraded. If the call fails, the app quietly uses the built-in rules. The reply parsing is tested, but the helper has not been tested with a live key.

## Run the tests

```
pytest
```

You should see `60 passed`. The tests cover group registration and roster validation, job-title/permission separation, reviewer-created demo teams, incomplete-project requests and feedback, member-level task assignment, category publishing/search/filtering, password hashing and validation, hiding secrets, quote checking, conflict detection, the rules that Inferred and Unknown claims cannot be approved as facts, the hard sharing readiness gate, restricted claims never reaching the successor (in the plan, timeline, search, evidence and every download), acknowledgement, revoking and expiring access, the action tracker, replacing files, deleting projects, undo and redo, upgrading an old database, search, unfinished work, who holds the knowledge, recurring problems, the readiness rehearsal, the seven-demo self-check, notifications, Word and XML files, questions, the phrase finder, login protections and AI reply parsing. A harmless warning about `httpx` can be ignored.

## Good to know

- Undo and redo step through one change at a time.
- Finding claims again replaces the earlier claims and your decisions on them. The app asks you to confirm.
- The self-check and the classmate trial are different things. The classmate trial, where someone unfamiliar with a project answers questions from the handover and from the raw files, has to be done by hand.
- The built-in finder uses simple sentence patterns, so it works best on plain notes. Review is mandatory for this reason.
- Visibility levels are set per file, not inherited from another system.
- The person leaving does not have their own login. The reviewer records their answers.
- The demo passwords are public. To change them, edit `DEMO_USERS` in `db.py` before the first run, or delete `handover.db` and start again.
- This runs as a local app over plain HTTP. Put it behind HTTPS before using it anywhere real.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `command not found: uvicorn` | Activate the virtual environment again, then run `pip install -r requirements.txt` |
| `Address already in use` | Run `uvicorn app:app --port 8001` and open http://127.0.0.1:8001 |
| Everything looks plain | Reload the page. If you are offline the fonts fall back to system fonts, which is fine |
| You want a fresh start | Stop the app, delete `handover.db`, and start it again |
