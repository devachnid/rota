"""seed_demo: three fictional GPs, a practice set up around them and nine
weeks of published rota, for a staging box. It is pointed at somebody's
database, so most of what is pinned here is what it refuses, what it leaves
alone and that it sends nothing."""

import io
from collections import Counter
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError

from rota import palette
from rota.admin_dashboard import setup_steps
from rota.management.commands import seed_demo
from rota.models import (Clinician, ClinicianGroup, CoverageRule, PatternSlot,
                         PracticeSettings, RotaEntry, SessionType, Site, TimeOff)
from rota.services.calendar import is_open
from rota.services.warnings import day_warnings
from tests.factories import make_clinician, make_group

pytestmark = pytest.mark.django_db
User = get_user_model()

BASE = "tom@example.org"
EMAILS = {
    "Dr Priya Nair": "tom+priya.nair@example.org",
    "Dr Callum Ross": "tom+callum.ross@example.org",
    "Dr Helen Okafor": "tom+helen.okafor@example.org",
}


def seed(base=BASE, *flags):
    out = io.StringIO()
    args = ["--email-base", base] if base else []
    call_command("seed_demo", *args, *(flags or ("--yes-this-is-staging",)), stdout=out)
    return out.getvalue()


def this_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


def snapshot():
    """Row counts of everything the command writes, and the audit trail."""
    from rota.models import RotaEntryLog
    models = (User, Clinician, ClinicianGroup, Site, SessionType, CoverageRule,
              PatternSlot, PracticeSettings, RotaEntry, RotaEntryLog)
    return {m.__name__: m.objects.count() for m in models}


def test_creates_three_clinicians_with_their_emails_groups_and_initials():
    seed()
    got = {c.name: (c.initials, c.group.name, c.user.email)
           for c in Clinician.objects.select_related("group", "user")}
    assert got == {
        "Dr Priya Nair": ("PN", "Partners", EMAILS["Dr Priya Nair"]),
        "Dr Callum Ross": ("CR", "Salaried", EMAILS["Dr Callum Ross"]),
        "Dr Helen Okafor": ("HO", "Salaried", EMAILS["Dr Helen Okafor"]),
    }
    assert Clinician.objects.count() == 3


def test_the_emails_follow_the_shared_rule():
    # <local>+<first>.<last>@<domain>, the one the HR and Shift Central seeds make.
    assert [gp.email("tom@example.org") for gp in seed_demo.CAST] == [
        "tom+priya.nair@example.org", "tom+callum.ross@example.org",
        "tom+helen.okafor@example.org"]
    assert seed_demo.CAST[0].email("a.b@x.co.uk") == "a.b+priya.nair@x.co.uk"


def test_logins_have_no_usable_password_and_no_invitation():
    seed()
    for user in User.objects.all():
        assert not user.has_usable_password()
        assert user.password_link_sent_at is None
        assert not user.is_rota_admin and not user.is_staff and not user.is_superuser


def test_practice_setup_exists():
    seed()
    assert Site.objects.filter(name="Main Surgery").exists()
    assert set(ClinicianGroup.objects.values_list("name", flat=True)) == {
        "Partners", "Salaried", "Locums"}
    assert ClinicianGroup.objects.filter(is_locum_group=True).count() == 1
    names = set(SessionType.objects.values_list("name", flat=True))
    assert {"Morning surgery", "Afternoon surgery", "Duty doctor", "Admin",
            "Home visits"} <= names
    assert CoverageRule.objects.count() == 3


def test_session_types_use_real_tints_and_codes_that_fit_the_grid():
    for name, code, _category, tint, _extra in seed_demo.SESSION_TYPES.values():
        assert tint in palette.TINTS, name
        assert len(code) <= 6, name


def test_patterns_are_eight_six_and_five_sessions():
    seed()
    counts = {c.name: PatternSlot.objects.filter(clinician=c, works=True).count()
              for c in Clinician.objects.all()}
    assert counts == {"Dr Priya Nair": 8, "Dr Callum Ross": 6, "Dr Helen Okafor": 5}
    days = {c.name: {s.weekday for s in c.pattern_slots.all()} for c in Clinician.objects.all()}
    assert days["Dr Priya Nair"] == {0, 1, 2, 3}
    assert days["Dr Callum Ross"] == {0, 1, 3, 4}
    assert days["Dr Helen Okafor"] == {2, 3, 4}


def test_published_entries_cover_this_week_and_the_next_eight_and_match_patterns():
    seed()
    monday = this_monday()
    entries = RotaEntry.objects.all()
    assert entries.count() == (8 + 6 + 5) * 9
    assert not entries.filter(is_published=False).exists()
    assert entries.first().day >= monday
    assert entries.order_by("-day").first().day <= monday + timedelta(weeks=8, days=6)
    assert {e.day for e in entries if e.day.weekday() >= 5} == set()
    weeks = Counter((e.day - monday).days // 7 for e in entries)
    assert weeks == {w: 19 for w in range(9)}
    # Every entry is a session its clinician's pattern says they work.
    pattern = {(s.clinician_id, s.weekday, s.part) for s in PatternSlot.objects.filter(works=True)}
    assert all((e.clinician_id, e.day.weekday(), e.part) in pattern for e in entries)
    assert all(e.site.name == "Main Surgery" for e in entries)


def test_one_duty_doctor_day_a_week_rotating_between_the_three():
    seed()
    monday = this_monday()
    duty = RotaEntry.objects.filter(session_type__name="Duty doctor")
    by_week = {}
    for e in duty:
        by_week.setdefault((e.day - monday).days // 7, []).append(e)
    assert sorted(by_week) == list(range(9))
    for week, rows in by_week.items():
        assert len(rows) == 2, week  # one full day: AM and PM
        assert len({(e.day, e.clinician_id) for e in rows}) == 1
        assert {e.part for e in rows} == {"AM", "PM"}
        assert len({e.allocation_group for e in rows}) == 1
    doing = [by_week[w][0].clinician.name for w in range(9)]
    assert set(doing[:3]) == set(EMAILS)
    assert doing[3:6] == doing[:3] and doing[6:] == doing[:3]


def test_the_grid_has_no_gaps_to_show():
    seed()
    monday = this_monday()
    for offset in range(63):
        day = monday + timedelta(days=offset)
        if is_open(day):
            assert [w.message for w in day_warnings(day)] == [], day


def test_setup_card_is_complete_but_for_shift_central_and_email():
    seed()
    done = {s["title"]: s["done"] for s in setup_steps()["steps"]}
    assert [t for t, ok in done.items() if not ok] == ["Shift Central", "Outgoing email"]
    assert len(done) == 9


def test_dashboard_and_grid_render(admin_client):
    seed()
    assert admin_client.get("/admin/").status_code == 200
    assert admin_client.get("/rota/").status_code == 200
    assert admin_client.get("/reports/staffing/").status_code == 200


def test_it_writes_nothing_it_was_not_asked_to():
    seed()
    from rota.models import (PersonalRequirement, RecurringCommitment,
                             TraineeProfile, LocumRequirement)
    for model in (TimeOff, TraineeProfile, RecurringCommitment,
                  PersonalRequirement, LocumRequirement):
        assert not model.objects.exists(), model.__name__
    assert not Clinician.objects.filter(group__is_locum_group=True).exists()


def test_a_second_run_with_the_same_base_changes_nothing():
    seed()
    before = snapshot()
    ids = set(RotaEntry.objects.values_list("pk", flat=True))
    out = seed()
    assert snapshot() == before
    assert set(RotaEntry.objects.values_list("pk", flat=True)) == ids
    assert "0 / 171" in out


def test_refuses_without_the_flags_and_changes_nothing():
    for kwargs in ({}, {"email_base": BASE}, {"yes_this_is_staging": True}):
        with pytest.raises(CommandError) as exc:
            call_command("seed_demo", **kwargs)
        assert "--email-base" in str(exc.value) or "--yes-this-is-staging" in str(exc.value)
    with pytest.raises(CommandError, match="--yes-this-is-staging"):
        call_command("seed_demo", "--email-base", BASE)
    with pytest.raises(CommandError, match="--email-base"):
        call_command("seed_demo", "--yes-this-is-staging")
    assert snapshot()["Clinician"] == 0 and snapshot()["User"] == 0
    assert snapshot()["Site"] == 0 and snapshot()["RotaEntry"] == 0


def test_refuses_with_a_clinician_outside_the_cast_and_changes_nothing():
    make_clinician("Zoe Real")
    make_clinician("Yan Real")
    before = snapshot()
    with pytest.raises(CommandError, match=r"2 clinicians outside the demo cast"):
        seed()
    assert snapshot() == before


def test_an_inactive_or_locum_stranger_still_blocks_it():
    locums = make_group("Locums", is_locum_group=True)
    make_clinician("Lou Locum", group=locums, active=False)
    with pytest.raises(CommandError, match="1 clinician outside"):
        seed()
    assert Site.objects.count() == 0


@pytest.mark.parametrize("base", ["tom", "tom@@example.org", "a@b@example.org",
                                  "tom+x@example.org", "@example.org", "tom@",
                                  "to m@example.org"])
def test_refuses_a_base_that_cannot_make_the_emails(base):
    with pytest.raises(CommandError):
        seed(base)
    assert snapshot()["Clinician"] == 0 and snapshot()["Site"] == 0


def test_refuses_when_the_cast_already_has_logins_under_another_base():
    seed()
    before = snapshot()
    with pytest.raises(CommandError, match="another --email-base"):
        seed("other@example.org")
    assert snapshot() == before


def test_refuses_when_a_login_belongs_to_another_clinician():
    other = make_clinician("Dr Callum Ross")
    user = User.objects.create_user(email=EMAILS["Dr Priya Nair"])
    other.user = user
    other.save()
    before = snapshot()
    with pytest.raises(CommandError, match="already belongs to another clinician"):
        seed()
    assert snapshot() == before


def test_leaves_existing_data_as_it_is():
    group = make_group("Partners", display_order=7)
    elsewhere = make_group("Elsewhere")
    existing = make_clinician("Dr Priya Nair", group=elsewhere, initials="XX")
    Site.objects.create(name="Main Surgery")
    SessionType.objects.create(name="Duty doctor", code="D", category="CLINICAL",
                               colour="red-soft")
    PracticeSettings.objects.create(pk=1, min_clinical_per_session=2)
    seed()
    existing.refresh_from_db()
    assert (existing.group, existing.initials) == (elsewhere, "XX")
    assert existing.user.email == EMAILS["Dr Priya Nair"]  # linked, nothing else
    group.refresh_from_db()
    assert group.display_order == 7
    duty = SessionType.objects.get(name="Duty doctor")
    assert (duty.code, duty.colour) == ("D", "red-soft")
    ps = PracticeSettings.load()
    assert ps.min_clinical_per_session == 2
    assert ps.default_fill_session_type.name == "Admin"
    assert Site.objects.count() == 1


def test_a_pattern_somebody_set_is_not_added_to():
    seed()
    helen = Clinician.objects.get(name="Dr Helen Okafor")
    PatternSlot.objects.filter(clinician=helen).update(works=False)
    PatternSlot.objects.filter(clinician=helen, weekday=2, part="AM").update(works=True)
    seed()
    assert PatternSlot.objects.filter(clinician=helen, works=True).count() == 1


def test_sends_no_email_whatever_the_relay_is_set_to(settings, monkeypatch):
    settings.EMAIL_HOST = "smtp.example"
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "Practice Rota <rota@example.org>"

    def boom(*a, **k):
        raise AssertionError("the SMTP backend was used")

    monkeypatch.setattr("django.core.mail.backends.smtp.EmailBackend.send_messages", boom)
    monkeypatch.setattr("accounts.mail.send_password_link", boom, raising=False)
    mail.outbox.clear()
    seed()
    seed()
    assert mail.outbox == []


def test_the_whole_run_is_one_transaction(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fell over part way")

    monkeypatch.setattr("rota.services.entries.assign_full_day", boom)
    before = snapshot()
    with pytest.raises(RuntimeError):
        seed()
    assert snapshot() == before


@pytest.fixture
def api(client, settings):
    cache.clear()
    settings.ROTA_API_TOKENS = frozenset({"t0k"})
    yield lambda url: client.get(url, HTTP_AUTHORIZATION="Bearer t0k")
    cache.clear()


def test_the_sessions_feed_names_the_three_by_their_emails(api):
    seed()
    monday = this_monday()
    end = monday + timedelta(weeks=9, days=-1)
    r = api(f"/api/v1/sessions?from={monday.isoformat()}&to={end.isoformat()}")
    assert r.status_code == 200
    body = r.json()
    assert body["without_email"] == 0
    assert Counter(s["email"] for s in body["sessions"]) == {
        EMAILS["Dr Priya Nair"]: 72, EMAILS["Dr Callum Ross"]: 54,
        EMAILS["Dr Helen Okafor"]: 45}
    assert {s["site"] for s in body["sessions"]} == {"Main Surgery"}
    assert {s["type"] for s in body["sessions"]} == {
        "Morning surgery", "Afternoon surgery", "Duty doctor"}
