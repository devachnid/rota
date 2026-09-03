"""The timer that makes the sync run, and the docs that tell an admin how."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_service_runs_the_sync_command_from_the_env_file():
    unit = (ROOT / "deploy" / "rota-breathe.service").read_text()
    assert "breathe_sync" in unit
    assert "EnvironmentFile=/etc/rota.env" in unit, "the key must come from the env file"
    assert "Type=oneshot" in unit


def test_the_timer_fires_every_fifteen_minutes():
    timer = (ROOT / "deploy" / "rota-breathe.timer").read_text()
    assert re.search(r"OnCalendar=.*\*:0/15", timer) or "OnUnitActiveSec=15min" in timer
    assert "WantedBy=timers.target" in timer


def test_the_env_file_comment_names_the_breathe_variables():
    unit = (ROOT / "deploy" / "gunicorn.service").read_text()
    assert "BREATHE_API_KEY" in unit


def test_no_doc_still_describes_local_leave_management():
    docs = "\n".join(p.read_text() for p in (ROOT / "docs" / "admin").glob("*.md"))
    for phrase in ("Leave entitlement sessions", "Counts toward entitlement",
                   "Leave year start", "/admin/rota/leaverequest/"):
        assert phrase not in docs, f"docs still describe {phrase!r}"
    readme = (ROOT / "README.md").read_text()
    assert "counts toward entitlement" not in readme.lower()
    assert "leave year start" not in readme.lower()
