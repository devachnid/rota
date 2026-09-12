"""The one-off import from the old sheet: a CSV of cells and a mapping file
in, drafts out through the same services the grid uses — full duty days
grouped, mentoring paired, locum rows as requirements, notes carried,
nothing written while anything is unmapped or already occupied."""

import csv
import io
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from rota.models import Clinician, LocumRequirement, RotaEntry, RotaEntryLog
from tests.factories import make_clinician, make_group, make_session_type

pytestmark = pytest.mark.django_db

MON = date(2026, 9, 21)
TUE, WED = MON + timedelta(days=1), MON + timedelta(days=2)

MAPPING = '''
[window]
start = 2026-09-21
end = 2026-10-23
[people]
"Alice Adams" = "Alice Adams"
"Dr Beth Brown " = "Beth Brown"
"ST2 - Terry Trainee" = "Terry Trainee"
[skip]
rows = ["FY2"]
[ignore]
rows = ["ROUTINEs (incl locums)"]
[locum_rows]
rows = ["Locum 1"]
session_type = "Routine"
needed = ["Locum needed"]
[locum_people]
"Amjad Mahmood" = "Amjad Mahmood"
[locum_names]
"Dr Laura Edgell" = "Laura Edgell"
[labels]
"Routine" = "Routine"
"Duty" = "Duty"
"Mentoring" = "Mentoring"
"Non Clinical" = "Management"
"Leave" = "Annual leave"
"Vision" = "Routine"
"Off" = ""
[full_day]
types = ["Duty"]
[pairs]
types = ["Mentoring"]
'''


@pytest.fixture
def world():
    make_group("Partners")
    make_group("Locum GPs", is_locum_group=True, display_order=99)
    types = {n: make_session_type(n, code=c, category=cat) for n, c, cat in (
        ("Routine", "Rout", "CLINICAL"), ("Duty", "Duty", "CLINICAL"),
        ("Mentoring", "Mentor", "NON_CLINICAL"), ("Management", "MGT", "NON_CLINICAL"),
        ("Annual leave", "AL", "ABSENCE"))}
    people = {n: make_clinician(n) for n in ("Alice Adams", "Beth Brown", "Terry Trainee")}
    return types, people


def _csv(tmp_path, rows):
    path = tmp_path / "window.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "part", "row", "label", "note"])
        for r in rows:
            w.writerow([r[0].isoformat(), *r[1:], *([""] * (5 - len(r)))])
    return str(path)


def _map(tmp_path, text=MAPPING):
    path = tmp_path / "map.toml"
    path.write_text(text)
    return str(path)


def _run(csv_path, map_path, *flags):
    out = io.StringIO()
    call_command("import_rota", csv_path, "--map", map_path, *flags, stdout=out)
    return out.getvalue()


STANDARD = [
    (MON, "AM", "Alice Adams", "Duty"), (MON, "PM", "Alice Adams", "Duty"),
    (TUE, "AM", "Alice Adams", "Routine", "Cluster meeting 2pm"),
    (TUE, "PM", "Alice Adams", "Off"),
    (MON, "AM", "Dr Beth Brown ", "Leave"), (MON, "PM", "Dr Beth Brown ", "Non Clinical"),
    (WED, "AM", "Dr Beth Brown ", "Mentoring"), (WED, "AM", "ST2 - Terry Trainee", "Mentoring", "first one"),
    (WED, "PM", "ST2 - Terry Trainee", "Vision"),
    (MON, "AM", "FY2", "Off"),
    (MON, "AM", "ROUTINEs (incl locums)", "3"), (MON, "PM", "ROUTINEs (incl locums)", "2"),
    (TUE, "PM", "Dr Beth Brown ", "Off", "at a funeral"),
    (MON, "AM", "Locum 1", "Dr Laura Edgell", "9.30 start"), (MON, "PM", "Locum 1", "Locum needed"),
    (TUE, "AM", "Amjad Mahmood", "Routine"),
    (date(2026, 11, 2), "AM", "Alice Adams", "Routine"),  # outside the window
]


def test_a_dry_run_reports_and_writes_nothing(tmp_path, world):
    out = _run(_csv(tmp_path, STANDARD), _map(tmp_path), "--dry-run")
    assert "(dry run)" in out
    assert "Sessions: 8 — 4 single, 1 full days, 1 pairs; written as drafts" in out
    assert "by type: Routine 2, Duty 2, Mentoring 2, Annual leave 1, Management 1" in out
    assert "Rows skipped (nothing but Off): FY2" in out
    assert "Rows ignored: ROUTINEs (incl locums)" in out
    assert ("Warning: 2026-09-22 PM Dr Beth Brown is 'Off', so nothing is written, "
            "but it carries a note: 'at a funeral'") in out
    assert "Cells outside the window, ignored: 1" in out
    assert "Locum requirements: 2 booked (Amjad Mahmood 1, Laura Edgell 1), 1 possibly needed" in out
    assert "locums to create in the locum group: Amjad Mahmood, Laura Edgell" in out
    assert "Notes carried over: 3" in out
    assert not RotaEntry.objects.exists() and not LocumRequirement.objects.exists()
    assert not Clinician.objects.filter(name="Laura Edgell").exists()


def test_the_import_writes_drafts_through_the_grids_own_services(tmp_path, world):
    types, people = world
    out = _run(_csv(tmp_path, STANDARD), _map(tmp_path))
    assert "Written: 10 sessions" in out
    alice, beth, terry = (people[n] for n in ("Alice Adams", "Beth Brown", "Terry Trainee"))
    # A Duty AM + PM is one full day.
    mon = {e.part: e for e in RotaEntry.objects.filter(clinician=alice, day=MON)}
    assert mon["AM"].allocation_group and mon["AM"].allocation_group == mon["PM"].allocation_group
    # The note rides on the entry; Off writes nothing.
    tue = RotaEntry.objects.get(clinician=alice, day=TUE)
    assert tue.part == "AM" and tue.note == "Cluster meeting 2pm"
    # Leave is an absence entry; Non Clinical is Management; Vision is Routine.
    assert RotaEntry.objects.get(clinician=beth, day=MON, part="AM").session_type == types["Annual leave"]
    assert RotaEntry.objects.get(clinician=beth, day=MON, part="PM").session_type == types["Management"]
    assert RotaEntry.objects.get(clinician=terry, day=WED, part="PM").session_type == types["Routine"]
    # Two people on Mentoring in one slot are a linked pair, sharing the note.
    b, t = (RotaEntry.objects.get(clinician=c, day=WED, part="AM") for c in (beth, terry))
    assert b.companion_group and b.companion_group == t.companion_group
    assert b.note == "first one" and t.note == "first one"
    # Everything is a manually set draft marked as imported.
    imported = RotaEntry.objects.exclude(clinician__group__is_locum_group=True)
    assert imported.count() == 8
    assert all(e.fill_reason == "imported" and e.manually_set and not e.is_published for e in imported)
    # The audit log has a row per created entry and one for the run.
    assert RotaEntryLog.objects.filter(action="created").count() == 10
    run = RotaEntryLog.objects.get(action="imported")
    assert run.detail == "10 sessions from the old rota, 2026-09-21..2026-10-23"


def test_locum_rows_become_requirements(tmp_path, world):
    types, people = world
    _run(_csv(tmp_path, STANDARD), _map(tmp_path))
    laura = Clinician.objects.get(name="Laura Edgell")
    amjad = Clinician.objects.get(name="Amjad Mahmood")
    assert laura.group.is_locum_group and laura.initials == "LE" and amjad.initials == "AM"
    booked = LocumRequirement.objects.get(day=MON, part="AM", clinician=laura)
    assert booked.status == LocumRequirement.Status.BOOKED and booked.details == "9.30 start"
    # The booking's session is a draft like everything else, and marked.
    assert booked.rota_entry.session_type == types["Routine"]
    assert not booked.rota_entry.is_published and booked.rota_entry.fill_reason == "imported"
    assert booked.rota_entry.note == "9.30 start"
    need = LocumRequirement.objects.get(day=MON, part="PM")
    assert need.status == LocumRequirement.Status.POSSIBLE and need.clinician is None
    assert need.session_type == types["Routine"]
    assert LocumRequirement.objects.get(day=TUE, part="AM", clinician=amjad).status == "BOOKED"


def test_publish_writes_published_entries(tmp_path, world):
    _run(_csv(tmp_path, STANDARD), _map(tmp_path), "--publish")
    assert not RotaEntry.objects.filter(is_published=False).exists()


def test_a_second_run_updates_rather_than_duplicates(tmp_path, world):
    types, people = world
    _run(_csv(tmp_path, STANDARD), _map(tmp_path))
    before = RotaEntry.objects.count(), LocumRequirement.objects.count(), Clinician.objects.count()
    changed = [r for r in STANDARD if not (r[0] == TUE and r[2] == "Alice Adams" and r[1] == "AM")]
    changed.append((TUE, "AM", "Alice Adams", "Routine", "moved to 3pm"))
    out = _run(_csv(tmp_path, changed), _map(tmp_path))
    assert "Conflict" not in out
    assert (RotaEntry.objects.count(), LocumRequirement.objects.count(), Clinician.objects.count()) == before
    assert RotaEntry.objects.get(clinician=people["Alice Adams"], day=TUE).note == "moved to 3pm"
    mon = {e.part: e for e in RotaEntry.objects.filter(clinician=people["Alice Adams"], day=MON)}
    assert mon["AM"].allocation_group == mon["PM"].allocation_group


@pytest.mark.parametrize("rows, message", [
    ([(MON, "AM", "Alice Adams", "Aesthetics")], "label 'Aesthetics' is not in [labels]"),
    ([(MON, "AM", "Nobody Known", "Routine")], "row 'Nobody Known' is in the CSV but not in"),
    ([(MON, "AM", "FY2", "Routine")], "a skipped row holds 'Routine'"),
    ([(MON, "AM", "Locum 1", "Dr Unknown")], "locum row holds 'Dr Unknown'"),
    ([(MON, "XX", "Alice Adams", "Routine")], "part 'XX' is not AM or PM"),
])
def test_anything_unaccounted_for_stops_the_import(tmp_path, world, rows, message, capsys):
    with pytest.raises(CommandError, match="problem"):
        call_command("import_rota", _csv(tmp_path, rows + STANDARD[:1]), "--map", _map(tmp_path))
    assert message in capsys.readouterr().out
    assert not RotaEntry.objects.exists()


def test_a_person_the_app_does_not_have_is_a_problem(tmp_path, world):
    mapping = MAPPING.replace('"Alice Adams" = "Alice Adams"', '"Alice Adams" = "Alice Nobody"')
    with pytest.raises(CommandError, match="problem"):
        _run(_csv(tmp_path, STANDARD[:1]), _map(tmp_path, mapping))


def test_a_cell_someone_else_filled_is_a_conflict(tmp_path, world):
    types, people = world
    from tests.factories import make_entry
    make_entry(people["Alice Adams"], day=TUE, part="AM", session_type=types["Duty"], is_published=True)
    with pytest.raises(CommandError, match="1 conflict"):
        _run(_csv(tmp_path, STANDARD), _map(tmp_path))
    assert RotaEntry.objects.count() == 1
    out = _run(_csv(tmp_path, STANDARD), _map(tmp_path), "--skip-conflicts")
    assert "Conflict: 2026-09-22 AM Alice Adams already holds Duty (published) set by hand" in out
    assert "Written: 9 sessions, 1 left alone" in out
    kept = RotaEntry.objects.get(clinician=people["Alice Adams"], day=TUE)
    assert kept.session_type == types["Duty"] and kept.is_published


def test_an_unpaired_mentoring_is_a_warning_and_a_single_entry(tmp_path, world):
    types, people = world
    rows = [(WED, "AM", "Dr Beth Brown ", "Mentoring")]
    out = _run(_csv(tmp_path, rows), _map(tmp_path))
    assert "Warning: 2026-09-23 AM: Mentoring for Beth Brown — 1 person in the slot, so no pair" in out
    e = RotaEntry.objects.get()
    assert e.companion_group is None and e.session_type == types["Mentoring"]


def test_a_locum_name_that_is_a_real_clinician_outside_the_locum_group_is_a_problem(tmp_path, world):
    mapping = MAPPING.replace('"Dr Laura Edgell" = "Laura Edgell"', '"Dr Laura Edgell" = "Beth Brown"')
    with pytest.raises(CommandError, match="problem"):
        _run(_csv(tmp_path, STANDARD), _map(tmp_path, mapping))
    assert not RotaEntry.objects.exists()


def test_the_extraction_script_reads_a_sheet_of_the_old_shape(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    import datetime as dt
    from scripts.old_rota_to_csv import main
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rota 2026"
    for i, day in enumerate((dt.datetime(2026, 9, 18), dt.datetime(2026, 9, 21), dt.datetime(2026, 9, 22))):
        c = 2 + 2 * i
        ws.cell(1, c, day)
        ws.merge_cells(start_row=1, start_column=c, end_row=1, end_column=c + 1)
        ws.cell(2, c, day.strftime("%A"))
        ws.cell(3, c, "AM")
        ws.cell(3, c + 1, "PM")
    ws.cell(4, 1, "Alice  Adams ")
    ws.cell(4, 2, "Routine"); ws.cell(4, 4, "Duty"); ws.cell(4, 5, "Duty"); ws.cell(4, 6, "Off")
    ws.cell(4, 4).comment = openpyxl.comments.Comment("swapped\nwith Beth", "tom")
    ws.cell(5, 1, "Locum 1"); ws.cell(5, 6, "Dr Laura Edgell")
    xlsx = tmp_path / "rota.xlsx"
    wb.save(xlsx)
    out = tmp_path / "window.csv"
    main(str(xlsx), "Rota 2026", "2026-09-21", "2026-09-22", str(out))
    rows = list(csv.DictReader(open(out)))
    assert rows == [
        {"date": "2026-09-21", "part": "AM", "row": "Alice Adams", "label": "Duty", "note": "swapped with Beth"},
        {"date": "2026-09-21", "part": "PM", "row": "Alice Adams", "label": "Duty", "note": ""},
        {"date": "2026-09-22", "part": "AM", "row": "Alice Adams", "label": "Off", "note": ""},
        {"date": "2026-09-22", "part": "AM", "row": "Locum 1", "label": "Dr Laura Edgell", "note": ""},
    ]
