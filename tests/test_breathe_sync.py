"""The sync, against the recorded test account. No network.

The fixtures hold the case that shaped the design: two records that appear
in both /absences and /leave_requests, field-for-field, under different ids.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from django.utils import timezone

from rota.models import BreatheAbsence, BreatheSyncRun
from rota.services.breathe import sync
from rota.services.breathe.client import BreatheError
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"


class FakeClient:
    """Serves the fixtures; `fail` names a resource that raises instead."""
    def __init__(self, fail=None, **overrides):
        self.fail = fail
        self.data = {r: json.loads((FIX / f"{r}.json").read_text())[r]
                     for r in ("leave_requests", "absences", "sicknesses")}
        self.data.update(overrides)
        self.calls = []
    def fetch_all(self, resource):
        self.calls.append(resource)
        if resource == self.fail:
            raise BreatheError("boom", status=500, path=f"/{resource}")
        return self.data[resource]


def _link_everyone():
    """Link a clinician to every employee id that has leave in the fixtures."""
    ids = {2340351, 2340352, 2340353, 2340356, 2340359, 2340361}
    return {i: make_clinician(f"Emp {i}", breathe_employee_id=i) for i in ids}


def test_the_two_endpoint_overlap_becomes_one_row_with_both_ids():
    by_id = _link_everyone()
    run = sync.run(FakeClient())
    assert run.ok
    tom = by_id[2340351]
    rows = BreatheAbsence.objects.filter(
        clinician=tom, kind__in=["holiday", "other"]).order_by("start_date")
    assert [(r.start_date, r.end_date) for r in rows] == [
        (date(2026, 9, 14), date(2026, 9, 22)), (date(2026, 9, 28), date(2026, 9, 30))]
    mat = rows[0]
    assert mat.kind == "other" and mat.reason == "Maternity"
    assert set(mat.source_ids.split(",")) == {"44235958", "37454316"}, "request id first, absence id second"


def test_pending_requests_are_not_leave():
    by_id = _link_everyone()
    sync.run(FakeClient())
    li = by_id[2340356]  # the two pending rows in the fixture are his
    assert not BreatheAbsence.objects.filter(clinician=li).exists()


def test_cancelled_rows_are_dropped():
    by_id = _link_everyone()
    client = FakeClient()
    client.data["leave_requests"][2]["cancelled"] = True  # Kathleen's November holiday (2026-11-02)
    sync.run(client)
    kathleen = by_id[2340352]
    assert BreatheAbsence.objects.filter(clinician=kathleen).count() == 2


def test_sickness_type_never_reaches_the_row():
    by_id = _link_everyone()
    sync.run(FakeClient())
    sick = BreatheAbsence.objects.get(kind="sickness")
    assert sick.reason == ""
    raw = json.loads((FIX / "sicknesses.json").read_text())["sicknesses"][0]
    assert raw["company_sicknesstype"]["name"], "fixture no longer carries a type to guard against"


def test_unlinked_employees_are_counted_not_stored():
    make_clinician("Only Tom", breathe_employee_id=2340351)
    run = sync.run(FakeClient())
    assert run.ok
    assert BreatheAbsence.objects.count() == 3, "Tom's two leaves plus his sickness"
    assert run.n_unlinked == 9, "13 requests - 2 pending - Tom's 2 = 9 approved rows for unlinked people"


def test_counts_are_recorded():
    _link_everyone()
    run = sync.run(FakeClient())
    assert (run.n_requests, run.n_absences, run.n_sicknesses) == (13, 2, 1)
    assert run.n_deduped == 12, "11 approved requests + 1 sickness; both absences collided with requests"
    assert run.finished is not None


def test_a_failed_fetch_leaves_the_previous_overlay_untouched():
    _link_everyone()
    sync.run(FakeClient())
    before = list(BreatheAbsence.objects.values_list("id", "start_date", "clinician_id"))
    run = sync.run(FakeClient(fail="sicknesses"))
    assert run.ok is False and "sicknesses" in run.error
    assert list(BreatheAbsence.objects.values_list("id", "start_date", "clinician_id")) == before


def test_replace_all_removes_leave_that_disappeared_from_breathe():
    by_id = _link_everyone()
    sync.run(FakeClient())
    client = FakeClient()
    client.data["absences"] = []
    client.data["leave_requests"] = [r for r in client.data["leave_requests"]
                                    if r["employee"]["id"] != 2340351]
    sync.run(client)
    assert not BreatheAbsence.objects.filter(clinician=by_id[2340351], kind__in=["holiday", "other"]).exists()


def test_dry_run_writes_nothing_but_reports_counts():
    _link_everyone()
    run = sync.run(FakeClient(), dry_run=True)
    assert run.ok and run.n_deduped == 12
    assert BreatheAbsence.objects.count() == 0
    assert BreatheSyncRun.objects.count() == 0


def test_contradictory_single_day_flags_are_logged_and_kept(caplog):
    """The row is stored — parts_off yields nothing for it, so it has no
    effect — and the run notes it, so someone can fix it in Breathe."""
    by_id = _link_everyone()
    client = FakeClient()
    bad = dict(client.data["leave_requests"][0])
    bad.update({"id": 999, "start_date": "2026-12-01", "end_date": "2026-12-01",
                "half_start": True, "half_start_am_pm": "AM",
                "half_end": True, "half_end_am_pm": "PM"})
    client.data["leave_requests"].append(bad)
    import logging
    with caplog.at_level(logging.WARNING, logger="rota.breathe"):
        run = sync.run(client)
    assert run.ok
    assert "999" in caplog.text and "contradict" in caplog.text.lower()


def test_the_management_command_runs_and_reports(capsys):
    from django.core.management import call_command
    from unittest import mock
    _link_everyone()
    with mock.patch("rota.services.breathe.client.from_settings", return_value=FakeClient()):
        call_command("breathe_sync")
    out = capsys.readouterr().out
    assert "12" in out and "ok" in out.lower()
    assert BreatheSyncRun.objects.count() == 1


def test_the_command_exits_cleanly_when_the_integration_is_off(capsys, settings):
    from django.core.management import call_command
    settings.BREATHE_API_KEY = ""
    call_command("breathe_sync")
    assert "not configured" in capsys.readouterr().out.lower()
    assert BreatheSyncRun.objects.count() == 0
