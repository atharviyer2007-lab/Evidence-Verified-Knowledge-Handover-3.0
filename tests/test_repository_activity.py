import db
import pipeline


def test_repository_authors_feed_knowledge_map():
    db.init_db()
    project_id = db.run(
        "INSERT INTO projects(name, created_by, created_at) VALUES (?, ?, ?)",
        ("Repository risk metadata", "test", db.now()),
    )
    git_log = b"""commit aaa111
Author: Priya Shah <priya@example.com>
Date: 2026-11-01
    update application
 src/app.py | 4 ++++

commit bbb222
Author: Priya Shah <priya@example.com>
Date: 2026-11-02
    update deployment
 infra/deploy.yml | 2 ++

commit ccc333
Author: Priya Shah <priya@example.com>
Date: 2026-11-03
    update runbook
 docs/runbook.md | 3 +++

commit ddd444
Author: Rahul Mehta <rahul@example.com>
Date: 2026-11-04
    update tests
 tests/test_app.py | 1 +
"""
    pipeline.add_source(project_id, "git-log.txt", "repository", 2, git_log)

    activity = pipeline.repository_activity(project_id)
    priya = next(item for item in activity if item["name"] == "Priya Shah")
    assert priya["commits"] == 3
    assert priya["paths"] == 3
    assert len(priya["areas"]) == 3
    assert priya["at_risk"]

    people = pipeline.knowledge_map(project_id)
    priya_map = next(item for item in people if item["name"] == "Priya Shah")
    assert priya_map["repo_commits"] == 3
    assert priya_map["repo_paths"] == 3
    assert priya_map["evidence"] == "repository activity"
    assert priya_map["at_risk"]
