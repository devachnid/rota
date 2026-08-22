from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_commitment,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)


def test_commitment_stamped_weekly(admin_user):
    PracticeSettings.load()
    c = make_clinician("Vic Whitbread")
    make_pattern(c)
    proactive = make_session_type("Proactive")
    make_commitment(c, session_type=proactive, weekday=0, part="BOTH")
    run_fill(admin_user, MON, FRI)
    entries = RotaEntry.objects.filter(session_type=proactive)
    assert [(e.day, e.part) for e in entries.order_by("part")] == [
        (MON, "AM"), (MON, "PM")]
    assert all(not e.manually_set and e.fill_reason == "commitment"
               for e in entries)


def test_commitment_never_overwrites_leave(admin_user):
    PracticeSettings.load()
    c = make_clinician("Vic Whitbread")
    make_pattern(c)
    leave = make_session_type("Annual leave", category="ABSENCE")
    entries_svc.assign(admin_user, c, MON, "AM", leave, published=True)
    make_commitment(c, session_type=make_session_type("Proactive"),
                    weekday=0, part="BOTH")
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.get(clinician=c, day=MON, part="AM").session_type == leave
    assert RotaEntry.objects.get(clinician=c, day=MON,
                                 part="PM").session_type.name == "Proactive"


def test_fortnightly_commitment_skips_off_weeks(admin_user):
    PracticeSettings.load()
    c = make_clinician("Ed P")
    make_pattern(c)
    occ = make_session_type("Occ Health")
    make_commitment(c, session_type=occ, weekday=3, part="AM",
                    interval_weeks=2, active_from=MON)
    run_fill(admin_user, MON, MON + timedelta(days=11))  # two Thursdays
    days = list(RotaEntry.objects.filter(session_type=occ)
                .values_list("day", flat=True))
    assert days == [MON + timedelta(days=3)]  # week 1 only


def test_commitment_skips_when_not_working(admin_user):
    PracticeSettings.load()
    c = make_clinician("Part Timer")
    make_pattern(c, weekdays=(1,))  # Tuesdays only
    make_commitment(c, session_type=make_session_type("Vision"),
                    weekday=0, part="AM")
    run_fill(admin_user, MON, FRI)
    assert not RotaEntry.objects.filter(session_type__name="Vision").exists()


def test_commitments_pass_has_no_n_plus_one(admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from rota.models import Site

    PracticeSettings.load()
    site = Site.objects.create(name="Main Surgery")
    vision = make_session_type("Vision")
    vision.default_site = site
    vision.save()
    for name in ("Alice Adams", "Beth Brown", "Carl Cole", "Dana Dee"):
        c = make_clinician(name)
        make_pattern(c)
        make_commitment(c, session_type=vision, weekday=0, part="AM")

    with CaptureQueriesContext(connection) as ctx:
        run_fill(admin_user, MON, MON)

    site_queries = [q for q in ctx.captured_queries
                    if "rota_site" in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")]
    assert len(site_queries) <= 1, (
        f"expected at most one Site query, got {len(site_queries)}:\n"
        + "\n".join(q["sql"] for q in site_queries))
    assert RotaEntry.objects.filter(session_type=vision).count() == 4
