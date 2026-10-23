"""The sync, against the synthetic account. No network.

The fixtures are the shape a real account sent (see their README) and
hold the cases that shape the design: a record entered twice for the same
days, a pending request and a deleted record, a weekday mask with a day
unticked, a type named by id only, a record with no type, one assigned to
no one, one for someone the rota has no clinician for, and a recurring one.
"""

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from rota.models import TimeOff, TimeOffSyncRun
from rota.services.findmyshift import sync
from rota.services.findmyshift.client import FindMyShiftError
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "findmyshift"
STAFF = ["S1", "S2", "S3", "S4", "S5", "S6"]


class FakeClient:
    """Serves the fixtures; `fail` names a method that raises instead."""
    def __init__(self, fail=None, **overrides):
        self.fail = fail
        self.data = {name: json.loads((FIX / f"{name}.json").read_text())
                     for name in ("teams", "staff", "time-off")}
        self.data.update(overrides)
        self.calls = []

    def _serve(self, name):
        self.calls.append(name)
        if name == self.fail:
            raise FindMyShiftError("boom", status=500, method=name)
        return self.data[name]

    def teams(self):
        return self._serve("teams")

    def staff(self, team_id=None):
        # As the real client projects it: `id` filled from staffId.
        return [dict(s, id=s["staffId"]) for s in self._serve("staff")]

    def time_off(self, team_id, since, until):
        self.calls.append(("time-off", team_id, since, until))
        if self.fail == "time-off":
            raise FindMyShiftError("boom", status=500, method="time-off/list")
        return self.data["time-off"]


def _link_everyone():
    return {sid: make_clinician(f"Staff {sid}", findmyshift_staff_id=sid) for sid in STAFF}


def _spans(clinician):
    return [(r.start_date, r.end_date) for r in TimeOff.objects.filter(clinician=clinician)]


def test_counts_are_recorded():
    _link_everyone()
    run = sync.run(FakeClient())
    assert run.ok, run.error
    assert run.n_teams == 1 and run.n_records == 13
    assert run.n_approved == 10, "13 - 1 pending - 1 deleted - 1 assigned to no one"
    assert run.n_deduped == 10, "TO4 splits in two around its unticked Wednesday; TO10 is TO2 entered twice"
    assert run.n_unlinked == 1, "S99"
    assert run.finished is not None
    assert TimeOff.objects.count() == 9


def test_first_and_last_day_off_are_the_span():
    by_id = _link_everyone()
    sync.run(FakeClient())
    assert _spans(by_id["S1"]) == [(date(2026, 9, 14), date(2026, 9, 22)),
                                   (date(2026, 9, 28), date(2026, 9, 30))]
    row = TimeOff.objects.get(clinician=by_id["S1"], start_date=date(2026, 9, 14))
    assert not row.half_start and not row.half_end, "FindMyShift time off is whole days"
    assert row.reason == "Maternity"


def test_a_record_entered_twice_becomes_one_row_with_both_ids():
    by_id = _link_everyone()
    sync.run(FakeClient())
    row = TimeOff.objects.get(clinician=by_id["S1"], start_date=date(2026, 9, 28))
    assert row.source_ids.split(",") == ["TO2", "TO10"]
    assert row.reason == "Holiday"


def test_an_unticked_weekday_splits_the_range():
    """`days` is the weekdays the time off applies to, Sunday 0. Monday to
    Friday with Wednesday unticked is two runs; the Wednesday is a working
    day."""
    by_id = _link_everyone()
    sync.run(FakeClient())
    assert _spans(by_id["S2"]) == [(date(2026, 10, 5), date(2026, 10, 6)),
                                   (date(2026, 10, 8), date(2026, 10, 9)),
                                   (date(2026, 11, 2), date(2026, 11, 6))]


def test_day_runs_number_sunday_as_zero():
    mon, sun = date(2026, 10, 5), date(2026, 10, 11)
    assert sync.fms_weekday(sun) == 0 and sync.fms_weekday(mon) == 1
    assert sync.day_runs(mon, sun, {1, 2, 3, 4, 5}) == [(mon, date(2026, 10, 9))]
    assert sync.day_runs(mon, sun, {0, 6}) == [(date(2026, 10, 10), sun)]
    assert sync.day_runs(mon, sun, set()) == []


def test_a_pending_request_is_not_leave():
    """Pending is dateApproved null with dateRequested set."""
    by_id = _link_everyone()
    sync.run(FakeClient())
    assert not TimeOff.objects.filter(clinician=by_id["S4"]).exists()


def test_a_deleted_record_is_dropped():
    """Deleted is dateDeleted set; the record still comes back in the list."""
    by_id = _link_everyone()
    sync.run(FakeClient())
    assert [r.reason for r in TimeOff.objects.filter(clinician=by_id["S5"])] == ["Unpaid leave"]


def test_a_record_assigned_to_no_one_is_nobodys_time_off():
    _link_everyone()
    run = sync.run(FakeClient())
    assert run.ok
    assert not TimeOff.objects.filter(start_date=date(2026, 10, 26), end_date=date(2026, 10, 26)).exists()
    assert run.n_unlinked == 1, "not counted as unlinked either — there is no one to link"


def test_a_type_named_by_id_only_gets_the_teams_name():
    by_id = _link_everyone()
    sync.run(FakeClient())
    row = TimeOff.objects.get(clinician=by_id["S3"], start_date=date(2026, 9, 21))
    assert row.reason == "Sick leave"


def test_a_record_with_no_type_is_stored_blank():
    by_id = _link_everyone()
    sync.run(FakeClient())
    row = TimeOff.objects.get(clinician=by_id["S6"])
    assert (row.start_date, row.end_date, row.reason) == (date(2026, 11, 16), date(2026, 11, 20), "")


def test_a_recurring_record_is_read_once_and_logged(caplog):
    by_id = _link_everyone()
    with caplog.at_level(logging.WARNING, logger="rota.findmyshift"):
        sync.run(FakeClient())
    assert (date(2026, 12, 1), date(2026, 12, 2)) in _spans(by_id["S3"])
    assert "TO13" in caplog.text and "recurs" in caplog.text


def test_the_managers_notes_never_reach_the_row():
    _link_everyone()
    sync.run(FakeClient())
    raw = json.loads((FIX / "time-off.json").read_text())
    assert any(r.get("managerNotes") for r in raw), "fixture no longer carries a note to guard against"
    for row in TimeOff.objects.all():
        assert "twice" not in row.reason and "no one" not in row.reason
    for name in ("managerNotes", "description"):
        assert name not in [n for names in sync.FIELDS.values() for n in names]


def test_a_record_with_no_approval_field_counts_as_approved():
    """An account that never marks approval is one where approval is not
    in use; hiding its time off would be the worse error."""
    make_clinician("One", findmyshift_staff_id="S1")
    row = {"timeOffId": "X", "staffId": "S1", "firstDayOff": "2026-10-05",
           "lastDayOff": "2026-10-06", "type": "Holiday"}
    run = sync.run(FakeClient(**{"time-off": [row]}))
    assert run.ok and run.n_approved == 1
    assert TimeOff.objects.count() == 1


@pytest.mark.parametrize("value, expected", [
    ("2026-10-23T15:41:39.263Z", True), (True, True), ("yes", True), (1, True),
    (None, "default"), (False, False), ("no", False), ("", False), ("pending", False), (0, False),
])
def test_as_bool_reads_timestamps_words_and_flags(value, expected):
    assert sync.as_bool(value, default="default") == expected


def test_unlinked_staff_are_counted_not_stored():
    make_clinician("Only Tom", findmyshift_staff_id="S1")
    run = sync.run(FakeClient())
    assert run.ok
    assert TimeOff.objects.count() == 2, "Tom's maternity leave and his holiday"
    assert run.n_unlinked == 8, "10 deduped rows, 2 of them Tom's"


def test_a_failed_fetch_leaves_the_previous_overlay_untouched():
    _link_everyone()
    sync.run(FakeClient())
    before = list(TimeOff.objects.values_list("id", "start_date", "clinician_id"))
    run = sync.run(FakeClient(fail="time-off"))
    assert run.ok is False and "time-off/list" in run.error
    assert list(TimeOff.objects.values_list("id", "start_date", "clinician_id")) == before


def test_a_failed_team_listing_is_reported_by_method():
    run = sync.run(FakeClient(fail="teams"))
    assert run.ok is False and "teams" in run.error


def test_a_configured_team_narrows_the_listing(settings):
    settings.FINDMYSHIFT_TEAM_ID = "T2"
    client = FakeClient(teams=[{"teamId": "T1"}, {"teamId": "T2"}])
    run = sync.run(client)
    assert run.n_teams == 1
    assert [c[1] for c in client.calls if isinstance(c, tuple)] == ["T2"]


def test_a_configured_team_the_key_cannot_see_is_an_error(settings):
    settings.FINDMYSHIFT_TEAM_ID = "T9"
    run = sync.run(FakeClient())
    assert run.ok is False and "T9" in run.error


def test_every_team_is_read_when_none_is_configured(settings):
    settings.FINDMYSHIFT_TEAM_ID = ""
    client = FakeClient(teams=[{"teamId": "T1"}, {"teamId": "T2"}])
    run = sync.run(client)
    assert run.n_teams == 2
    assert [c[1] for c in client.calls if isinstance(c, tuple)] == ["T1", "T2"]


def test_no_teams_is_an_error_not_an_empty_sync():
    run = sync.run(FakeClient(teams=[]))
    assert run.ok is False and "FINDMYSHIFT_TEAM_ID" in run.error


def test_the_window_is_a_year_back_and_two_ahead():
    client = FakeClient()
    sync.run(client, now=None)
    (_, _, since, until) = next(c for c in client.calls if isinstance(c, tuple))
    assert (date.today() - since).days == sync.HISTORY_DAYS
    assert (until - date.today()).days == sync.HORIZON_DAYS


def test_an_unreadable_record_records_a_failed_run_naming_its_keys():
    """A record missing a field it must have fails the run — and says which
    keys it did carry, which is the first thing to know about a response
    shape nobody documented. The overlay keeps the last good sync."""
    _link_everyone()
    sync.run(FakeClient())
    before = list(TimeOff.objects.values_list("id", "start_date", "clinician_id"))
    client = FakeClient()
    client.data["time-off"][0] = {"timeOffId": "TO1", "staffId": "S1", "firstDayOff": None,
                                  "type": "Holiday"}

    run = sync.run(client)

    assert run.ok is False
    assert "Unreadable" in run.error and "'TO1'" in run.error
    assert "start/end" in run.error and "'staffId'" in run.error
    assert run.finished is not None
    assert TimeOffSyncRun.objects.filter(ok=False).count() == 1, "the failure is on record"
    assert list(TimeOff.objects.values_list("id", "start_date", "clinician_id")) == before


def test_alternative_field_names_are_read():
    """The pre-measurement names still work, and a time with a clock in it
    still becomes half a day — in case another account, or a later API,
    sends them."""
    make_clinician("One", findmyshift_staff_id="S1")
    row = {"id": 7, "staff": {"id": "S1"}, "from": "2026-10-05T13:00:00",
           "to": "2026-10-06T23:59:59", "approved": "yes", "reason": {"name": "Holiday"}}
    run = sync.run(FakeClient(**{"time-off": [row]}))
    assert run.ok, run.error
    stored = TimeOff.objects.get()
    assert stored.reason == "Holiday" and stored.source_ids == "7"
    assert stored.half_start and stored.half_start_am_pm == "PM"


@pytest.mark.parametrize("value, expected", [
    ("2026-10-05", date(2026, 10, 5)),
    ("2026-10-05T13:00:00", "2026-10-05 13:00"),
    ("2026-10-05 13:00", "2026-10-05 13:00"),
    # An offset is honoured and the value moved to the practice's clock:
    # 13:00 UTC on an October day is 14:00 in London.
    ("2026-10-05T13:00:00Z", "2026-10-05 14:00"),
    ("2026-10-23T15:41:39.263Z", "2026-10-23 16:41"),
    ("2026-10-05T13:00:00+01:00", "2026-10-05 13:00"),
    ("/Date(1791205200000)/", "2026-10-05 14:00"),
    (1791205200000, "2026-10-05 14:00"),
])
def test_dates_in_the_forms_a_dotnet_api_sends(value, expected, settings):
    settings.TIME_ZONE = "Europe/London"
    got = sync.parse_when(value)
    if isinstance(expected, date):
        assert got == expected
    else:
        assert f"{got:%Y-%m-%d %H:%M}" == expected


def test_replace_all_removes_leave_that_disappeared():
    by_id = _link_everyone()
    sync.run(FakeClient())
    client = FakeClient()
    client.data["time-off"] = [r for r in client.data["time-off"] if r["staffId"] != "S1"]
    sync.run(client)
    assert not TimeOff.objects.filter(clinician=by_id["S1"]).exists()


def test_dry_run_writes_nothing_but_reports_counts():
    _link_everyone()
    run = sync.run(FakeClient(), dry_run=True)
    assert run.ok and run.n_deduped == 10
    assert TimeOff.objects.count() == 0
    assert TimeOffSyncRun.objects.count() == 0


def test_inspect_names_fields_and_reasons_but_no_values():
    text = sync.inspect(FakeClient())
    assert "time off: 13 records" in text
    assert "staff: 7 records; with an id: 7" in text
    assert "time-off types ['Holiday', 'Maternity', 'Personal', 'Sick leave', 'Training', 'Unpaid leave']" in text
    assert "start: read from 'firstDayOff'" in text
    assert "approved: read from 'dateApproved'" in text
    assert "reasons seen: ['', 'Holiday', 'Maternity', 'Sick leave', 'Training', 'Unpaid leave']" in text
    assert "pending: 1; deleted: 1; for no one: 1; recurring: 1; with a weekday mask: 2" in text
    assert "S99" not in text and "Tom" not in text and "example.org" not in text
    assert "twice" not in text, "a manager's note is a value"


def test_the_management_command_runs_and_reports(capsys):
    from django.core.management import call_command
    from unittest import mock
    _link_everyone()
    with mock.patch("rota.services.findmyshift.client.from_settings", return_value=FakeClient()):
        call_command("findmyshift_sync")
    out = capsys.readouterr().out
    assert "10 after dedup" in out and "ok" in out.lower()
    assert TimeOffSyncRun.objects.count() == 1


def test_the_command_can_inspect(capsys):
    from django.core.management import call_command
    from unittest import mock
    with mock.patch("rota.services.findmyshift.client.from_settings", return_value=FakeClient()):
        call_command("findmyshift_sync", "--inspect")
    out = capsys.readouterr().out
    assert "reasons seen" in out
    assert TimeOffSyncRun.objects.count() == 0


def test_the_command_exits_cleanly_when_the_integration_is_off(capsys, settings):
    from django.core.management import call_command
    settings.FINDMYSHIFT_API_KEY = ""
    call_command("findmyshift_sync")
    assert "not configured" in capsys.readouterr().out.lower()
    assert TimeOffSyncRun.objects.count() == 0
