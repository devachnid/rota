# Importing the old rota

A one-off, for the weeks the old Google Sheets rota still owned when the
app went live. Two steps with a file between them, so the translation can
be checked before anything touches the database.

## 1. Sheet to CSV

Download the sheet as Excel (File › Download › Microsoft Excel), then:

    pip install openpyxl
    python scripts/old_rota_to_csv.py "Rota 2022-2026.xlsx" "Rota 2026" 2026-09-21 2026-10-23 window.csv

One line per cell: `date, part, row, label, note` — the row is column A's
name, the note is the cell's comment. Blank cells are dropped; *Off* is
kept so the importer can confirm a row it was told to skip holds nothing.
openpyxl is needed only here, not by the app. The CSV names people against
dates: keep it, and the mapping below, out of the repo.

## 2. The mapping

A `.toml` file saying what every row and every label means here. Start
from `scripts/old-rota-mapping.example.toml`, which has every section with
placeholder names:

- `[people]` — sheet row → clinician name in the app.
- `[skip]` — rows that must hold nothing but *Off* in the window (anything
  else stops the import).
- `[ignore]` — rows dropped without looking (the sheet's totals).
- `[locum_rows]` — rows whose cells hold a locum's name or a "needed" word;
  `session_type` is what those sessions are.
- `[locum_people]` — a row that *is* a locum: cells hold session types, as
  for a person, but are booked as locum cover.
- `[locum_names]` — each locum name as typed on the sheet → the name to
  record. New names are created in the locum group.
- `[labels]` — sheet label → session type name; `""` drops the cell.
- `[full_day]` — types whose AM + PM on one day are one full day.
- `[pairs]` — types where two people in the same slot are a linked pair.

## 3. The import

    .venv/bin/python manage.py import_rota window.csv --map mapping.toml --dry-run

The dry run prints the tally by session type and by person, the locum
requirements it would make and the locums it would create, the notes it
carries, and then any **warnings** (a Mentoring with nobody to pair it
with; a comment on an *Off* cell, which writes nothing), **conflicts** (a
cell already holding something this import did not write) and
**problems** (a label, row or locum name the mapping does not cover).

Nothing is written while there is a problem. A conflict stops the run
too, unless `--skip-conflicts` leaves those cells as they are and imports
the rest; a full day or pair with one half occupied is left whole.

Without `--dry-run` it writes, in one transaction:

- every session as a **draft**, manually set, with fill reason *imported*
  — look at each week on the grid, then Publish week (`--publish` writes
  them published instead);
- a full day for each `[full_day]` type held AM and PM, and a linked pair
  for each `[pairs]` type two people hold in one slot, exactly as the cell
  form makes them;
- a **Booked** locum requirement per named locum session, its own session
  a draft like the rest, and a **Possibly needed** one per "needed" cell;
- one audit row for the run and one per session created.

It is safe to run again after correcting the sheet or the mapping: a
session it made before is updated in place, never duplicated, and a cell
anyone else has filled is never touched.
