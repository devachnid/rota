"""The timer, the env comments, and that nothing deployable still names FindMyShift or Breathe."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_service_runs_the_sync_from_the_env_file():
    unit = (ROOT / "deploy" / "rota-shift-central.service").read_text()
    assert "shift_central_sync" in unit and "EnvironmentFile=/etc/rota.env" in unit and "Type=oneshot" in unit


def test_the_timer_fires_every_fifteen_minutes_offset_from_the_others():
    timer = (ROOT / "deploy" / "rota-shift-central.timer").read_text()
    assert re.search(r"OnCalendar=.*\*:11/15", timer) and "WantedBy=timers.target" in timer


def test_the_env_file_comment_names_the_shift_central_variables():
    unit = (ROOT / "deploy" / "gunicorn.service").read_text()
    assert "SHIFT_CENTRAL_URL" in unit and "SHIFT_CENTRAL_TOKEN" in unit and "FINDMYSHIFT" not in unit


def test_nothing_deployable_still_names_findmyshift_or_breathe():
    hits = []
    for folder in ("rota", "templates", "static/css", "deploy", "docs/admin", "config", "api"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_dir() or "migrations" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            if path.name == "shift-central.md":
                text = text.split("### Moving from FindMyShift", 1)[0]
            if re.search(r"findmyshift|breathe", text, re.I):
                hits.append(str(path.relative_to(ROOT)))
    assert not hits, hits
    readme = (ROOT / "README.md").read_text().lower()
    assert "breathe" not in readme and readme.count("findmyshift") <= 2     # the history line and the "Moving from" pointer only
