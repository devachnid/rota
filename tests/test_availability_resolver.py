"""One answer to "can this clinician be given this session?".

Before this, the question was answered in the grid and in the fill engine
separately, and knew only about the working pattern. Clinician date windows
and approved leave both belong in it. Composing them in one place is what
stops `active` and the dates disagreeing.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot
from rota.services.availability import AvailabilityResolver
from tests.factories import make_clinician, make_session_type

MON = date(2026, 9, 7)
LONG_AGO = date(2025, 1, 1)


def _pattern(clinician, weekday, part, works=True, effective_from=LONG_AGO):
    return PatternSlot.objects.create(
        clinician=clinician, weekday=weekday, part=part,
        works=works, effective_from=effective_from)


def _resolver(clinicians, rows=(), leave=()):
    return AvailabilityResolver(list(rows), list(clinicians), list(leave))


@pytest.mark.django_db
def test_works_on_follows_the_pattern():
    c = make_clinician("Pat", initials="PA")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    assert r.works_on(c.id, MON, "AM") is True
    assert r.works_on(c.id, MON, "PM") is False


@pytest.mark.django_db
def test_an_inactive_clinician_never_works():
    c = make_clinician("Gone", initials="GO")
    rows = [_pattern(c, 0, "AM")]
    c.active = False
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_a_session_before_the_start_date_is_not_worked():
    c = make_clinician("Starts", initials="SS")
    rows = [_pattern(c, 0, "AM")]
    c.start_date = MON + timedelta(days=7)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False
    assert _resolver([c], rows).works_on(c.id, MON + timedelta(days=7), "AM") is True


@pytest.mark.django_db
def test_a_session_after_the_end_date_is_not_worked():
    c = make_clinician("Ends", initials="EN")
    rows = [_pattern(c, 0, "AM")]
    c.end_date = MON - timedelta(days=1)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_approved_leave_makes_a_worked_session_unavailable():
    c = make_clinician("Away", initials="AW")
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rows = [_pattern(c, 0, "AM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], rows, leave)
    assert r.works_on(c.id, MON, "AM") is True, "leave must not change works_on"
    assert r.on_leave(c.id, MON, "AM") is True
    assert r.available(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_pending_leave_is_ignored():
    """Out of scope by decision: pending leave stays invisible to scheduling."""
    c = make_clinician("Maybe", initials="MB")
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    rows = [_pattern(c, 0, "AM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.PENDING)]
    assert _resolver([c], rows, leave).available(c.id, MON, "AM") is True


@pytest.mark.django_db
def test_leave_is_whole_day_because_requests_store_dates_not_parts():
    c = make_clinician("Allday", initials="AD")
    al = make_session_type("Annual Leave", code="AL3", category="ABSENCE")
    rows = [_pattern(c, 0, "AM"), _pattern(c, 0, "PM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], rows, leave)
    assert r.on_leave(c.id, MON, "AM") is True
    assert r.on_leave(c.id, MON, "PM") is True


@pytest.mark.django_db
def test_leave_type_returns_the_session_type_for_rendering():
    c = make_clinician("Chip", initials="CH")
    al = make_session_type("Study Leave", code="SL", category="ABSENCE")
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], (), leave)
    assert r.leave_type(c.id, MON) == al
    assert r.leave_type(c.id, MON + timedelta(days=1)) is None


@pytest.mark.django_db
def test_has_pattern_distinguishes_no_rows_from_not_working():
    with_rows = make_clinician("Has", initials="HS")
    without = make_clinician("Hasnt", initials="HN")
    rows = [_pattern(with_rows, 0, "AM")]
    r = _resolver([with_rows, without], rows)
    assert r.has_pattern(with_rows.id) is True
    assert r.has_pattern(without.id) is False


@pytest.mark.django_db
def test_the_resolver_issues_no_queries_once_built():
    """Both callers ask it once per cell. A query here is a query per cell."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    c = make_clinician("Quiet", initials="QT")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    with CaptureQueriesContext(connection) as ctx:
        for _ in range(20):
            r.available(c.id, MON, "AM")
    assert len(ctx) == 0
