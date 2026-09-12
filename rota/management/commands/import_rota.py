"""One-off: bring sessions across from the old Google Sheets rota.

Reads the long CSV that scripts/old_rota_to_csv.py writes (one line per
sheet cell: date, part, row, label, note) and a mapping file that says
what every row and every label means here. Refuses to run while anything
is unaccounted for, prints what it would do, and by default writes
drafts — review each week on the grid, then Publish week.

Everything goes through the same services the grid uses, so audit rows
are written, every entry is manually set (assisted fill leaves it alone),
a Duty AM + PM is one full day, and two people on Mentoring in the same
slot are a linked pair. Each entry carries fill_reason "imported", which
is how a second run recognises its own work and updates it rather than
duplicating it, and how a cell somebody else filled is told apart and
left alone.
"""

import csv
import datetime as dt
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rota.models import (Clinician, ClinicianGroup, LocumRequirement, Part,
                         RotaEntry, RotaEntryLog, SessionType)
from rota.services import entries as entries_svc
from rota.services import locums as locums_svc

IMPORTED = "imported"


@dataclass(frozen=True)
class Cell:
    clinician: Clinician
    day: dt.date
    part: str
    session_type: SessionType
    note: str


@dataclass(frozen=True)
class Booking:
    """A locum's session: the locum by name (created if need be)."""
    locum: str
    day: dt.date
    part: str
    session_type: SessionType
    note: str


@dataclass(frozen=True)
class Need:
    day: dt.date
    part: str
    session_type: SessionType
    note: str


@dataclass
class Plan:
    start: dt.date
    end: dt.date
    singles: list = field(default_factory=list)   # Cell
    full_days: list = field(default_factory=list)  # (clinician, day, session_type, note)
    pairs: list = field(default_factory=list)      # (day, part, session_type, c1, c2, note)
    bookings: list = field(default_factory=list)   # Booking
    needs: list = field(default_factory=list)      # Need
    conflicts: list = field(default_factory=list)  # (Cell-or-Booking, existing entry)
    problems: list = field(default_factory=list)   # fatal
    warnings: list = field(default_factory=list)
    skipped_rows: Counter = field(default_factory=Counter)
    ignored_rows: Counter = field(default_factory=Counter)
    outside: int = 0
    new_locums: list = field(default_factory=list)

    def sessions(self):
        return (len(self.singles) + 2 * len(self.full_days) + 2 * len(self.pairs))


def _join_notes(*notes):
    seen = []
    for n in notes:
        if n and n not in seen:
            seen.append(n)
    return "; ".join(seen)[:200]


def _initials(name):
    return "".join(w[0] for w in name.split() if w[0].isalpha()).upper()[:5] or "L"


def load_mapping(path):
    with open(path, "rb") as f:
        m = tomllib.load(f)
    for key in ("window", "people", "labels"):
        if key not in m:
            raise CommandError(f"{path}: no [{key}] section")
    m.setdefault("skip", {}).setdefault("rows", [])
    m.setdefault("ignore", {}).setdefault("rows", [])
    m.setdefault("locum_rows", {}).setdefault("rows", [])
    m["locum_rows"].setdefault("needed", [])
    m.setdefault("locum_people", {})
    m.setdefault("locum_names", {})
    m.setdefault("full_day", {}).setdefault("types", [])
    m.setdefault("pairs", {}).setdefault("types", [])
    # Names are compared with the sheet's spacing collapsed, as the CSV is.
    for section in ("people", "locum_people", "locum_names", "labels"):
        m[section] = {" ".join(k.split()): v for k, v in m[section].items()}
    m["skip"]["rows"] = [" ".join(r.split()) for r in m["skip"]["rows"]]
    m["ignore"]["rows"] = [" ".join(r.split()) for r in m["ignore"]["rows"]]
    m["locum_rows"]["rows"] = [" ".join(r.split()) for r in m["locum_rows"]["rows"]]
    m["locum_rows"]["needed"] = [" ".join(n.split()).lower() for n in m["locum_rows"]["needed"]]
    return m


def read_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for col in ("date", "part", "row", "label", "note"):
        if rows and col not in rows[0]:
            raise CommandError(f"{path}: no {col!r} column — is this the CSV "
                               "scripts/old_rota_to_csv.py writes?")
    return rows


def build_plan(rows, m):
    plan = Plan(m["window"]["start"], m["window"]["end"])
    types = {t.name: t for t in SessionType.objects.all()}
    clinicians = {c.name: c for c in Clinician.objects.all()}
    problems, warnings = plan.problems, plan.warnings

    def session_type(name, what):
        t = types.get(name)
        if t is None:
            problems.append(f"{what}: no session type called {name!r} in the app")
        return t

    locum_type = None
    if m["locum_rows"]["rows"]:
        locum_type = session_type(m["locum_rows"].get("session_type", ""), "[locum_rows] session_type")

    cells = {}   # (clinician_id, day, part) -> Cell
    unmapped_labels, unmapped_rows, unmapped_locums = set(), set(), set()
    for r in rows:
        try:
            day = dt.date.fromisoformat(r["date"])
        except ValueError:
            problems.append(f"bad date {r['date']!r}")
            continue
        if not (plan.start <= day <= plan.end):
            plan.outside += 1
            continue
        part = r["part"].strip().upper()
        if part not in Part.values:
            problems.append(f"{day} {r['row']}: part {r['part']!r} is not AM or PM")
            continue
        row = " ".join(r["row"].split())
        label = " ".join(r["label"].split())
        note = " ".join(r["note"].split())
        what = f"{day} {part} {row}"

        if row in m["ignore"]["rows"]:
            plan.ignored_rows[row] += 1
            continue
        if row in m["skip"]["rows"]:
            if m["labels"].get(label, label) != "":
                problems.append(f"{what}: a skipped row holds {label!r}")
            else:
                plan.skipped_rows[row] += 1
            continue

        if row in m["locum_rows"]["rows"]:
            if locum_type is None:
                continue
            if label.lower() in m["locum_rows"]["needed"]:
                plan.needs.append(Need(day, part, locum_type, note))
            elif label in m["locum_names"]:
                plan.bookings.append(Booking(m["locum_names"][label], day, part, locum_type, note))
            else:
                unmapped_locums.add(label)
            continue

        if label not in m["labels"]:
            unmapped_labels.add(label)
            continue
        type_name = m["labels"][label]
        if type_name == "":
            if note:
                warnings.append(f"{what} is {label!r}, so nothing is written, but it "
                                f"carries a note: {note!r}")
            continue
        st = session_type(type_name, f"label {label!r}")
        if st is None:
            continue

        if row in m["locum_people"]:
            plan.bookings.append(Booking(m["locum_people"][row], day, part, st, note))
            continue
        if row not in m["people"]:
            unmapped_rows.add(row)
            continue
        c = clinicians.get(m["people"][row])
        if c is None:
            problems.append(f"row {row!r} maps to {m['people'][row]!r}, who is not a clinician in the app")
            continue
        key = (c.id, day, part)
        if key in cells:
            problems.append(f"{what}: appears twice in the CSV")
            continue
        cells[key] = Cell(c, day, part, st, note)

    for label in sorted(unmapped_labels):
        problems.append(f"label {label!r} is not in [labels]")
    for row in sorted(unmapped_rows):
        problems.append(f"row {row!r} is in the CSV but not in [people], [skip], "
                        "[locum_rows] or [locum_people]")
    for name in sorted(unmapped_locums):
        problems.append(f"locum row holds {name!r}, which is neither in [locum_names] "
                        "nor a [locum_rows] needed word")

    # Locums named in bookings: created in the locum group if unknown.
    locum_group = ClinicianGroup.objects.filter(is_locum_group=True).first()
    for name in sorted({b.locum for b in plan.bookings}):
        existing = clinicians.get(name)
        if existing is None:
            if locum_group is None:
                problems.append(f"locum {name!r} would be created, but there is no locum group")
            else:
                plan.new_locums.append(name)
        elif not existing.group.is_locum_group:
            problems.append(f"locum {name!r} is a clinician outside the locum group "
                            f"({existing.group.name}); a booking needs a locum")

    # Full days: AM + PM of a full-day type on one day for one person.
    full_types = set(m["full_day"]["types"])
    consumed = set()
    for (cid, day, part), cell in list(cells.items()):
        if part != "AM" or cell.session_type.name not in full_types:
            continue
        pm = cells.get((cid, day, "PM"))
        if pm is not None and pm.session_type == cell.session_type:
            plan.full_days.append((cell.clinician, day, cell.session_type,
                                   _join_notes(cell.note, pm.note)))
            consumed |= {(cid, day, "AM"), (cid, day, "PM")}

    # Pairs: exactly two people on a pair type in the same slot.
    pair_types = set(m["pairs"]["types"])
    by_slot = defaultdict(list)
    for key, cell in cells.items():
        if key not in consumed and cell.session_type.name in pair_types:
            by_slot[(cell.day, cell.part, cell.session_type.name)].append(cell)
    for (day, part, tname), group in sorted(by_slot.items()):
        if len(group) == 2:
            a, b = sorted(group, key=lambda c: c.clinician.name)
            plan.pairs.append((day, part, a.session_type, a.clinician, b.clinician,
                               _join_notes(a.note, b.note)))
            consumed |= {(a.clinician.id, day, part), (b.clinician.id, day, part)}
        else:
            who = ", ".join(sorted(c.clinician.name for c in group))
            warnings.append(f"{day} {part}: {tname} for {who} — {len(group)} "
                            f"person{'s' if len(group) != 1 else ''} in the slot, so no pair "
                            "is made; link it from the cell form if it should be one")
    plan.singles = [cell for key, cell in cells.items() if key not in consumed]

    # Anything already in a cell that this import did not write is a conflict.
    existing = {
        (e.clinician_id, e.day, e.part): e
        for e in RotaEntry.objects.filter(day__range=(plan.start, plan.end))
        .exclude(fill_reason=IMPORTED).select_related("session_type", "clinician")
    }
    for cell in cells.values():
        e = existing.get((cell.clinician.id, cell.day, cell.part))
        if e is not None:
            plan.conflicts.append((cell, e))
    for b in plan.bookings:
        c = clinicians.get(b.locum)
        e = existing.get((c.id, b.day, b.part)) if c else None
        if e is not None:
            plan.conflicts.append((b, e))
    return plan


def report(plan, out, *, dry_run, publish):
    p = plan
    out.write(f"Old rota import — {p.start:%-d %b} to {p.end:%-d %b %Y}"
              f"{' (dry run)' if dry_run else ''}")
    out.write(f"Sessions: {p.sessions()} — {len(p.singles)} single, "
              f"{len(p.full_days)} full days, {len(p.pairs)} pairs; written as "
              f"{'published' if publish else 'drafts'}")
    by_type, by_person = Counter(), Counter()
    for c in p.singles:
        by_type[c.session_type.name] += 1
        by_person[c.clinician.name] += 1
    for clinician, day, st, note in p.full_days:
        by_type[st.name] += 2
        by_person[clinician.name] += 2
    for day, part, st, a, b, note in p.pairs:
        by_type[st.name] += 2
        by_person[a.name] += 1
        by_person[b.name] += 1
    if by_type:
        out.write("  by type: " + ", ".join(f"{k} {n}" for k, n in by_type.most_common()))
        out.write("  by person: " + ", ".join(f"{k} {n}" for k, n in sorted(by_person.items())))
    if p.skipped_rows:
        out.write("Rows skipped (nothing but Off): " + ", ".join(sorted(p.skipped_rows)))
    if p.ignored_rows:
        out.write("Rows ignored: " + ", ".join(sorted(p.ignored_rows)))
    if p.outside:
        out.write(f"Cells outside the window, ignored: {p.outside}")
    booked = Counter(b.locum for b in p.bookings)
    out.write(f"Locum requirements: {len(p.bookings)} booked"
              + (" (" + ", ".join(f"{k} {n}" for k, n in sorted(booked.items())) + ")" if booked else "")
              + f", {len(p.needs)} possibly needed")
    if p.new_locums:
        out.write("  locums to create in the locum group: " + ", ".join(p.new_locums))
    notes = [c for c in p.singles if c.note] + [f for f in p.full_days if f[3]] \
        + [pr for pr in p.pairs if pr[5]] + [b for b in p.bookings if b.note] + [n for n in p.needs if n.note]
    out.write(f"Notes carried over: {len(notes)}")
    for w in p.warnings:
        out.write(f"Warning: {w}")
    for item, e in p.conflicts:
        who = item.clinician.name if isinstance(item, Cell) else item.locum
        out.write(f"Conflict: {item.day} {item.part} {who} already holds "
                  f"{e.session_type.name}{' (published)' if e.is_published else ' (draft)'}"
                  f"{' set by hand' if e.manually_set else ''} — not from this import")
    for pr in p.problems:
        out.write(f"Problem: {pr}")


@transaction.atomic
def apply(plan, *, publish):
    """Write the plan. Cells in plan.conflicts are left as they are — the
    command only gets here with --skip-conflicts, or with none."""
    conflicted = {(i.clinician.id, i.day, i.part) if isinstance(i, Cell) else (i.locum, i.day, i.part)
                  for i, _ in plan.conflicts}
    locum_group = ClinicianGroup.objects.filter(is_locum_group=True).first()
    locums = {}
    for name in sorted({b.locum for b in plan.bookings}):
        c = Clinician.objects.filter(name=name).first()
        if c is None:
            c = Clinician.objects.create(name=name, initials=_initials(name), group=locum_group)
        locums[name] = c

    n = left = 0
    for cell in plan.singles:
        if (cell.clinician.id, cell.day, cell.part) in conflicted:
            left += 1
            continue
        entries_svc.assign(None, cell.clinician, cell.day, cell.part, cell.session_type,
                           note=cell.note, published=publish, manually_set=True,
                           fill_reason=IMPORTED)
        n += 1
    for clinician, day, st, note in plan.full_days:
        if (clinician.id, day, "AM") in conflicted or (clinician.id, day, "PM") in conflicted:
            left += 2
            continue
        entries_svc.assign_full_day(None, clinician, day, st, note=note, published=publish,
                                    manually_set=True, fill_reason=IMPORTED)
        n += 2
    for day, part, st, a, b, note in plan.pairs:
        if (a.id, day, part) in conflicted or (b.id, day, part) in conflicted:
            left += 2
            continue
        entries_svc.assign_pair(None, day, part, a, b, st, note=note, published=publish,
                                manually_set=True, fill_reason=IMPORTED)
        n += 2

    for need in plan.needs:
        req = LocumRequirement.objects.filter(
            day=need.day, part=need.part, session_type=need.session_type,
            status=LocumRequirement.Status.POSSIBLE, clinician__isnull=True).first()
        locums_svc.save_requirement(None, pk=req.pk if req else None, day=need.day, part=need.part,
                                    session_type=need.session_type,
                                    status=LocumRequirement.Status.POSSIBLE, details=need.note)
    for b in plan.bookings:
        if (b.locum, b.day, b.part) in conflicted:
            left += 1
            continue
        locum = locums[b.locum]
        req = LocumRequirement.objects.filter(day=b.day, part=b.part, clinician=locum).first()
        req = locums_svc.save_requirement(
            None, pk=req.pk if req else None, day=b.day, part=b.part,
            session_type=b.session_type, status=LocumRequirement.Status.BOOKED,
            details=b.note, clinician=locum)
        # The service publishes a booking at once, which is right from the
        # grid and wrong here: the whole window is under review.
        entry = req.rota_entry
        entry.fill_reason = IMPORTED
        entry.is_published = publish
        entry.save(update_fields=["fill_reason", "is_published"])
        n += 1

    RotaEntryLog.objects.create(
        day=plan.start, part="", clinician_name="", actor=None, action=IMPORTED,
        detail=f"{n} sessions from the old rota, {plan.start}..{plan.end}")
    return n, left


class Command(BaseCommand):
    help = ("One-off: import the old sheet's sessions from the CSV that "
            "scripts/old_rota_to_csv.py writes, through a mapping file.")

    def add_arguments(self, parser):
        parser.add_argument("csv")
        parser.add_argument("--map", required=True, help="the mapping .toml")
        parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
        parser.add_argument("--publish", action="store_true",
                            help="write published entries rather than drafts")
        parser.add_argument("--skip-conflicts", action="store_true",
                            help="leave cells that already hold something and import the rest")

    def handle(self, csv, *, map, dry_run, publish, skip_conflicts, **options):
        mapping = load_mapping(map)
        plan = build_plan(read_csv(csv), mapping)
        report(plan, self.stdout, dry_run=dry_run, publish=publish)
        if plan.problems:
            raise CommandError(f"{len(plan.problems)} problem(s) above — nothing written")
        if plan.conflicts and not skip_conflicts:
            raise CommandError(f"{len(plan.conflicts)} conflict(s) above — clear them, or "
                               "--skip-conflicts to leave those cells as they are")
        if dry_run:
            return
        n, left = apply(plan, publish=publish)
        self.stdout.write(f"Written: {n} sessions"
                          + (f", {left} left alone (a full day or pair with one half "
                             "occupied is left whole)" if left else ""))
