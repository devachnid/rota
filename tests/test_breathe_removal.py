"""Local leave management is gone. Breathe owns it."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.django_db


def test_no_code_references_leaverequest():
    hits = []
    for path in (ROOT / "rota").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        if re.search(r"\bLeaveRequest\b", path.read_text()):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"LeaveRequest still referenced in: {hits}"


def test_no_template_offers_a_leave_request():
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text()
        assert "leave/new" not in text, f"{path.name} still links the leave form"
        assert "Request leave" not in text, f"{path.name} still offers Request leave"
        assert "reports/leave" not in text, f"{path.name} still links the leave report"


@pytest.mark.parametrize("url", ["/me/leave/new/", "/reports/leave/",
                                 "/requests/leave/1/approve/", "/requests/leave/1/decline/"])
def test_the_old_leave_urls_are_gone(admin_client, url):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    assert admin_client.get(url).status_code == 404


def test_the_removed_fields_are_gone():
    from rota.models import Clinician, PracticeSettings, SessionType
    assert not any(f.name == "leave_entitlement_sessions" for f in Clinician._meta.fields)
    assert not any(f.name == "counts_toward_entitlement" for f in SessionType._meta.fields)
    assert not any(f.name.startswith("leave_year_start") for f in PracticeSettings._meta.fields)


def test_the_inbox_still_shows_swaps_and_no_leave(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/requests/").content.decode()
    assert "Swaps" in html or "swap" in html.lower()
    assert "pending leave" not in html.lower()
