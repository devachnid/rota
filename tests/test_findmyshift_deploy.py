"""The timer that makes the sync run, and the docs that tell an admin how."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_service_runs_the_sync_command_from_the_env_file():
    unit = (ROOT / "deploy" / "rota-findmyshift.service").read_text()
    assert "findmyshift_sync" in unit
    assert "EnvironmentFile=/etc/rota.env" in unit, "the key must come from the env file"
    assert "Type=oneshot" in unit


def test_the_timer_fires_every_fifteen_minutes():
    timer = (ROOT / "deploy" / "rota-findmyshift.timer").read_text()
    assert re.search(r"OnCalendar=.*\*:0/15", timer) or "OnUnitActiveSec=15min" in timer
    assert "WantedBy=timers.target" in timer


def test_the_env_file_comment_names_the_findmyshift_variables():
    unit = (ROOT / "deploy" / "gunicorn.service").read_text()
    for name in ("FINDMYSHIFT_API_KEY", "FINDMYSHIFT_API_URL", "FINDMYSHIFT_TEAM_ID",
                 "FINDMYSHIFT_MIDDAY"):
        assert name in unit


def test_nothing_deployable_still_names_breathe():
    """The Breathe integration is gone. Its name may survive in dated specs,
    plans, the backlog's history, the migrations that built and removed it,
    and the guide's "Moving from Breathe" section that tells an admin how to
    retire its timer — nowhere else an admin or a deploy reads."""
    hits = []
    for folder in ("rota", "templates", "static/css", "deploy", "docs/admin", "config"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_dir() or "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            if path.name == "findmyshift.md":
                text = text.split("### Moving from Breathe", 1)[0]
            if re.search(r"breathe", text, re.I):
                hits.append(str(path.relative_to(ROOT)))
    assert "breathe" not in (ROOT / "README.md").read_text().lower()
    assert not hits, hits


def test_no_doc_still_describes_local_leave_management():
    docs = "\n".join(p.read_text() for p in (ROOT / "docs" / "admin").glob("*.md"))
    for phrase in ("Leave entitlement sessions", "Counts toward entitlement",
                   "Leave year start", "/admin/rota/leaverequest/"):
        assert phrase not in docs, f"docs still describe {phrase!r}"
    readme = (ROOT / "README.md").read_text()
    assert "counts toward entitlement" not in readme.lower()
    assert "leave year start" not in readme.lower()
