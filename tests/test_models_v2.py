from datetime import date

import pytest
from django.core.exceptions import ValidationError

from rota.models import CoverageRule, PatternSlot, PracticeSettings
from tests.factories import MON, make_session_type

pytestmark = pytest.mark.django_db


def _rule(**kw):
    kw.setdefault("session_type", make_session_type())
    return CoverageRule.objects.create(**kw)


def test_months_blank_means_all_year():
    r = _rule()
    assert r.applies_on(date(2026, 1, 5))   # a Monday in January
    assert r.applies_on(date(2026, 7, 20))  # a Monday in July


def test_months_window_filters():
    winter = _rule(months="10,11,12,1,2,3,4")
    assert winter.applies_on(date(2026, 1, 5))       # Jan Monday: in window
    assert not winter.applies_on(date(2026, 7, 20))  # Jul Monday: out
    assert not winter.applies_on(date(2026, 1, 4))   # Jan Sunday: weekday fails


def test_frequency_defaults_to_per_slot():
    assert _rule().frequency == CoverageRule.Frequency.PER_SLOT


def test_preferred_weekday_list_ordered():
    r = _rule(preferred_weekdays="3,1")
    assert r.preferred_weekday_list() == [3, 1]
    assert _rule().preferred_weekday_list() == []


def test_blocks_same_day_m2m():
    pmc = make_session_type("PMC - Routine")
    duty = make_session_type("Duty", fairness_tracked=True)
    pmc.blocks_same_day.add(duty)
    assert duty in pmc.blocks_same_day.all()
    assert pmc not in duty.blocks_same_day.all()  # asymmetric


def test_practice_settings_type_fks_default_null():
    s = PracticeSettings.load()
    assert s.vts_session_type is None
    assert s.sdl_session_type is None
    assert s.mentoring_session_type is None


# --- Finding C: PER_DAY + PER_WEEK/PER_MONTH with odd count -------------

def test_per_day_odd_count_weekly_rule_rejected():
    # unit=PER_DAY places a full day (2 sessions) at a time, so an odd
    # weekly count can never be satisfied and would silently place nothing
    # forever.
    rule = _rule(unit=CoverageRule.Unit.PER_DAY,
                frequency=CoverageRule.Frequency.PER_WEEK, count=1)
    with pytest.raises(ValidationError):
        rule.full_clean()


def test_per_day_odd_count_monthly_rule_rejected():
    rule = _rule(unit=CoverageRule.Unit.PER_DAY,
                frequency=CoverageRule.Frequency.PER_MONTH, count=3)
    with pytest.raises(ValidationError):
        rule.full_clean()


def test_per_day_even_count_weekly_rule_passes_clean():
    rule = _rule(unit=CoverageRule.Unit.PER_DAY,
                frequency=CoverageRule.Frequency.PER_WEEK, count=2)
    rule.full_clean()  # must not raise


def test_per_day_odd_count_per_slot_rule_unaffected():
    # PER_SLOT isn't a quota frequency, so this combination is untouched.
    rule = _rule(unit=CoverageRule.Unit.PER_DAY,
                frequency=CoverageRule.Frequency.PER_SLOT, count=1)
    rule.full_clean()  # must not raise


from rota.models import TraineeStageRule  # noqa: E402
from tests.factories import make_clinician, make_trainee  # noqa: E402


def test_stage_rules_seeded():
    rules = {r.stage: r for r in TraineeStageRule.objects.all()}
    assert set(rules) == {"FY2", "ST1", "ST2", "ST3"}
    assert float(rules["ST3"].vts_per_week) == 1.0
    assert rules["ST3"].vts_weekday == 1 and rules["ST3"].vts_part == "PM"
    assert rules["ST2"].vts_weekday == 1 and rules["ST2"].vts_part == "AM"
    assert float(rules["FY2"].vts_per_week) == 0.0
    assert float(rules["FY2"].sdl_per_week) == 2.0
    assert float(rules["FY2"].mentoring_per_week) == 1.0
    # ST1's seed must match ST2's (1/1/1 per week, anchored Tuesday AM) —
    # only ST1's presence in the stage set was asserted before, so a wrong
    # seed value for ST1 specifically would pass silently.
    assert float(rules["ST1"].vts_per_week) == float(rules["ST2"].vts_per_week) == 1.0
    assert float(rules["ST1"].sdl_per_week) == float(rules["ST2"].sdl_per_week) == 1.0
    assert (float(rules["ST1"].mentoring_per_week)
            == float(rules["ST2"].mentoring_per_week) == 1.0)
    assert rules["ST1"].vts_weekday == rules["ST2"].vts_weekday == 1
    assert rules["ST1"].vts_part == rules["ST2"].vts_part == "AM"


def test_stage_rule_admin_forbids_delete(staff_client):
    # The four rows are seeded reference data, not user content — deleting
    # one from the admin should not be possible (see stage_rule() above for
    # what happens if it does).
    rule = TraineeStageRule.objects.get(stage="ST2")
    resp = staff_client.get(f"/admin/rota/traineestagerule/{rule.pk}/delete/")
    assert resp.status_code == 403
    resp = staff_client.post(f"/admin/rota/traineestagerule/{rule.pk}/delete/",
                             {"post": "yes"})
    assert resp.status_code == 403
    assert TraineeStageRule.objects.filter(pk=rule.pk).exists()


def test_stage_rule_deleted_yields_zero_rates_not_a_crash():
    # Deleting a seeded TraineeStageRule row (nothing at the DB level
    # prevents it) used to raise DoesNotExist from stage_rule(), 500ing the
    # trainee report and any fill for a trainee at that stage.
    c = make_clinician("Terry Trainee")
    profile = make_trainee(clinician=c, stage="ST2")
    TraineeStageRule.objects.filter(stage="ST2").delete()
    assert profile.stage_rule() is None
    assert profile.weekly_rates() == {
        "vts": (0.0, None, None),
        "sdl": (0.0, None, None),
        "mentoring": (0.0, None, None),
    }


def test_weekly_rates_scaled_by_wte():
    t = make_trainee(stage="ST3", wte=60)
    rates = t.weekly_rates()
    assert rates["vts"] == (0.6, 1, "PM")
    assert rates["sdl"] == (0.6, None, None)
    assert rates["mentoring"] == (0.6, None, None)


def test_weekly_rates_fy2():
    t = make_trainee(stage="FY2", wte=100)
    rates = t.weekly_rates()
    assert rates["vts"][0] == 0.0
    assert rates["sdl"][0] == 2.0
    assert rates["mentoring"][0] == 1.0


from datetime import timedelta  # noqa: E402

from tests.factories import make_commitment  # noqa: E402


def test_commitment_occurs_on_weekday_in_window():
    c = make_commitment(make_clinician(), weekday=0, part="AM")
    assert c.occurs_on(MON)
    assert not c.occurs_on(MON + timedelta(days=1))


def test_commitment_respects_active_window():
    c = make_commitment(make_clinician(), weekday=0,
                        active_from=MON + timedelta(days=7))
    assert not c.occurs_on(MON)
    assert c.occurs_on(MON + timedelta(days=7))
    c.active_until = MON + timedelta(days=7)
    assert not c.occurs_on(MON + timedelta(days=14))


def test_commitment_fortnightly_anchored_to_active_from_week():
    c = make_commitment(make_clinician(), weekday=0, interval_weeks=2,
                        active_from=MON)
    assert c.occurs_on(MON)
    assert not c.occurs_on(MON + timedelta(days=7))
    assert c.occurs_on(MON + timedelta(days=14))


def test_commitment_fortnightly_anchor_normalizes_non_monday_active_from():
    # active_from is a Wednesday, not a Monday; the fortnight anchor must
    # normalize to that week's Monday (MON here) before computing parity,
    # not use active_from's raw date. If it didn't normalize, the parity of
    # every later Monday relative to a Wednesday anchor would come out
    # different from what's asserted below.
    active_from = MON + timedelta(days=2)  # Wednesday
    c = make_commitment(make_clinician(), weekday=0, interval_weeks=2,
                        active_from=active_from)
    assert not c.occurs_on(MON)                    # before active_from
    assert not c.occurs_on(MON + timedelta(days=7))    # 1 week after anchor: odd
    assert c.occurs_on(MON + timedelta(days=14))       # 2 weeks after anchor: even
    assert not c.occurs_on(MON + timedelta(days=21))   # 3 weeks after anchor: odd
    assert c.occurs_on(MON + timedelta(days=28))       # 4 weeks after anchor: even


def test_commitment_parts_list():
    cl = make_clinician()
    assert make_commitment(cl, part="BOTH").parts_list() == ["AM", "PM"]
    assert make_commitment(cl, part="PM", weekday=2).parts_list() == ["PM"]


def test_patternslot_weekday_out_of_range_fails_full_clean():
    slot = PatternSlot(clinician=make_clinician(), weekday=7, part="AM",
                       effective_from=MON)
    with pytest.raises(ValidationError):
        slot.full_clean()
    slot.weekday = -1
    with pytest.raises(ValidationError):
        slot.full_clean()


def test_practicesettings_admin_refuses_second_row(staff_client):
    resp = staff_client.get("/admin/rota/practicesettings/add/")
    assert resp.status_code == 200
    PracticeSettings.objects.create(pk=1)
    resp = staff_client.get("/admin/rota/practicesettings/add/")
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# the prefetched stage-rule mapping
# --------------------------------------------------------------------------

def test_stage_rule_accepts_a_prefetched_mapping():
    """The report and every trainee fill pass iterate profiles, so they hand
    weekly_rates() a mapping instead of paying a query each time round."""
    t = make_trainee(stage="ST3")
    rules = {r.stage: r for r in TraineeStageRule.objects.all()}
    assert t.stage_rule(rules) == t.stage_rule()
    assert t.weekly_rates(rules) == t.weekly_rates()


def test_a_mapping_missing_this_stage_reads_as_no_rule_not_a_crash():
    """This is why the mapping needs no sentinel: absent-from-mapping and
    row-deleted are the same answer, and weekly_rates already handles it."""
    t = make_trainee(stage="ST3")
    assert t.stage_rule({}) is None
    assert t.weekly_rates({}) == {
        "vts": (0.0, None, None),
        "sdl": (0.0, None, None),
        "mentoring": (0.0, None, None),
    }


def test_the_mapping_is_used_instead_of_the_database():
    """A mapping is authoritative — passing one must not fall back to a
    query, or the N+1 it exists to remove would still be there."""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    t = make_trainee(stage="ST3")
    rules = {r.stage: r for r in TraineeStageRule.objects.all()}
    with CaptureQueriesContext(connection) as ctx:
        t.weekly_rates(rules)
    assert len(ctx) == 0, f"expected no query, ran {len(ctx)}: {[q['sql'] for q in ctx]}"


def test_without_a_mapping_it_still_queries_for_itself():
    """Callers that hold a single profile keep the simple behaviour."""
    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    t = make_trainee(stage="ST3")
    with CaptureQueriesContext(connection) as ctx:
        assert t.stage_rule() is not None
    assert len(ctx) == 1
