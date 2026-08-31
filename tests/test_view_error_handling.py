"""`parse_errors_as_400` and the exception types it has to know about.

The decorator caught `(KeyError, ValueError)`, which was the complete list of
what a parse could raise when it was written. `rota.services.ranges` now raises
`django.core.exceptions.ValidationError`, and `CoverageRule.applies_on()` and
`PracticeSettings.open_weekday_list()` both parse stored text at *read* time —
so a value that ever slipped past `clean()` turned a 400 naming the offending
value into a bare 500 with no explanation.

Not reachable from today's data. It is the failure mode when it stops being
true, which is exactly what a guard is for.
"""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from rota.models import CoverageRule, PracticeSettings
from rota.views.decorators import parse_errors_as_400
from tests.factories import make_session_type

PAYLOAD = "<img src=x onerror=alert(1)>"


def test_a_validation_error_is_a_400_that_names_the_value():
    @parse_errors_as_400
    def view(request):
        raise ValidationError(
            "%(part)r is not a number or a range like 1-6.",
            params={"part": "0,1,2,3,4,"})

    r = view(None)
    assert r.status_code == 400, "a bad stored value gives a bare 500"
    assert r.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert b"0,1,2,3,4," in r.content, (
        "the response should name the value that failed to parse"
    )
    assert b"[" not in r.content, (
        "ValidationError's str() is the repr of a list; use .messages"
    )


def test_a_validation_error_is_escaped_like_every_other_parse_error():
    """The reflected-XSS reason the decorator serves escaped plain text does
    not stop applying because the exception class changed: ranges.py puts the
    offending value straight into the message, same as int() and
    date.fromisoformat() do."""
    @parse_errors_as_400
    def view(request):
        raise ValidationError("%(part)r is not a number.",
                              params={"part": PAYLOAD})

    r = view(None)
    assert r.status_code == 400
    assert not r.headers["Content-Type"].startswith("text/html")
    assert PAYLOAD.encode() not in r.content, "the payload came back verbatim"
    assert b"&lt;img" in r.content, "the value should still be reported, escaped"


def test_keyerror_and_valueerror_still_report_the_way_they_did():
    """The added clause must not have moved the existing ones."""
    @parse_errors_as_400
    def missing_key(request):
        raise KeyError("start")

    @parse_errors_as_400
    def bad_value(request):
        date.fromisoformat("not-a-date")

    assert missing_key(None).status_code == 400
    assert b"start" in missing_key(None).content
    r = bad_value(None)
    assert r.status_code == 400
    assert b"Bad request" in r.content


@pytest.mark.django_db
def test_a_bad_stored_open_weekdays_gives_a_400_from_a_real_view(admin_client):
    """End to end through a view that parses settings at read time. .update()
    to store it, because that is the only way it gets there: it is a value
    clean() would refuse today, and the point is the shape of the failure if
    one ever does slip past."""
    settings = PracticeSettings.load()
    PracticeSettings.objects.filter(pk=settings.pk).update(
        open_weekdays="0,1,2,3,4,")
    monday = date(2026, 9, 7)

    resp = admin_client.post("/rota/fill/", {
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=4)).isoformat(),
    })
    assert resp.status_code == 400, (
        "a stored value the parser refuses 500s instead of reporting itself"
    )
    # The parser names the segment that failed, which for a trailing comma is
    # the empty one after it -- so assert on the explanation, not the value.
    assert b"is not a number or a range" in resp.content


@pytest.mark.django_db
def test_a_bad_stored_coverage_rule_weekdays_gives_a_400_too(admin_client):
    """The same hazard by its other route: CoverageRule.applies_on() parses
    three stored fields, and the fill run reads it once per rule per day."""
    st = make_session_type("Duty", code="DUT")
    CoverageRule.objects.create(session_type=st, weekdays="0,1,2,3,4,")
    monday = date(2026, 9, 7)

    resp = admin_client.post("/rota/fill/", {
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=4)).isoformat(),
    })
    assert resp.status_code == 400
    assert b"is not a number or a range" in resp.content
