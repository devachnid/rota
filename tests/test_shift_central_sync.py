"""Time off read from Shift Central: matched by the clinician's login email,
replaced in full, parts as AM/PM, never a name or a note in the run."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from rota.models import TimeOff, TimeOffSyncRun
from rota.services.shift_central import sync
from rota.services.shift_central.client import ShiftCentralError
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db
FIX = Path(__file__).resolve().parent / "fixtures" / "shift_central" / "leave.json"
User = get_user_model()


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else json.loads(FIX.read_text())
        self.error = error
        self.calls = []

    def leave(self, start, end):
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return self.payload


def _people():
    alice = make_clinician("Alice Adams", user=User.objects.create_user(email="alice@example.org", password="pw"))
    bob = make_clinician("Bob Brown", user=User.objects.create_user(email="Bob@Example.org", password="pw"))
    return alice, bob


def test_records_become_time_off_rows_by_email_case_insensitively():
    alice, bob = _people()
    run = sync.run(FakeClient())
    assert run.ok, run.error
    rows = list(TimeOff.objects.filter(clinician=alice).order_by("start_date"))
    assert [(r.start_date, r.end_date, r.half_start, r.half_start_am_pm, r.half_end, r.half_end_am_pm, r.reason) for r in rows] == [
        (date(2027, 3, 10), date(2027, 3, 12), False, "", False, "", "Holiday"),
        (date(2027, 3, 15), date(2027, 3, 15), False, "", True, "AM", "Training")]
    pm = TimeOff.objects.get(clinician=bob)
    assert (pm.half_start, pm.half_start_am_pm, pm.reason) == (True, "PM", "Sick leave")


def test_counts_are_recorded_and_emails_only_in_detail():
    _people()
    run = sync.run(FakeClient())
    assert (run.n_records, run.n_matched, run.n_unmatched, run.n_outside) == (6, 2, 1, 1)      # two clinicians matched, Alice twice
    assert run.detail == {"unmatched": ["nobody@example.org"]}
    assert "nobody" not in run.error and sync.unmatched_emails() == ["nobody@example.org"]
    assert TimeOff.objects.count() == 3          # the duplicate collapses onto the content key


def test_the_window_and_replace_in_full():
    alice, _ = _people()
    client = FakeClient()
    sync.run(client, now=datetime(2027, 1, 5, 12, tzinfo=timezone.utc))
    assert client.calls == [(date(2026, 1, 5), date(2029, 1, 4))]
    TimeOff.objects.create(clinician=alice, start_date=date(2027, 6, 1), end_date=date(2027, 6, 1), reason="Stale")
    sync.run(FakeClient())
    assert not TimeOff.objects.filter(reason="Stale").exists() and TimeOff.objects.count() == 3


def test_a_failed_fetch_keeps_the_rows_and_records_the_error():
    alice, _ = _people()
    sync.run(FakeClient())
    run = sync.run(FakeClient(error=ShiftCentralError("Shift Central returned 503 for leave")))
    assert not run.ok and "503" in run.error and TimeOff.objects.count() == 3
    assert TimeOffSyncRun.objects.count() == 2


def test_dry_run_writes_nothing():
    _people()
    run = sync.run(FakeClient(), dry_run=True)
    assert run.ok and run.n_matched == 2 and TimeOff.objects.count() == 0 and TimeOffSyncRun.objects.count() == 0


def test_a_bad_record_fails_the_run_without_naming_anyone():
    _people()
    payload = {"leave": [{"email": "alice@example.org", "first_day": "nope", "last_day": "2027-03-12", "part": "whole", "type": "Holiday"}]}
    run = sync.run(FakeClient(payload))
    assert not run.ok and "record 1" in run.error and "alice" not in run.error
