"""The sessions feed Shift Central polls: bearer token, published entries
only, by the clinician's login email."""

from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from tests.factories import make_clinician, make_entry, make_session_type, make_site

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture(autouse=True)
def _fresh_rate_counts(monkeypatch):
    cache.clear()
    monkeypatch.setattr("api.auth.time", SimpleNamespace(time=lambda: 1_800_000_030.0))
    yield
    cache.clear()


@pytest.fixture
def api(client, settings):
    settings.ROTA_API_TOKENS = frozenset({"t0k"})
    return lambda url: client.get(url, HTTP_AUTHORIZATION="Bearer t0k")


def test_token_required(client, settings):
    settings.ROTA_API_TOKENS = frozenset({"t0k"})
    r = client.get("/api/v1/sessions?from=2027-01-04&to=2027-01-10")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer" and r.json() == {"error": "unauthorised"}
    assert client.get("/api/v1/sessions?from=2027-01-04&to=2027-01-10", HTTP_AUTHORIZATION="Bearer wrong").status_code == 401
    assert "no-store" in r.headers["Cache-Control"]


def test_no_tokens_configured_refuses_everything(client, settings):
    settings.ROTA_API_TOKENS = frozenset()
    assert client.get("/api/v1/sessions?from=2027-01-04&to=2027-01-10", HTTP_AUTHORIZATION="Bearer anything").status_code == 401


def test_a_session_is_not_a_token(admin_client, settings):
    settings.ROTA_API_TOKENS = frozenset({"t0k"})
    assert admin_client.get("/api/v1/sessions?from=2027-01-04&to=2027-01-10").status_code == 401


def test_only_get(client, settings):
    settings.ROTA_API_TOKENS = frozenset({"t0k"})
    r = client.post("/api/v1/sessions?from=2027-01-04&to=2027-01-10", HTTP_AUTHORIZATION="Bearer t0k")
    assert r.status_code == 405 and r.headers["Allow"] == "GET"


@pytest.mark.parametrize("q", ["", "from=2027-01-04", "from=2027-01-10&to=2027-01-04", "from=x&to=2027-01-04",
                               "from=2027-01-01&to=2028-06-01"])
def test_bad_ranges_are_400(api, q):
    r = api(f"/api/v1/sessions?{q}")
    assert r.status_code == 400 and "error" in r.json()


def test_published_sessions_by_email_with_site_type_and_note(api):
    user = User.objects.create_user(email="a.gp@example.org", password="pw")
    alice = make_clinician("Alice Adams", user=user)
    bob = make_clinician("Bob Brown")                       # no login, no email
    site = make_site("AG")
    make_entry(alice, date(2027, 1, 4), "AM", make_session_type("Surgery"), site=site, note="late start")
    make_entry(alice, date(2027, 1, 4), "PM", make_session_type("Admin"))
    make_entry(alice, date(2027, 1, 5), "AM", is_published=False)
    make_entry(alice, date(2027, 2, 1), "AM")
    make_entry(bob, date(2027, 1, 4), "AM")
    body = api("/api/v1/sessions?from=2027-01-04&to=2027-01-10").json()
    assert body["from"] == "2027-01-04" and body["to"] == "2027-01-10"
    assert body["sessions"] == [
        {"email": "a.gp@example.org", "day": "2027-01-04", "part": "AM", "type": "Surgery", "site": "AG", "note": "late start"},
        {"email": "a.gp@example.org", "day": "2027-01-04", "part": "PM", "type": "Admin", "site": "", "note": ""},
    ]
    assert body["without_email"] == 1
