# Grid and Fill Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The week grid shows an eight-week window with week markers, a Today jump, and an admin-only "ticking mode" that marks sessions as entered into the clinical system; clinicians order by an admin-set integer; a usual non-working half-day reads OFF; the fill screen suggests the first under-half-filled week.

**Architecture:** Django 5 server-rendered templates with htmx for forms, one grid script, no build step. The grid's row assembly moves from the view into `rota/services/grid.py` (a `Window` object) so the page and the new "toggle entered" endpoint render rows through one path. `rota/services/warnings.py` gains a prefetched `WarningBundle` so forty rendered days cost the same queries as five. Everything else is a field, a template branch or a small service.

**Tech Stack:** Python 3.13, Django 5.2, SQLite, htmx (vendored), pytest + pytest-django, ruff (pyflakes only). Run everything with `DEBUG=1` for `manage.py`; the suite needs nothing.

**Spec:** `docs/superpowers/specs/2026-09-15-grid-fill-round-2-design.md` — read it first; the plan argues from it.

## Global Constraints

- No build step, no node, no new dependencies.
- Every colour comes from `static/css/tokens.css`; `components.css` and `screens.css` carry no colour literals (a test greps for them).
- Exactly one width media query, `@media (max-width: 640px)`.
- `cell_state()` in `rota/services/cells.py` is the single answer to "what does this cell show". No screen re-derives it.
- Availability never fails open. Nothing here touches `AvailabilityResolver.available()`.
- No pre-existing test assertion is weakened. Assertions whose subject changes are re-pointed with their rationale rewritten; none is deleted.
- Every mutation runs inside `transaction.atomic()` and writes one audit line through `rota.services.entries._log`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- After each task: `ruff check .` clean, `DEBUG=1 python manage.py makemigrations --check` clean, `pytest -q` green. Run `graphify update .` at the end of each task (AST-only, free).
- Work on branch `feature/grid-fill-round-2` (already exists, holds the specs).

## How to run things

```bash
cd /root/rota
source .venv/bin/activate
pytest -q                                   # whole suite (~1.4k tests, a few minutes)
pytest tests/test_grid_view.py -q           # one file
DEBUG=1 python manage.py makemigrations rota -n <name>
DEBUG=1 python manage.py makemigrations --check
ruff check .
```

Test factories live in `tests/factories.py`: `make_group`, `make_clinician(name, group=None, **fields)`, `make_session_type(name, code=None, **fields)`, `make_pattern(clinician, weekdays=(0..4), parts=("AM","PM"), works=True)`, `make_entry(clinician, day=MON, part="AM", session_type=None, **fields)` (published and manually set by default), `make_absence(clinician, start, end=None, kind="holiday")`. `MON` is `date(2026, 7, 20)`. Fixtures in `tests/conftest.py`: `admin_user`, `admin_client` (rota admin), `gp_user`, `gp_client`. Every grid test starts with `PracticeSettings.load()` so open weekdays exist.

---

## File map

| File | Responsibility after this plan |
|---|---|
| `rota/models/people.py` | `Clinician.display_order` (Task 1) |
| `rota/models/entries.py` | `RotaEntry.entered_at`, `entered_by` (Task 8) |
| `rota/migrations/0029_clinician_display_order.py`, `0030_rotaentry_entered.py` | generated |
| `rota/services/cells.py` | `off_pattern` (Task 2), `entered` / `entered_by` (Task 8), merge rule sees entered state (Task 8) |
| `rota/services/next_week.py` | new: `suggest(today) -> Suggestion` (Task 3) |
| `rota/services/warnings.py` | `WarningBundle` + `bundle=` on `day_warnings` and `week_warnings` (Task 5) |
| `rota/services/grid.py` | new: `parse_anchor`, `Window` — window dates, prefetch, `build_row`, `sections`, `weeks`, `day_headers`, `locum_cells` (Task 6) |
| `rota/services/entries.py` | `set_entered`; `assign` clears the mark on a type/site change (Task 8) |
| `rota/services/swaps.py` | both swap kinds clear the mark (Task 8) |
| `rota/views/grid.py` | thin: parse, build `Window`, render (Task 6); `tick` flag (Task 9) |
| `rota/views/edit.py` | `entered` endpoint (Task 9) |
| `rota/views/fill.py` | default start from `next_week.suggest` (Task 4) |
| `rota/urls.py` | `rota/entered/` (Task 9) |
| `rota/admin.py` | clinician `display_order` inline-editable (Task 1); entry admin shows/filters entered (Task 8) |
| `templates/rota/grid.html` | toolbar, three-row header, includes the row template (Task 6, 9) |
| `templates/rota/_grid_row.html` | new: one clinician row; used by the page and the entered endpoint (Task 6, 9) |
| `templates/rota/fill.html` | suggestion line (Task 4) |
| `static/css/components.css` | `--cols` floor, `.week-start`, `.is-today`, `.is-not-working`, `.is-entered` (Tasks 2, 7, 9) |
| `static/css/screens.css` | `.grid-week`, `.week-publish` (Task 7) |
| `static/js/grid.js` | editing ring (as now) + scroll restore/anchor + Today (Task 7) |
| `docs/admin/people.md`, `docs/admin/day-to-day.md`, `README.md`, `docs/backlog.md` | Tasks 1, 4, 10 |

---

### Task 1: Clinician display order

**Files:**
- Modify: `rota/models/people.py:40-80` (the `Clinician` model)
- Create: `rota/migrations/0029_clinician_display_order.py` (generated)
- Modify: `rota/admin.py:124-153` (`ClinicianAdmin`)
- Modify: `rota/views/grid.py:77-79` (the `Prefetch`), `rota/views/day.py:76-77`
- Modify: `docs/admin/people.md` (Clinicians section, after "Group")
- Test: `tests/test_clinician_order.py` (new)

**Interfaces:**
- Produces: `Clinician.display_order: PositiveIntegerField(default=100)`; `Clinician.Meta.ordering == ["display_order", "name"]`. Task 6 orders its prefetch by `("display_order", "name")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_clinician_order.py
"""Rows within a group follow an admin-set order, then name. Until an
admin sets one, everyone is 100 and the grid is alphabetical as before."""

import pytest

from rota.models import Clinician, PracticeSettings
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db


def test_clinicians_order_by_display_order_then_name():
    beth = make_clinician("Beth Brown", display_order=1)
    alice = make_clinician("Alice Adams")            # default 100
    cara = make_clinician("Cara Cole", display_order=1)
    assert list(Clinician.objects.all()) == [beth, cara, alice]


def test_the_grid_follows_display_order_within_a_group(admin_client):
    PracticeSettings.load()
    make_clinician("Alice Adams", initials="AA")
    make_clinician("Zed Zane", initials="ZZ", display_order=1)
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert html.index('title="Zed Zane"') < html.index('title="Alice Adams"')


def test_the_day_view_follows_display_order(admin_client):
    PracticeSettings.load()
    for name, order in (("Alice Adams", 100), ("Zed Zane", 1)):
        make_pattern(make_clinician(name, display_order=order))
    html = admin_client.get(f"/rota/day/{MON}/").content.decode()
    assert html.index("Zed Zane") < html.index("Alice Adams")


def test_the_admin_list_edits_the_order_inline(admin_client):
    make_clinician("Alice Adams")
    html = admin_client.get("/admin/rota/clinician/").content.decode()
    assert 'name="form-0-display_order"' in html
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_clinician_order.py -q`
Expected: 4 failures — `TypeError: Clinician() got unexpected keyword arguments: 'display_order'`.

- [ ] **Step 3: Add the field and the ordering**

In `rota/models/people.py`, after the `group` field of `Clinician`:

```python
    display_order = models.PositiveIntegerField(
        default=100,
        help_text="Rows within the group appear on the grid in this order, "
                  "lowest first. Ties are alphabetical.",
    )
```

and change `Clinician.Meta`:

```python
    class Meta:
        ordering = ["display_order", "name"]
```

- [ ] **Step 4: Generate the migration**

Run: `DEBUG=1 python manage.py makemigrations rota -n clinician_display_order`
Expected: `rota/migrations/0029_clinician_display_order.py` with one `AddField` and one `AlterModelOptions`.

- [ ] **Step 5: Admin, grid and day view**

`rota/admin.py`, `ClinicianAdmin`:

```python
    list_display = ("name", "initials", "group", "display_order", "active",
                    "is_trainer", "pattern_column", "breathe_link")
    list_editable = ("display_order",)
```

and the "Who" fieldset's fields become `("name", "initials", "group", "display_order", "user")`.

`rota/views/grid.py`, the prefetch:

```python
    groups = ClinicianGroup.objects.prefetch_related(
        Prefetch("clinicians", queryset=Clinician.objects.filter(active=True)
                 .order_by("display_order", "name"))
    )
```

`rota/views/day.py:76-77`:

```python
    active = list(Clinician.objects.filter(active=True)
                 .select_related("group").order_by("display_order", "name"))
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_clinician_order.py tests/test_grid_view.py tests/test_day_view.py tests/test_admin_render.py -q`
Expected: all pass.

- [ ] **Step 7: Document it**

In `docs/admin/people.md`, after the "### Group" entry under Clinicians, add:

```markdown
### Display order

**Default: 100.** Lower sorts first, within the group; ties are
alphabetical by name. The grid and the day view follow it. Dropdowns and
reports stay alphabetical, because a list you scan for a name should be
in name order. Edit it inline on the clinician list — leave gaps (10, 20,
30) so someone new can be slotted in without renumbering.
```

- [ ] **Step 8: Checks and commit**

```bash
ruff check . && DEBUG=1 python manage.py makemigrations --check && pytest -q
graphify update .
git add rota/models/people.py rota/migrations/0029_clinician_display_order.py rota/admin.py rota/views/grid.py rota/views/day.py docs/admin/people.md tests/test_clinician_order.py graphify-out
git commit -m "feat: clinicians order by an admin-set display order within their group

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: OFF on a usual non-working half-day

**Files:**
- Modify: `rota/services/cells.py:35-85` (`cell_state`)
- Modify: `templates/rota/grid.html:65-66` (the `off` branch)
- Modify: `static/css/components.css:387-397` (the empty-state comment and rules)
- Modify: `tests/test_cells.py`, `tests/test_grid_rendering.py` (docstring at top, `test_a_non_working_session_is_blank`), `tests/test_chrome_contrast.py:PAIRS`
- Test: as above

**Interfaces:**
- Produces: `cell_state(...)["off_pattern"]: bool`. Task 6's row template keeps the same three-way branch.

- [ ] **Step 1: Write the failing service tests**

Append to `tests/test_cells.py` (it already has `_works`, `_resolver`, `TUE`, `make_clinician`):

```python
def test_a_slot_the_pattern_says_is_not_worked_is_off_pattern():
    c = make_clinician()
    _works(c, weekday=0)  # Mondays only
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off_pattern"] is True


def test_off_pattern_is_false_on_a_closed_day():
    c = make_clinician()
    _works(c, weekday=0)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=True)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_outside_the_contractual_window():
    c = make_clinician(end_date=TUE - timedelta(days=1))
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_with_no_pattern_rows_at_all():
    c = make_clinician()
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_under_an_entry():
    c = make_clinician()
    _works(c, weekday=0)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["off_pattern"] is False
```

Check the top of `tests/test_cells.py` imports `timedelta` and `make_entry`; add them if not.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_cells.py -q`
Expected: 5 failures with `KeyError: 'off_pattern'`.

- [ ] **Step 3: Add `off_pattern` to `cell_state`**

In `rota/services/cells.py`, after the `showable = ...` line:

```python
    # A usual non-working half-day, as distinct from blank for any other
    # reason. The grid prints OFF on the former and nothing on the latter:
    # a closed day stays blank so a bank holiday never reads as everyone
    # being off; a clinician outside their dates has no pattern in force;
    # and a clinician with no pattern rows at all must not read OFF on
    # every session when the truth is nobody has entered their pattern
    # (the dashboard counts those).
    off_pattern = (entry is None and not works and not closed
                   and resolver.has_pattern(clinician_id)
                   and resolver.in_service(clinician_id, day))
```

and add `"off_pattern": off_pattern,` to the returned dict after `"off"`.

- [ ] **Step 4: Run the service tests**

Run: `pytest tests/test_cells.py -q`
Expected: pass.

- [ ] **Step 5: Write the failing rendering test**

In `tests/test_grid_rendering.py`, replace `test_a_non_working_session_is_blank` with:

```python
@pytest.mark.django_db
def test_a_non_working_session_reads_off(admin_client):
    """A part-timer's day off used to be blank, the same as a closed day or
    a session outside someone's dates, and users read blank as "not filled
    yet". It now says OFF; the other blanks stay blank."""
    c = make_clinician("Blank", initials="BL")
    _pattern(c, 0, "AM", works=False)
    html = _cells(admin_client)
    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "is-off is-not-working"
    assert set(chips.values()) == {"is-off is-not-working"}, (
        "this clinician works nothing, so nothing should be grey"
    )
    assert 'title="Not a working session">OFF<' in html
    assert "unavail" not in html, "the old class is gone"


@pytest.mark.django_db
def test_a_closed_day_stays_blank_for_a_non_working_session(admin_client):
    c = make_clinician("Closed", initials="CD")
    _pattern(c, 0, "AM", works=False)
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] == "is-off"
```

Rewrite the module docstring's precedence table so the last two lines read:

```
    works_on                    -> grey: working, nothing allocated
    usual non-working half-day  -> OFF, muted on the sunken ground
    otherwise                   -> blank: closed, or not employed that day
```

and drop the sentence about "the reverse of what shipped" (it is history, and the chip block's comment carries it).

- [ ] **Step 6: Run it to see it fail**

Run: `pytest tests/test_grid_rendering.py -q`
Expected: the two new tests fail; the rest pass.

- [ ] **Step 7: Template and CSS**

`templates/rota/grid.html`, replace the `{% elif cell.off %}` branch:

```django
    {% elif cell.off_pattern %}
      <span class="chip is-off is-not-working" title="Not a working session">OFF</span>
    {% elif cell.off %}
      <span class="chip is-off">&nbsp;</span>
```

`static/css/components.css`, replace the comment and two rules at the "two empty states" block:

```css
/* Three empty states. Blank means closed, or not employed that day; OFF
   means a usual non-working half-day (cells.py's off_pattern); grey means
   "working, nothing allocated" — the state that wants attention, so it is
   the one that carries weight. Grey has its own token, not --sunken:
   --sunken is a panel ground and sits at 1.06:1 on the white cell in light
   mode, which is to say invisible (tokens.css). OFF sits on --sunken on
   purpose — it is not asking for anything — with the chip's fallback
   --muted foreground (muted on sunken is a checked pairing in
   tests/test_chrome_contrast.py). */
.chip.is-off {
  background: transparent;
}
.chip.is-off.is-not-working {
  background: var(--sunken);
}
.chip.empty-slot {
  background: var(--slot);
}
```

In `tests/test_chrome_contrast.py`, change the `("muted", "sunken", ...)` entry's description to `".badge default, .closed body cells, .chip fallback fg, the OFF chip"`.

- [ ] **Step 8: Run the tests**

Run: `pytest tests/test_grid_rendering.py tests/test_cells.py tests/test_chrome_contrast.py tests/test_css_cascade.py -q`
Expected: pass.

- [ ] **Step 9: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/services/cells.py templates/rota/grid.html static/css/components.css tests/test_cells.py tests/test_grid_rendering.py tests/test_chrome_contrast.py graphify-out
git commit -m "feat: a usual non-working half-day reads OFF on the grid

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The next-week-to-fill service

**Files:**
- Create: `rota/services/next_week.py`
- Test: `tests/test_next_week.py` (new)

**Interfaces:**
- Produces: `next_week.suggest(today: date | None = None) -> Suggestion` with fields `monday: date`, `working: int`, `filled: int`, `found: bool`, `horizon_end: date`; `next_week.next_monday(today) -> date`. Task 4 reads all of them.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_next_week.py
"""Which week the assisted fill should offer to start on: from next Monday,
the first week under half filled — working sessions against entries. A few
advance bookings leave a week under half, so it is still wanted; a week
with no working sessions at all is skipped."""

from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PracticeSettings
from rota.services.next_week import next_monday, suggest
from tests.factories import make_absence, make_clinician, make_entry, make_pattern

pytestmark = pytest.mark.django_db

TODAY = date(2026, 9, 16)          # a Wednesday
NEXT = date(2026, 9, 21)           # the Monday after
WEEK_AFTER = NEXT + timedelta(days=7)


def _gp(name="Alice Adams", parts=("AM", "PM")):
    c = make_clinician(name)
    make_pattern(c, parts=parts)
    return c


def _fill_week(c, monday, parts=("AM", "PM"), days=range(5)):
    for d in days:
        for part in parts:
            make_entry(c, day=monday + timedelta(days=d), part=part)


def test_next_monday_is_strictly_after_today():
    assert next_monday(TODAY) == NEXT
    assert next_monday(NEXT) == WEEK_AFTER


def test_an_empty_rota_suggests_next_monday():
    PracticeSettings.load()
    _gp()
    s = suggest(TODAY)
    assert s.found and s.monday == NEXT
    assert (s.working, s.filled) == (10, 0)


def test_a_few_advance_sessions_still_leave_the_week_wanted():
    PracticeSettings.load()
    c = _gp()
    _fill_week(c, NEXT, parts=("AM",), days=range(2))
    s = suggest(TODAY)
    assert s.monday == NEXT and s.filled == 2


def test_exactly_half_filled_is_not_wanted():
    PracticeSettings.load()
    c = _gp()
    _fill_week(c, NEXT, parts=("AM",))       # 5 of 10
    assert suggest(TODAY).monday == WEEK_AFTER


def test_a_full_week_is_skipped():
    PracticeSettings.load()
    _fill_week(_gp(), NEXT)
    s = suggest(TODAY)
    assert s.monday == WEEK_AFTER and s.filled == 0


def test_a_week_with_every_day_closed_is_skipped():
    PracticeSettings.load()
    _gp()
    for d in range(5):
        ClosedDay.objects.create(day=NEXT + timedelta(days=d), reason="Closed")
    assert suggest(TODAY).monday == WEEK_AFTER


def test_leave_reduces_the_working_count():
    PracticeSettings.load()
    c = _gp()
    make_absence(c, NEXT, NEXT + timedelta(days=4))
    s = suggest(TODAY)
    assert s.monday == WEEK_AFTER and s.working == 10


def test_drafts_count_as_filled():
    PracticeSettings.load()
    c = _gp()
    for d in range(5):
        for part in ("AM", "PM"):
            make_entry(c, day=NEXT + timedelta(days=d), part=part,
                       is_published=False)
    assert suggest(TODAY).monday == WEEK_AFTER


def test_falls_back_to_next_monday_when_no_week_is_under_half():
    PracticeSettings.load()
    c = _gp(parts=("AM",))                   # 5 working sessions a week
    for w in range(26):
        _fill_week(c, NEXT + timedelta(days=7 * w), parts=("AM",), days=range(3))
    s = suggest(TODAY)
    assert not s.found and s.monday == NEXT
    assert s.horizon_end == NEXT + timedelta(days=26 * 7 - 1)


def test_the_scan_is_a_fixed_number_of_queries(django_assert_max_num_queries):
    PracticeSettings.load()
    for name in ("Alice Adams", "Beth Brown", "Cara Cole"):
        _gp(name)
    with django_assert_max_num_queries(8):
        suggest(TODAY)
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_next_week.py -q`
Expected: `ModuleNotFoundError: No module named 'rota.services.next_week'`.

- [ ] **Step 3: Write the service**

```python
# rota/services/next_week.py
"""The week the assisted fill should offer to start on.

The rota is built four to six weeks ahead, so "next Monday" is nearly
always a week already done. From next Monday, this finds the first week
that is under half filled: the number of working sessions — a clinician
who is active, inside their dates, works that half-day by pattern and is
not on Breathe leave — against how many of those hold any entry, draft or
published. A few advance bookings or a booked locum leave a week well
under half, so it is still picked; a week with no working sessions at all
(every day closed) is skipped. Bounded at HORIZON_WEEKS, falling back to
next Monday.

Deliberately not the fill engine's FillContext: that is built for a run
over a range, and this is a scan.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClosedDay, PatternSlot, PracticeSettings, RotaEntry)
from rota.services import availability

HORIZON_WEEKS = 26


@dataclass(frozen=True)
class Suggestion:
    monday: date
    working: int
    filled: int
    found: bool
    horizon_end: date


def next_monday(today):
    """The Monday strictly after `today` (a Monday jumps a full week)."""
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def suggest(today=None):
    today = today or date.today()
    first = next_monday(today)
    last = first + timedelta(days=HORIZON_WEEKS * 7 - 1)
    open_weekdays = set(PracticeSettings.load().open_weekday_list())
    closed = set(ClosedDay.objects.filter(day__range=(first, last))
                 .values_list("day", flat=True))
    active = list(Clinician.objects.filter(active=True))
    pattern_rows = list(PatternSlot.objects.filter(clinician__in=active)
                        .order_by("effective_from"))
    absences = list(BreatheAbsence.objects.filter(
        clinician__in=active, start_date__lte=last, end_date__gte=first))
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, absences, BreatheLeaveMapping.as_dict())
    held = set(RotaEntry.objects.filter(day__range=(first, last))
               .values_list("clinician_id", "day", "part"))

    for i in range(HORIZON_WEEKS):
        monday = first + timedelta(days=7 * i)
        working = filled = 0
        for offset in range(7):
            day = monday + timedelta(days=offset)
            if day.weekday() not in open_weekdays or day in closed:
                continue
            for c in active:
                for part in ("AM", "PM"):
                    if resolver.available(c.id, day, part):
                        working += 1
                        if (c.id, day, part) in held:
                            filled += 1
        if working and filled * 2 < working:
            return Suggestion(monday, working, filled, True, last)
    return Suggestion(first, 0, 0, False, last)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_next_week.py -q`
Expected: pass. If the query-count test fails, count what `BreatheLeaveMapping.as_dict()` and `PracticeSettings.load()` cost and raise the cap to the real fixed number; the point is that it does not scale with clinicians or weeks, so also add three more clinicians in that test and assert the same cap holds.

- [ ] **Step 5: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/services/next_week.py tests/test_next_week.py graphify-out
git commit -m "feat: a service that finds the first week under half filled

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The fill screen defaults to the suggested week

**Files:**
- Modify: `rota/views/fill.py:52-60` (`_base_context`)
- Modify: `templates/rota/fill.html:9-18` (after the To field)
- Modify: `docs/admin/day-to-day.md` ("## Assisted fill", first paragraph)
- Test: `tests/test_fill_form.py`

**Interfaces:**
- Consumes: `next_week.suggest`, `next_week.next_monday` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fill_form.py`:

```python
from datetime import date

from rota.services.next_week import next_monday
from tests.factories import make_clinician, make_pattern


@pytest.mark.django_db
def test_the_start_date_is_the_first_week_under_half_filled(admin_client):
    PracticeSettings.load()
    make_pattern(make_clinician("Alice Adams"))
    html = admin_client.get("/rota/fill/").content.decode()
    expected = next_monday(date.today())
    assert f'name="start" id="id_fill_start" value="{expected}"' in html
    assert "Suggested from" in html
    assert "the first week under half filled (0 of 10 sessions)" in html


@pytest.mark.django_db
def test_with_nothing_to_suggest_the_form_says_so(admin_client):
    """No clinician works anything, so no week has a working session and
    none can be under half: the default is next Monday and the line
    explains."""
    PracticeSettings.load()
    html = admin_client.get("/rota/fill/").content.decode()
    assert "No week to" in html and "defaulting to next Monday" in html
    assert f'value="{next_monday(date.today())}"' in html
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_fill_form.py -q`
Expected: the two new tests fail on the missing text.

- [ ] **Step 3: View and template**

`rota/views/fill.py`: add `from rota.services import next_week` to the imports and replace `_base_context`:

```python
def _base_context():
    suggestion = next_week.suggest(date.today())
    return {
        "start": suggestion.monday,
        "end": suggestion.monday + timedelta(days=27),
        "suggestion": suggestion,
        "result": None,
        "default_type": PracticeSettings.load().default_fill_session_type,
    }
```

`templates/rota/fill.html`: after the closing `</div>` of the "To" field, add:

```django
      <p class="field-help">
        {% if suggestion.found %}Suggested from {{ suggestion.monday|date:"D j M" }} — the first week under half filled ({{ suggestion.filled }} of {{ suggestion.working }} sessions). Change the dates if you want a different run.
        {% else %}No week to {{ suggestion.horizon_end|date:"j M" }} is under half filled; defaulting to next Monday.{% endif %}
      </p>
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_fill_form.py tests/test_fill_view.py tests/test_delete_drafts_view.py -q`
Expected: pass.

- [ ] **Step 5: Document it**

In `docs/admin/day-to-day.md`, replace the line under "## Assisted fill" that reads `` `/rota/fill/` — pick a date range, run it. `` with:

```markdown
`/rota/fill/` — pick a date range, run it. The **From** date opens on the
first week, from next Monday, that is under half filled — working sessions
(by pattern, minus Breathe leave) against entries, drafts included — and
the line under the dates says which week and why. A few advance bookings
leave a week under half, so it is still offered. When no week in the next
26 is under half, the form says so and opens on next Monday. **To** is
four weeks on; both are editable.
```

- [ ] **Step 6: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/views/fill.py templates/rota/fill.html docs/admin/day-to-day.md tests/test_fill_form.py graphify-out
git commit -m "feat: the fill screen opens on the first week under half filled

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: A prefetched bundle for day and week warnings

**Files:**
- Modify: `rota/services/warnings.py` (whole file: `_locum_suffix`, `day_warnings`, `week_warnings`; add `WarningBundle`)
- Test: `tests/test_warnings.py`

**Interfaces:**
- Produces: `WarningBundle.load(days, include_drafts=True) -> WarningBundle`; `day_warnings(day, include_drafts=True, resolver=None, bundle=None)`; `week_warnings(days, include_drafts=True, bundle=None)`. With a bundle, neither function queries. Without one, both behave exactly as today. Task 6 builds one bundle per page.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_warnings.py`:

```python
def test_a_bundle_gives_the_same_day_warnings_with_no_queries(
        duty_rule, django_assert_num_queries):
    """The grid renders forty days at once; without the bundle each day
    is its own set of queries."""
    from rota.services.availability import AvailabilityResolver
    from rota.services.warnings import WarningBundle
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 1})
    c = make_clinician()
    c.group.min_per_session = 2
    c.group.save()
    make_entry(c, part="AM", session_type=duty_rule)
    LocumRequirement.objects.create(
        day=MON, part="PM", session_type=duty_rule,
        status=LocumRequirement.Status.ADVERTISED)
    days = [MON + timedelta(days=i) for i in range(5)]
    resolver = AvailabilityResolver([], [c], [], {})
    plain = [day_warnings(d, resolver=resolver) for d in days]
    bundle = WarningBundle.load(days)
    with django_assert_num_queries(0):
        bundled = [day_warnings(d, resolver=resolver, bundle=bundle) for d in days]
    assert bundled == plain
    assert any("locum advertised" in w.message for w in bundled[0])


def test_a_bundle_gives_the_same_week_warnings_with_no_queries(django_assert_num_queries):
    from rota.services.warnings import WarningBundle
    larc = make_session_type("LARC", max_per_week=1)
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=larc)
    make_entry(c, day=MON + timedelta(days=1), part="AM", session_type=larc)
    days = [MON + timedelta(days=i) for i in range(5)]
    plain = week_warnings(days)
    bundle = WarningBundle.load(days)
    with django_assert_num_queries(0):
        bundled = week_warnings(days, bundle=bundle)
    assert bundled == plain and len(bundled) == 1


def test_a_bundle_respects_include_drafts():
    from rota.services.warnings import WarningBundle
    larc = make_session_type("LARC", max_per_week=1)
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=larc)
    make_entry(c, day=MON + timedelta(days=1), part="AM", session_type=larc,
               is_published=False)
    days = [MON + timedelta(days=i) for i in range(5)]
    assert week_warnings(days, include_drafts=False,
                         bundle=WarningBundle.load(days, include_drafts=False)) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_warnings.py -q`
Expected: 3 failures, `ImportError: cannot import name 'WarningBundle'`.

- [ ] **Step 3: Add the bundle and thread it through**

In `rota/services/warnings.py`, after the `Warning` dataclass:

```python
@dataclass
class WarningBundle:
    """Everything day_warnings() and week_warnings() read that does not
    depend on the one day: fetched once by a caller rendering many days
    (the grid's eight-week window) and sliced per day. Without one the
    functions fetch for themselves, so the dashboard, the staffing report
    and the day view are unchanged."""
    entries_by_day: dict
    rules: list
    ceiling_types: list
    week_types: list
    groups: list
    settings: PracticeSettings
    open_weekdays: set
    closed: set
    locum_reqs: dict

    @classmethod
    def load(cls, days, include_drafts=True):
        entries = RotaEntry.objects.filter(day__in=days).select_related(
            "session_type", "clinician", "clinician__group")
        if not include_drafts:
            entries = entries.filter(is_published=True)
        by_day = {}
        for e in entries:
            by_day.setdefault(e.day, []).append(e)
        # First by pk, matching the .first() the unbundled path uses.
        reqs = {}
        for r in LocumRequirement.objects.filter(day__in=days).order_by("pk"):
            reqs.setdefault((r.day, r.part, r.session_type_id), r)
        settings = PracticeSettings.load()
        return cls(
            entries_by_day=by_day,
            rules=list(CoverageRule.objects.filter(
                frequency=CoverageRule.Frequency.PER_SLOT).select_related("session_type")),
            ceiling_types=list(SessionType.objects.filter(
                Q(max_per_session__isnull=False) | Q(max_per_day__isnull=False))),
            week_types=list(SessionType.objects.filter(max_per_week__isnull=False)),
            groups=list(ClinicianGroup.objects.filter(min_per_session__isnull=False)),
            settings=settings,
            open_weekdays=set(settings.open_weekday_list()),
            closed=set(ClosedDay.objects.filter(day__in=days).values_list("day", flat=True)),
            locum_reqs=reqs,
        )

    def is_open(self, day):
        return day.weekday() in self.open_weekdays and day not in self.closed
```

Add `ClosedDay` to the model import. Change `_locum_suffix`:

```python
def _locum_suffix(day, part, session_type, bundle=None):
    if bundle is not None:
        req = bundle.locum_reqs.get((day, part, session_type.id))
    else:
        req = LocumRequirement.objects.filter(
            day=day, part=part, session_type=session_type).first()
    return f" — locum {req.get_status_display().lower()}" if req else ""
```

Change the head of `day_warnings` to:

```python
def day_warnings(day, include_drafts=True, resolver=None, bundle=None):
    if bundle is not None:
        if not bundle.is_open(day):
            return []
        entries = bundle.entries_by_day.get(day, [])
        rules, ceiling_types, groups = bundle.rules, bundle.ceiling_types, bundle.groups
        settings = bundle.settings
    else:
        if not calendar.is_open(day):
            return []
        entries = RotaEntry.objects.filter(day=day).select_related(
            "session_type", "clinician", "clinician__group"
        )
        if not include_drafts:
            entries = entries.filter(is_published=True)
        entries = list(entries)
        rules = CoverageRule.objects.filter(
            frequency=CoverageRule.Frequency.PER_SLOT).select_related("session_type")
        ceiling_types = SessionType.objects.filter(
            Q(max_per_session__isnull=False) | Q(max_per_day__isnull=False))
        groups = ClinicianGroup.objects.filter(min_per_session__isnull=False)
        settings = PracticeSettings.load()
    warnings = []
```

then the three loops iterate `rules`, `ceiling_types` and `groups` instead of their inline querysets, and the coverage loop's suffix call becomes `_locum_suffix(day, part, rule.session_type, bundle)`. The `_breathe_conflicts(day, entries, resolver)` call at the end is unchanged.

Change `week_warnings`:

```python
def week_warnings(days, include_drafts=True, bundle=None):
    """The one ceiling that only makes sense across a week: a session
    type's max_per_week, over the open days given. Rendered in the week's
    header cell on the grid."""
    if bundle is not None:
        days = [d for d in days if bundle.is_open(d)]
        types = bundle.week_types
        if not days or not types:
            return []
        have = Counter(e.session_type_id for d in days
                       for e in bundle.entries_by_day.get(d, []))
    else:
        days = [d for d in days if calendar.is_open(d)]
        types = list(SessionType.objects.filter(max_per_week__isnull=False))
        if not days or not types:
            return []
        entries = RotaEntry.objects.filter(day__in=days, session_type__in=types)
        if not include_drafts:
            entries = entries.filter(is_published=True)
        have = Counter(entries.values_list("session_type_id", flat=True))
    return [
        Warning("ceiling", None,
                f"Too many {st.name} this week: {have[st.id]} sessions, max {st.max_per_week}")
        for st in types if have[st.id] > st.max_per_week
    ]
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_warnings.py tests/test_grid_view.py tests/test_admin_dashboard.py -q`
Expected: pass. If the `django_assert_num_queries(0)` block fails, the traceback names the query: every remaining read in `day_warnings` must come from the bundle.

- [ ] **Step 5: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/services/warnings.py tests/test_warnings.py graphify-out
git commit -m "feat: day and week warnings can read from one prefetched bundle

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: The eight-week window — service, view, templates

This task changes the page's structure and leaves its look for Task 7. After it the grid renders eight weeks in one table with a week header row; the table is still `min-width: 42rem`, so it will look cramped until Task 7 lands. Both tasks go in before the branch is reviewed for looks.

**Files:**
- Create: `rota/services/grid.py`
- Rewrite: `rota/views/grid.py`
- Rewrite: `templates/rota/grid.html`
- Create: `templates/rota/_grid_row.html`
- Modify: `tests/test_grid_view.py` (re-point `test_week_param_snaps_to_monday`), `tests/test_grid_rendering.py` (nothing should break; run it)
- Test: `tests/test_grid_window.py` (new)

**Interfaces:**
- Consumes: `WarningBundle`, `day_warnings(..., bundle=)`, `week_warnings(..., bundle=)` (Task 5); `cell_state`, `one_block`, `day_note`, `shows_on_roster` (`rota/services/cells.py`).
- Produces (all in `rota/services/grid.py`):
  - `WEEKS_BEFORE = 1`, `WEEKS_AFTER = 6`, `STEP_WEEKS = 4`
  - `week_monday(day) -> date`
  - `parse_anchor(raw: str | None, today: date | None = None) -> date` (a Monday)
  - `class Window(anchor, is_admin, user, today=None)` with attributes `anchor, today, is_admin, user, mondays, days, start, end, entries, cell_map, companion_partner, active, resolver, closed, notes, week_starts` and methods `weeks() -> list[dict]`, `day_headers() -> list[dict]`, `sections() -> list[dict]`, `build_row(clinician, is_locum) -> dict | None`, `locum_cells() -> list[dict]`.
  - Template context keys the row template reads: `row` (`clinician`, `mine`, `cells`), `is_admin`, `colspan`. Each cell dict is `cell_state(...)` plus `merged`, `week_start`, `today`.
- Task 9 adds `tick` to the row template's context and calls `Window(...).build_row(...)` from the entered endpoint.

- [ ] **Step 1: Write the failing view tests**

```python
# tests/test_grid_window.py
"""The grid shows a run of weeks — one before the anchor week, six after —
in one table, with a header cell per week, a heavier rule at each week
boundary, today marked, and each week's Publish in its own header."""

from datetime import date, timedelta

import pytest

from rota.models import PracticeSettings
from rota.services import grid as grid_svc
from tests.factories import MON, make_clinician, make_entry, make_pattern, make_session_type

pytestmark = pytest.mark.django_db


def _page(client, anchor=MON):
    PracticeSettings.load()
    return client.get(f"/rota/?week={anchor}").content.decode()


def test_parse_anchor_snaps_to_monday_and_falls_back_to_today():
    assert grid_svc.parse_anchor("2026-07-22", today=date(2026, 1, 1)) == MON
    assert grid_svc.parse_anchor("", today=date(2026, 7, 23)) == MON
    assert grid_svc.parse_anchor("nonsense", today=date(2026, 7, 23)) == MON
    assert grid_svc.parse_anchor(None, today=date(2026, 7, 23)) == MON


def test_the_window_spans_one_week_back_and_six_forward(admin_client):
    html = _page(admin_client)
    first = MON - timedelta(days=7)
    last = MON + timedelta(days=6 * 7 + 4)
    assert f'data-monday="{first}"' in html
    assert f'data-monday="{MON + timedelta(days=42)}"' in html
    assert f'data-monday="{MON + timedelta(days=49)}"' not in html
    assert f'data-monday="{first - timedelta(days=7)}"' not in html
    assert f"Weeks of {first:%-d %b} – {last:%-d %b %Y}" in html
    assert html.count('class="grid-week') == 8


def test_earlier_and_later_step_four_weeks(admin_client):
    html = _page(admin_client)
    assert f'href="?week={MON - timedelta(days=28)}"' in html
    assert f'href="?week={MON + timedelta(days=28)}"' in html


def test_each_week_header_spans_its_open_days(admin_client):
    html = _page(admin_client)
    assert html.count('<th colspan="10" scope="colgroup" class="grid-week') == 8


def test_the_anchor_week_is_marked(admin_client):
    html = _page(admin_client)
    assert html.count("is-anchor") == 1
    start = html.index("is-anchor")
    assert f'data-monday="{MON}"' in html[start - 60:start + 120]


def test_week_start_lands_on_mondays_only(admin_client):
    c = make_clinician()
    make_pattern(c)
    html = _page(admin_client)
    for offset, expected in ((0, True), (1, False), (7, True), (-7, True)):
        d = MON + timedelta(days=offset)
        i = html.index(f'hx-get="/rota/cell/{c.id}/{d}/AM/"')
        td = html[html.rindex("<td", 0, i):i]
        assert ("week-start" in td) is expected, (d, td)


def test_today_is_marked_when_inside_the_window(admin_client, monkeypatch):
    monkeypatch.setattr(grid_svc, "_today", lambda: MON + timedelta(days=2))
    c = make_clinician()
    make_pattern(c)
    html = _page(admin_client)
    wed = MON + timedelta(days=2)
    assert "grid-day is-today" in html
    i = html.index(f'hx-get="/rota/cell/{c.id}/{wed}/AM/"')
    assert "is-today" in html[html.rindex("<td", 0, i):i]
    j = html.index(f'hx-get="/rota/cell/{c.id}/{MON}/AM/"')
    assert "is-today" not in html[html.rindex("<td", 0, j):j]
    assert 'id="grid-today"' in html and 'data-scroll="1"' in html


def test_today_outside_the_window_is_a_plain_link(admin_client, monkeypatch):
    far = MON + timedelta(days=365)
    monkeypatch.setattr(grid_svc, "_today", lambda: far)
    html = _page(admin_client)
    assert "is-today" not in html
    assert f'href="?week={far}" class="btn" id="grid-today"' in html
    assert 'data-scroll="1"' not in html


def test_publish_sits_in_the_week_header_only_when_there_are_drafts(admin_client):
    c = make_clinician()
    duty = make_session_type("Duty", code="DUTY")
    make_entry(c, day=MON + timedelta(days=7), part="AM", is_published=False,
               session_type=duty)
    html = _page(admin_client)
    assert html.count('hx-post="/rota/publish/"') == 1
    form_at = html.index('hx-post="/rota/publish/"')
    form = html[form_at:form_at + 400]
    assert f'name="start" value="{MON + timedelta(days=7)}"' in form
    assert f'name="end" value="{MON + timedelta(days=11)}"' in form
    assert "1 draft" in form
    assert "Publish week" not in html.split('<div class="grid-wrap">')[0]


def test_a_gp_sees_no_publish_and_no_drafts(gp_client):
    c = make_clinician()
    make_entry(c, day=MON, part="AM", is_published=False,
               session_type=make_session_type("Duty", code="DUTY"))
    html = _page(gp_client)
    assert "/rota/publish/" not in html and "DUTY" not in html


def test_the_week_ceiling_warning_sits_in_its_week_header(admin_client):
    larc = make_session_type("LARC", code="LARC", max_per_week=1)
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=larc)
    make_entry(c, day=MON + timedelta(days=1), part="AM", session_type=larc)
    html = _page(admin_client)
    week_cell = html.index(f'data-monday="{MON}"')
    next_cell = html.index(f'data-monday="{MON + timedelta(days=7)}"')
    assert "Too many LARC this week" in html[week_cell:next_cell]


def test_the_table_declares_its_column_count_and_start(admin_client):
    html = _page(admin_client)
    assert 'style="--cols: 80"' in html
    assert f'data-start="{MON - timedelta(days=7)}"' in html


def test_query_count_does_not_grow_with_weeks_of_entries(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY")
    make_entry(c, day=MON, part="AM", session_type=duty)
    with CaptureQueriesContext(connection) as one_week:
        admin_client.get(f"/rota/?week={MON}")
    for w in range(-1, 7):
        for d in range(5):
            if (w, d) != (0, 0):
                make_entry(c, day=MON + timedelta(days=7 * w + d), part="AM",
                           session_type=duty)
    with CaptureQueriesContext(connection) as eight_weeks:
        admin_client.get(f"/rota/?week={MON}")
    assert len(eight_weeks) == len(one_week), (
        f"{len(one_week)} queries with one week of entries, "
        f"{len(eight_weeks)} with eight")
    assert len(one_week) <= 30, len(one_week)
```

In `tests/test_grid_view.py`, rename `test_week_param_snaps_to_monday` to `test_week_param_anchors_the_window_on_its_monday` and change its body to:

```python
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    wednesday = MON + timedelta(days=2)
    html = admin_client.get(f"/rota/?week={wednesday}").content.decode()
    assert "ROUT" in html
    assert f'data-monday="{MON}"' in html and "is-anchor" in html
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_grid_window.py -q`
Expected: `ImportError` on `rota.services.grid`.

- [ ] **Step 3: Write the grid service**

```python
# rota/services/grid.py
"""What the week grid shows: a window of weeks, and one row per clinician.

The page renders WEEKS_BEFORE weeks before the anchor Monday and
WEEKS_AFTER after it, in one table; Earlier and Later move the anchor by
STEP_WEEKS so successive windows overlap. The row builder is here rather
than in the view because the "entered in the clinical system" endpoint
re-renders one row through the same path, and the two must not drift.
"""

from datetime import date, timedelta

from django.db.models import Prefetch

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClinicianGroup, ClosedDay, DayNote, LocumRequirement,
                         PatternSlot, PracticeSettings, RotaEntry)
from rota.services import availability
from rota.services.cells import cell_state, day_note, one_block, shows_on_roster
from rota.services.warnings import WarningBundle, day_warnings, week_warnings

WEEKS_BEFORE = 1
WEEKS_AFTER = 6
STEP_WEEKS = 4


def _today():
    return date.today()


def week_monday(day):
    return day - timedelta(days=day.weekday())


def parse_anchor(raw, today=None):
    """The Monday of the week `?week=` names; today's week when it is
    absent or malformed."""
    try:
        anchor = date.fromisoformat(raw or "")
    except ValueError:
        anchor = today or _today()
    return week_monday(anchor)


class Window:
    def __init__(self, anchor, is_admin, user, today=None):
        self.anchor = anchor
        self.is_admin = is_admin
        self.user = user
        self.today = today or _today()
        settings = PracticeSettings.load()
        # sorted(): open_weekday_list() preserves input order, and the
        # per-week slices below take the first day of each week by value.
        offsets = sorted(settings.open_weekday_list())
        self.mondays = [anchor + timedelta(days=7 * i)
                        for i in range(-WEEKS_BEFORE, WEEKS_AFTER + 1)]
        self.days = sorted(m + timedelta(days=o) for m in self.mondays for o in offsets)
        # min()/max(), not [0]/[-1]: `days` can be empty (open_weekdays ""
        # parses to [] and PracticeSettings.clean() accepts it).
        self.start = min(self.days) if self.days else anchor
        self.end = max(self.days) if self.days else anchor
        self.week_starts = set()
        for m in self.mondays:
            in_week = [d for d in self.days if week_monday(d) == m]
            if in_week:
                self.week_starts.add(min(in_week))
        self._bundle = None
        self._load()

    def _load(self):
        days = self.days
        entries = RotaEntry.objects.filter(day__in=days).select_related(
            "session_type", "clinician", "site")
        if not self.is_admin:
            entries = entries.filter(is_published=True)
        self.entries = list(entries)
        self.cell_map = {(e.clinician_id, e.day, e.part): e for e in self.entries}

        self.companion_partner = {}
        by_group = {}
        for e in self.entries:
            if e.companion_group:
                by_group.setdefault(e.companion_group, []).append(e)
        for pair in by_group.values():
            if len(pair) != 2:
                continue
            e1, e2 = pair
            self.companion_partner[(e1.clinician_id, e1.day, e1.part)] = e2.clinician.name
            self.companion_partner[(e2.clinician_id, e2.day, e2.part)] = e1.clinician.name

        self.active = list(Clinician.objects.filter(active=True))
        pattern_rows = list(PatternSlot.objects.filter(
            clinician__in=self.active).order_by("effective_from"))
        absences = BreatheAbsence.objects.none()
        if days:
            absences = BreatheAbsence.objects.filter(
                clinician__in=self.active,
                start_date__lte=self.end, end_date__gte=self.start)
        self.resolver = availability.AvailabilityResolver(
            pattern_rows, self.active, absences, BreatheLeaveMapping.as_dict())
        self.closed = set(ClosedDay.objects.filter(day__in=days)
                          .values_list("day", flat=True))
        self.notes = {n.day: n for n in DayNote.objects.filter(day__in=days)}

    # ---- header --------------------------------------------------------

    def bundle(self):
        """One WarningBundle per page, shared by weeks() and day_headers();
        None for a non-admin, who sees no warnings."""
        if self._bundle is None and self.is_admin:
            self._bundle = WarningBundle.load(self.days)
        return self._bundle

    def weeks(self):
        bundle = self.bundle()
        out = []
        for m in self.mondays:
            in_week = [d for d in self.days if week_monday(d) == m]
            if not in_week:
                continue
            drafts = sum(1 for e in self.entries
                         if week_monday(e.day) == m and not e.is_published)
            out.append({
                "monday": m,
                "end": max(in_week),
                "colspan": len(in_week) * 2,
                "drafts": drafts,
                "is_anchor": m == self.anchor,
                "warnings": (week_warnings(in_week, include_drafts=True, bundle=bundle)
                             if self.is_admin else []),
            })
        return out

    def day_headers(self):
        bundle = self.bundle()
        return [
            {"day": d, "closed": d in self.closed, "note": self.notes.get(d),
             "week_start": d in self.week_starts, "today": d == self.today,
             "warnings": (day_warnings(d, include_drafts=True, resolver=self.resolver,
                                       bundle=bundle) if self.is_admin else [])}
            for d in self.days
        ]

    # ---- body ----------------------------------------------------------

    def build_row(self, clinician, is_locum):
        """One clinician's row, or None when the roster rule hides them."""
        has_entry = any((clinician.id, d, part) in self.cell_map
                        for d in self.days for part in ("AM", "PM"))
        in_service = any(self.resolver.in_service(clinician.id, d) for d in self.days)
        if not shows_on_roster(is_locum=is_locum, has_entry=has_entry,
                               in_service=in_service):
            return None
        cells = []
        for d in self.days:
            am, pm = (cell_state(
                clinician.id, d, part,
                entry=self.cell_map.get((clinician.id, d, part)),
                resolver=self.resolver, closed=d in self.closed,
                partner=self.companion_partner.get((clinician.id, d, part)),
            ) for part in ("AM", "PM"))
            flags = {"week_start": d in self.week_starts, "today": d == self.today}
            if one_block(am, pm):
                # One chip across both columns; its form edits the whole
                # day (part "DAY") unless the admin picks a half.
                cells.append({**am, "part": "DAY", "merged": True,
                              "note": day_note(am, pm), **flags})
            else:
                cells.append({**am, "merged": False, **flags})
                cells.append({**pm, "merged": False, "week_start": False,
                              "today": d == self.today})
        return {
            "clinician": clinician,
            "mine": clinician.user_id == self.user.id,
            "cells": cells,
        }

    def sections(self):
        groups = ClinicianGroup.objects.prefetch_related(
            Prefetch("clinicians", queryset=Clinician.objects.filter(active=True)
                     .order_by("display_order", "name")))
        out = []
        for group in groups:
            rows = [row for row in (self.build_row(c, group.is_locum_group)
                                    for c in group.clinicians.all()) if row]
            if rows or group.is_locum_group:
                out.append({"group": group, "rows": rows})
        return out

    def locum_cells(self):
        reqs = LocumRequirement.objects.filter(day__in=self.days).select_related(
            "session_type", "covering")
        req_map = {}
        for r in reqs:
            req_map.setdefault((r.day, r.part), []).append(r)
        return [
            {"day": d, "day_str": d.isoformat(), "part": part,
             "reqs": req_map.get((d, part), []),
             "week_start": d in self.week_starts and part == "AM",
             "today": d == self.today}
            for d in self.days for part in ("AM", "PM")
        ]
```

- [ ] **Step 4: Slim the view**

Replace `rota/views/grid.py` with:

```python
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.services import grid as grid_svc
from rota.services.breathe.links import (unlinked_changelist_url,
                                         unlinked_clinicians)


@login_required
def grid(request):
    is_admin = request.user.is_rota_admin
    anchor = grid_svc.parse_anchor(request.GET.get("week"))
    window = grid_svc.Window(anchor, is_admin, request.user)
    step = timedelta(days=7 * grid_svc.STEP_WEEKS)
    return render(request, "rota/grid.html", {
        "anchor": anchor,
        "start": window.start,
        "end": window.end,
        "earlier": anchor - step,
        "later": anchor + step,
        "today": window.today,
        "today_shown": window.today in window.days,
        "weeks": window.weeks(),
        "day_headers": window.day_headers(),
        "sections": window.sections(),
        "locum_cells": window.locum_cells(),
        "cols": len(window.days) * 2,
        "colspan": len(window.days) * 2 + 1,
        "is_admin": is_admin,
        "has_clinician": getattr(request.user, "clinician", None) is not None,
        "unlinked_count": unlinked_clinicians().count() if is_admin else 0,
        "unlinked_url": unlinked_changelist_url(),
    })
```

- [ ] **Step 5: The row template**

```django
{% comment %}One clinician's row. Rendered by the grid page for every row
and by /rota/entered/ for the one row it changed, so there is one row
markup. Context: row, is_admin.{% endcomment %}
<tr class="{% if row.mine %}mine{% endif %}">
  <th class="grid-clin" scope="row" title="{{ row.clinician.name }}">{{ row.clinician.initials }}</th>
  {% for cell in row.cells %}
  <td {% if cell.merged %}colspan="2"{% endif %}
      class="{% if cell.entry and not cell.entry.is_published %}draft{% endif %}{% if cell.closed %} closed{% endif %}{% if cell.week_start %} week-start{% endif %}{% if cell.today %} is-today{% endif %}"
      {% if is_admin %}hx-get="/rota/cell/{{ row.clinician.id }}/{{ cell.day_str }}/{{ cell.part }}/"
      hx-target="#modal"{% endif %}
      title="{{ cell.entry.fill_reason|default:'' }} {{ cell.note }}{% if cell.partner %} with {{ cell.partner }}{% endif %}{% if cell.clash %}{% if cell.entry.fill_reason or cell.note or cell.partner %} — {% endif %}On Breathe leave: {{ cell.leave_label }}{% endif %}">
    {% if cell.entry %}
      <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}{% if cell.clash %} is-clash{% endif %}{% if cell.note %} has-note{% endif %}"
            style="--chip-bg: var(--tint-{{ cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.entry.session_type.tint.key }}-fg);">
        {{ cell.entry.session_type.code }}{% if cell.entry.site %}<span class="site-marker">{{ cell.entry.site.name|slice:":1" }}</span>{% endif %}
      </span>
    {% elif cell.absence %}
      <span class="chip" title="{{ cell.leave_label }} — from Breathe"
            style="--chip-bg: var(--tint-{{ cell.absence.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.absence.tint.key }}-fg);">
        {{ cell.absence.code }}
      </span>
    {% elif cell.off_pattern %}
      <span class="chip is-off is-not-working" title="Not a working session">OFF</span>
    {% elif cell.off %}
      <span class="chip is-off">&nbsp;</span>
    {% else %}
      <span class="chip empty-slot">&nbsp;</span>
    {% endif %}
  </td>
  {% endfor %}
</tr>
```

- [ ] **Step 6: The page template**

Replace `templates/rota/grid.html` with:

```django
{% extends "base.html" %}{% load static %}
{% block title %}Rota — weeks of {{ start|date:"j M" }} – {{ end|date:"j M Y" }}{% endblock %}
{% block body_attrs %} class="page-grid"{% endblock %}
{% block content %}
<div class="toolbar">
  <a href="?week={{ earlier|date:'Y-m-d' }}" class="btn">&larr; Earlier</a>
  <a href="?week={{ today|date:'Y-m-d' }}" class="btn" id="grid-today"{% if today_shown %} data-scroll="1"{% endif %}>Today</a>
  <a href="?week={{ later|date:'Y-m-d' }}" class="btn">Later &rarr;</a>
  <h2>Weeks of {{ start|date:"j M" }} – {{ end|date:"j M Y" }}</h2>
  <form method="get"><input type="date" name="week"><button class="btn">Go</button></form>
  {% if has_clinician %}
  <a href="/me/swap/new/" class="btn">Propose swap</a>
  {% endif %}
</div>
{% if unlinked_count %}
<div class="warn">{{ unlinked_count }} clinician{{ unlinked_count|pluralize }} not linked to Breathe — no leave is read for them. <a href="{{ unlinked_url }}">Link them</a>.</div>
{% endif %}
<script src="{% static 'js/grid.js' %}" defer></script>
<div class="grid-wrap">
<table class="table-grid" style="--cols: {{ cols }}" data-start="{{ start|date:'Y-m-d' }}">
<caption class="visually-hidden">Rota for the weeks of {{ start|date:"j F Y" }} to {{ end|date:"j F Y" }}</caption>
<thead>
<tr>
  <th class="grid-clin"></th>
  {% for w in weeks %}
  <th colspan="{{ w.colspan }}" scope="colgroup" class="grid-week week-start{% if w.is_anchor %} is-anchor{% endif %}" data-monday="{{ w.monday|date:'Y-m-d' }}">
    <span class="week-label">Week of {{ w.monday|date:"j M" }}</span>
    {% if is_admin and w.drafts %}
    <form hx-post="/rota/publish/" class="week-publish">
      <input type="hidden" name="start" value="{{ w.monday|date:'Y-m-d' }}">
      <input type="hidden" name="end" value="{{ w.end|date:'Y-m-d' }}">
      <button class="btn btn-primary">Publish · {{ w.drafts }} draft{{ w.drafts|pluralize }}</button>
    </form>
    {% endif %}
    {% for x in w.warnings %}<div class="warn">{{ x.message }}</div>{% endfor %}
  </th>
  {% endfor %}
</tr>
<tr>
  <th class="grid-clin"></th>
  {% for h in day_headers %}
  <th colspan="2" scope="colgroup" class="grid-day{% if h.closed %} closed{% endif %}{% if h.week_start %} week-start{% endif %}{% if h.today %} is-today{% endif %}"
      {% if is_admin %}hx-get="/rota/daynote/{{ h.day|date:'Y-m-d' }}/" hx-target="#modal"{% endif %}>
    {{ h.day|date:"D j M" }}
    {% if h.note %}<div class="daynote">{{ h.note.text }}</div>{% endif %}
    {% for w in h.warnings %}<div class="warn">{{ w.message }}</div>{% endfor %}
  </th>
  {% endfor %}
</tr>
<tr><th class="grid-clin"></th>{% for h in day_headers %}<th class="grid-part{% if h.closed %} closed{% endif %}{% if h.week_start %} week-start{% endif %}{% if h.today %} is-today{% endif %}" scope="col">AM</th><th class="grid-part{% if h.closed %} closed{% endif %}{% if h.today %} is-today{% endif %}" scope="col">PM</th>{% endfor %}</tr>
</thead>
{% for section in sections %}
<tbody>
<tr class="grid-group"><td colspan="{{ colspan }}">{{ section.group.name }}</td></tr>
{% for row in section.rows %}{% include "rota/_grid_row.html" %}{% endfor %}
{% if section.group.is_locum_group %}
<tr>
  <th class="grid-clin" scope="row">Need</th>
  {% for cell in locum_cells %}
  <td class="{% if cell.week_start %}week-start{% endif %}{% if cell.today %} is-today{% endif %}">
    {% for r in cell.reqs %}
    <span class="badge {{ r.status }}"
          {% if is_admin %}hx-get="/rota/locum/{{ r.id }}/form/" hx-target="#modal"{% endif %}
          title="{% if r.covering %}Covering {{ r.covering.name }}{% if r.details %} — {% endif %}{% endif %}{{ r.details }}">{{ r.get_status_display }}</span>
    {% endfor %}
    {% if is_admin %}
    <span class="badge" hx-get="/rota/locum/new/?day={{ cell.day_str }}&part={{ cell.part }}"
          hx-target="#modal">+</span>
    {% endif %}
  </td>
  {% endfor %}
</tr>
{% endif %}
</tbody>
{% endfor %}
</table>
</div>
{% endblock %}
```

- [ ] **Step 7: Run the grid tests**

Run: `pytest tests/test_grid_window.py tests/test_grid_view.py tests/test_grid_rendering.py tests/test_grid_pane.py tests/test_grid_editing_ring.py tests/test_accessibility.py tests/test_day_pinning.py tests/test_clinician_order.py -q`
Expected: pass. Likely snags and their fixes:
- A test elsewhere asserting the old `<h2>Week of` or "Publish week" text: re-point it to the new text and rewrite its docstring to say why the text moved.
- `test_query_count_does_not_grow_with_weeks_of_entries` failing on the equality: read the two captured lists side by side (`[q["sql"][:80] for q in eight_weeks]`) and find the query that runs per entry or per day; every such read belongs in `Window._load` or `WarningBundle.load`. `cell_state` must not touch `entry.session_type.tint` lazily — `select_related("session_type")` covers it.
- The absolute cap of 30: if the honest fixed count is higher, set the cap to that number and say in the assertion message what it is made of.

- [ ] **Step 8: Run the whole suite, then commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/services/grid.py rota/views/grid.py templates/rota/grid.html templates/rota/_grid_row.html tests/test_grid_window.py tests/test_grid_view.py graphify-out
git commit -m "feat: the grid renders an eight-week window with a header cell and Publish per week

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Width, week boundaries, today, and the scroll script

**Files:**
- Modify: `static/css/components.css:283-343` (the width comment and `.table-grid` rule; add `.week-start` and `.is-today` rules after `.table-grid tr.mine .grid-clin`)
- Modify: `static/css/screens.css` (after `.grid-part`: `.grid-week`, `.week-label`, `.week-publish`)
- Rewrite: `static/js/grid.js`
- Modify: `tests/test_css_cascade.py` (`test_only_the_clinician_column_is_given_a_width`, `test_the_grid_has_its_horizontal_floor_on_the_table`), `tests/test_chrome_contrast.py:PAIRS`, `tests/test_grid_editing_ring.py` (unchanged assertions; it must still pass)
- Test: `tests/test_grid_scroll.py` (new)

**Interfaces:**
- Consumes: the `style="--cols: N"`, `data-start`, `.grid-week.is-anchor`, `#grid-today[data-scroll]`, `.grid-day.is-today` hooks from Task 6.

- [ ] **Step 1: Re-point the two cascade tests and write the new ones**

In `tests/test_css_cascade.py`, replace `test_only_the_clinician_column_is_given_a_width`'s `offenders` regex with `r"\.grid-(day|part|week)\b"` and add to its docstring: "The week header cell joins the rule: it spans a week's columns and a width on it would be a floor on the whole week."

Replace `test_the_grid_has_its_horizontal_floor_on_the_table` with:

```python
def test_the_grid_has_its_horizontal_floor_on_the_table():
    """With the day columns auto there is no per-column floor left, so the
    floor lives on the table: `.grid-wrap` is `overflow: auto`, and a table
    wider than it scrolls sideways inside it. min-width on the *cells* would
    be inert — it is not an input to the fixed-layout algorithm. The floor
    used to be one length sized for a five-day week (42rem); the grid now
    renders a window of weeks, so the template sets `--cols` to the number
    of half-day columns and the floor is a calc() over it. The per-column
    term is what the old floor gave each of ten columns after the 5.5rem
    name column, so a one-week window would render exactly as before and an
    eight-week one is eight times wider than the pane."""
    floor = declares(".table-grid", "min-width")
    m = re.fullmatch(r"calc\(5\.5rem \+ var\(--cols(?:,\s*\d+)?\) \* ([\d.]+)rem\)", floor)
    assert m, floor
    assert float(m.group(1)) >= 3.5, floor
    wrap = rule(".grid-wrap")
    assert wrap.declarations.get("overflow") == "auto", wrap.declarations


def test_week_boundary_and_today_marks_do_not_touch_positioning():
    """Both classes land on header cells inside the sticky <thead> and on
    the frozen .grid-clin's neighbours; a position/top/left/z-index on
    either would fight the sticky rules."""
    for selector in (".table-grid .week-start", ".table-grid thead th.is-today",
                     ".table-grid td.is-today"):
        decl = rule(selector).declarations
        assert not {"position", "top", "left", "z-index"} & set(decl), (selector, decl)
    assert declares(".table-grid .week-start", "border-left").startswith("2px solid var(--")
    assert declares(".table-grid thead th.is-today", "background") == "var(--accent-soft)"
    assert declares(".table-grid td.is-today", "box-shadow").startswith("inset")
```

Create `tests/test_grid_scroll.py`:

```python
"""The pane scrolls to the anchor week on load, remembers where it was
across the full-page refresh every cell save triggers, and the Today
button scrolls rather than reloads when today is on the page."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_script_anchors_restores_and_jumps():
    js = (ROOT / "static/js/grid.js").read_text()
    assert "sessionStorage" in js and '"grid-scroll:"' in js
    assert "dataset.start" in js
    assert '".grid-week.is-anchor"' in js
    assert "pagehide" in js and "htmx:beforeRequest" in js
    assert 'getElementById("grid-today")' in js and ".grid-day.is-today" in js
    assert "preventDefault" in js and "scrollLeft" in js


def test_storage_access_is_guarded():
    """A private window or blocked site data throws on access; the grid
    must still load."""
    js = (ROOT / "static/js/grid.js").read_text()
    assert js.count("try {") >= 2
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_css_cascade.py tests/test_grid_scroll.py -q`
Expected: the re-pointed floor test, the new cascade test and both script tests fail.

- [ ] **Step 3: CSS**

In `static/css/components.css`, replace the last paragraph of the long width comment (from "The floor is one length rather than per-column" to the end of that sentence) with:

```
   The floor is a calc() over --cols, which the template sets to the number
   of half-day columns in the window (grid.html): 3.5rem per column after
   the 5.5rem name column is exactly what the old 42rem floor gave each of
   ten columns, so a one-week window would render as before and an
   eight-week one is eight times wider than the pane and scrolls inside
   it. A practice open six or seven days gets the same 3.5rem per column
   instead of squeezing.
```

and change the rule:

```css
.table-grid { border-collapse: separate; border-spacing: 2px;
              font-variant-numeric: tabular-nums; width: 100%;
              min-width: calc(5.5rem + var(--cols, 10) * 3.5rem);
              table-layout: fixed; }
```

After `.table-grid tr.mine .grid-clin { ... }`, add:

```css
/* Week boundaries and today. The window shows eight weeks in one table,
   so the first column of each week — the week cell, the day cell, the AM
   part cell and every body cell under them — carries a heavier left
   border the full height of the table. --muted rather than --hairline:
   1px hairline is too faint to follow across a 25-row table. Today's
   header cells take the accent-soft ground (ink on accent-soft is a
   checked pairing); today's body cells take a 1px inset ring on the td,
   not a background, so the chip's own tint is untouched. Neither touches
   position/top/left/z-index (tests/test_css_cascade.py). */
.table-grid .week-start { border-left: 2px solid var(--muted); }
.table-grid thead th.is-today { background: var(--accent-soft); }
.table-grid td.is-today {
  box-shadow: inset 1px 0 0 var(--accent), inset -1px 0 0 var(--accent);
}
```

In `static/css/screens.css`, after the `.grid-part` rule:

```css
/* The week header row: label left, the week's Publish beside it. */
.grid-week {
  text-align: left;
  font-size: var(--fs-sm);
  font-weight: 700;
  color: var(--ink);
  vertical-align: middle;
}
.week-publish {
  display: inline-block;
  margin-left: var(--sp-2);
}
```

In `tests/test_chrome_contrast.py`, change the `("ink", "accent-soft", ...)` description to `".flash, .mine's clinician cell, today's header cells"`.

- [ ] **Step 4: The script**

Replace `static/js/grid.js` with:

```js
// Three jobs on the week page, each its own function.
//
// 1. The cell whose form is open gets a ring, so it is clear which one was
//    clicked. Set when a click on the grid opens the modal; cleared when
//    the modal empties (Cancel) — Save reloads the page (HX-Refresh),
//    which clears it by itself. The day headers and the locum "+" cells
//    open forms the same way, so they get the same ring.
// 2. The pane shows eight weeks and scrolls sideways. On load it lands on
//    the anchor week, unless this is the refresh a save just triggered, in
//    which case it lands where the admin was: the position is written to
//    sessionStorage under the window's start date before any htmx request
//    and on pagehide, and read back once. A different window (Earlier,
//    Later, Go) has a different key and lands on its anchor.
// 3. Today: when today's column is on the page the Today link scrolls to
//    it instead of reloading; otherwise it is the plain link it renders as.
(function () {
  var modal = document.getElementById("modal");
  var pane = document.querySelector(".grid-wrap");
  var table = document.querySelector(".table-grid");
  if (!modal || !pane || !table) return;

  function ring() {
    function clear() {
      document.querySelectorAll(".is-editing").forEach(function (el) {
        el.classList.remove("is-editing");
      });
    }
    document.body.addEventListener("htmx:beforeRequest", function (e) {
      var el = e.detail.elt;
      if (e.detail.target !== modal || !el.closest || !el.closest(".table-grid")) return;
      var cell = el.closest("td, th");
      if (!cell) return;
      clear();
      cell.classList.add("is-editing");
    });
    new MutationObserver(function () {
      if (!modal.childElementCount) clear();
    }).observe(modal, { childList: true });
  }

  function scrollToCell(cell) {
    var corner = table.querySelector("thead .grid-clin");
    pane.scrollLeft = cell.offsetLeft - (corner ? corner.offsetWidth : 0);
  }

  function position() {
    var key = "grid-scroll:" + (table.dataset.start || "");
    var saved = null;
    try {
      saved = sessionStorage.getItem(key);
      sessionStorage.removeItem(key);
    } catch (e) { /* storage blocked: land on the anchor */ }
    if (saved !== null) {
      pane.scrollLeft = parseInt(saved, 10) || 0;
    } else {
      var anchor = table.querySelector(".grid-week.is-anchor");
      if (anchor) scrollToCell(anchor);
    }
    function remember() {
      try { sessionStorage.setItem(key, String(pane.scrollLeft)); } catch (e) { /* ignore */ }
    }
    document.body.addEventListener("htmx:beforeRequest", remember);
    window.addEventListener("pagehide", remember);
  }

  function today() {
    var link = document.getElementById("grid-today");
    var cell = table.querySelector("thead .grid-day.is-today");
    if (!link || !cell) return;
    link.addEventListener("click", function (e) {
      e.preventDefault();
      scrollToCell(cell);
    });
  }

  ring();
  position();
  today();
})();
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_css_cascade.py tests/test_grid_scroll.py tests/test_grid_editing_ring.py tests/test_chrome_contrast.py tests/test_grid_window.py -q`
Expected: pass. `test_grid_editing_ring.py` asserts the strings `'closest(".table-grid")'`, `'closest("td, th")'`, `classList.add("is-editing")`, `MutationObserver`, `childElementCount` — all still present.

- [ ] **Step 6: Look at it**

Run: `DEBUG=1 python manage.py runserver 0.0.0.0:8000` and open `/rota/` as an admin. Check: the table is wider than the pane and scrolls; the first week is one scroll-width to the left of where the page lands; each week begins with a heavier line; today's column is tinted in the header and ringed in the body; Publish sits in a week header only where that week has drafts; saving a cell brings the page back to the same scroll position; Today scrolls when today is on the page. Stop the server.

- [ ] **Step 7: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add static/css/components.css static/css/screens.css static/js/grid.js tests/test_css_cascade.py tests/test_chrome_contrast.py tests/test_grid_scroll.py graphify-out
git commit -m "feat: the grid's width follows its column count; week boundaries, today, and scroll memory

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The "entered in the clinical system" mark — data and services

**Files:**
- Modify: `rota/models/entries.py:7-43`
- Create: `rota/migrations/0030_rotaentry_entered.py` (generated)
- Modify: `rota/services/entries.py` (`assign`; add `set_entered`)
- Modify: `rota/services/swaps.py:206-229` (both branches of `approve`)
- Modify: `rota/services/cells.py` (`cell_state`, `one_block`)
- Modify: `rota/services/grid.py:_load` (`select_related` gains `entered_by__clinician`)
- Modify: `rota/admin.py:541-558` (`RotaEntryAdmin`)
- Test: `tests/test_entered.py` (new); `tests/test_cells.py`

**Interfaces:**
- Produces: `RotaEntry.entered_at: DateTimeField(null)`, `RotaEntry.entered_by: FK(user, null)`; `entries.set_entered(actor, entry, on: bool) -> None`; `cell_state(...)["entered"]: bool`, `["entered_by"]: str`. Task 9 calls `set_entered` and renders both cell keys.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entered.py
"""A session keyed into the clinical system's appointment screen carries
when and by whom. Anything that changes what the session is clears it."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model

from rota.models import RotaEntry, RotaEntryLog, Site, SwapRequest
from rota.services import entries as entries_svc
from rota.services import swaps as swaps_svc
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
User = get_user_model()
TUE = MON + timedelta(days=1)


def test_set_entered_stamps_and_logs(admin_user):
    e = make_entry(make_clinician())
    entries_svc.set_entered(admin_user, e, True)
    e.refresh_from_db()
    assert e.entered_at is not None and e.entered_by == admin_user
    assert RotaEntryLog.objects.filter(action="entered", day=MON, part="AM").exists()
    entries_svc.set_entered(admin_user, e, False)
    e.refresh_from_db()
    assert e.entered_at is None and e.entered_by is None
    assert RotaEntryLog.objects.filter(action="unentered").exists()


def test_a_note_only_save_keeps_the_mark(admin_user):
    c = make_clinician()
    rout = make_session_type("Routine")
    e = make_entry(c, session_type=rout)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", rout, note="ring first")
    e.refresh_from_db()
    assert e.entered_at is not None and e.note == "ring first"


def test_a_type_change_clears_the_mark(admin_user):
    c = make_clinician()
    e = make_entry(c, session_type=make_session_type("Routine"))
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", make_session_type("Duty", code="DUTY"))
    e.refresh_from_db()
    assert e.entered_at is None and e.entered_by is None


def test_a_site_change_clears_the_mark(admin_user):
    c = make_clinician()
    rout = make_session_type("Routine")
    e = make_entry(c, session_type=rout)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", rout, site=Site.objects.create(name="Branch"))
    e.refresh_from_db()
    assert e.entered_at is None


def test_publishing_keeps_the_mark(admin_user):
    e = make_entry(make_clinician(), is_published=False)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.publish_range(admin_user, MON, MON)
    e.refresh_from_db()
    assert e.is_published and e.entered_at is not None


def test_a_fill_rerun_leaves_a_published_marked_session_alone(admin_user):
    from rota.models import PracticeSettings
    from rota.services.fill import run_fill
    PracticeSettings.load()
    e = make_entry(make_clinician())            # published, manually set
    entries_svc.set_entered(admin_user, e, True)
    run_fill(admin_user, MON, MON)
    e.refresh_from_db()
    assert e.entered_at is not None


def _accepted_swap(admin_user):
    """The scenario tests/test_swaps.py proves applies: Alice has Duty Mon
    (full day) + Routine Tue AM; Beth has Routine Mon AM/PM + Duty Tue AM.
    Alice offers Mon AM for Beth's Tue AM — a trade of the work. Every
    entry the swap touches is marked first."""
    duty = make_session_type("Duty", code="DUTY", fairness_tracked=True)
    rout = make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    entries_svc.assign_full_day(None, a, MON, duty, published=True)
    make_entry(a, day=TUE, part="AM", session_type=rout)
    make_entry(b, day=MON, part="AM", session_type=rout)
    make_entry(b, day=MON, part="PM", session_type=rout)
    entries_svc.assign(None, b, TUE, "AM", duty, published=True)
    for e in RotaEntry.objects.all():
        entries_svc.set_entered(admin_user, e, True)
    b.user = User.objects.create_user(email="beth@example.com", password="pw")
    b.save()
    req = SwapRequest.objects.create(
        proposer=a, proposer_day=MON, proposer_part="AM",
        colleague=b, colleague_day=TUE, colleague_part="AM")
    swaps_svc.accept(req, b.user)
    return req


def test_an_approved_swap_clears_the_mark_on_every_entry_it_touches(admin_user):
    req = _accepted_swap(admin_user)
    swaps_svc.approve(admin_user, req)
    touched = RotaEntry.objects.filter(day__in=(MON, TUE), part="AM")
    assert touched.count() == 4
    assert not touched.filter(entered_at__isnull=False).exists()
    # Beth's Mon PM and Alice's Mon PM are the swap's linked full-day
    # halves; the swap moves them too, so they are cleared as well.
    assert not RotaEntry.objects.filter(entered_at__isnull=False).exists()
```

If the last assertion fails because the swap leaves a PM half untouched, drop only that assertion and its comment: the contract is that every entry `approve()` saves is cleared, and the four AM entries prove it.

Append to `tests/test_cells.py` (add `make_session_type` to its factories import if it is not there):

```python
def test_a_marked_half_does_not_merge_with_an_unmarked_half(admin_user):
    from rota.services.cells import one_block
    from rota.services import entries as entries_svc
    c = make_clinician()
    _works(c)
    rout = make_session_type("Routine")
    am = make_entry(c, day=TUE, part="AM", session_type=rout)
    pm = make_entry(c, day=TUE, part="PM", session_type=rout)
    entries_svc.set_entered(admin_user, am, True)
    r = _resolver([c])
    a = cell_state(c.id, TUE, "AM", entry=am, resolver=r, closed=False)
    p = cell_state(c.id, TUE, "PM", entry=pm, resolver=r, closed=False)
    assert a["entered"] is True and p["entered"] is False
    assert a["entered_by"] == "admin@example.com"
    assert not one_block(a, p)
    entries_svc.set_entered(admin_user, pm, True)
    p = cell_state(c.id, TUE, "PM", entry=pm, resolver=r, closed=False)
    assert one_block(a, p)
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_entered.py tests/test_cells.py -q`
Expected: failures on `set_entered` not existing / `KeyError: 'entered'`.

- [ ] **Step 3: Model and migration**

In `rota/models/entries.py`, after `fill_reason`:

```python
    # Keyed into the clinical system's appointment screen: when, and by
    # whom. Set from the grid's ticking mode; cleared by anything that
    # changes what the session is (services/entries.assign on a type or
    # site change, either kind of swap). A timestamp, not a boolean, so the
    # tooltip can say when.
    entered_at = models.DateTimeField(null=True, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
```

Run: `DEBUG=1 python manage.py makemigrations rota -n rotaentry_entered`
Expected: `rota/migrations/0030_rotaentry_entered.py` with two `AddField`s.

- [ ] **Step 4: Services**

`rota/services/entries.py`: add `from django.utils import timezone` to the imports. In `assign`, inside `if existing:` before `existing.session_type = session_type`:

```python
        # A different session, or the same one somewhere else, has to be
        # keyed into the clinical system again; a note-only save does not.
        if (existing.session_type_id != session_type.id
                or existing.site_id != getattr(site, "id", None)):
            existing.entered_at = None
            existing.entered_by = None
```

After `publish_range`, add:

```python
@transaction.atomic
def set_entered(actor, entry, on):
    """Mark a session as keyed into the clinical system's appointment
    screen — or unmark it. The only writer of the two fields."""
    entry.entered_at = timezone.now() if on else None
    entry.entered_by = actor if on else None
    entry.save(update_fields=["entered_at", "entered_by", "updated_at"])
    _log(actor, entry.day, entry.part, entry.clinician.name,
         "entered" if on else "unentered", entry.session_type.code)
```

`rota/services/swaps.py`, in `approve`: in the WORK branch after `e1.manually_set = e2.manually_set = True` add

```python
            e1.entered_at = e2.entered_at = None
            e1.entered_by = e2.entered_by = None
```

and in the PEOPLE branch after `e.manually_set = True` add

```python
                e.entered_at = None
                e.entered_by = None
```

`rota/services/cells.py`, in `cell_state` before the `return`:

```python
    # Who keyed it in, for the tooltip: the actor's initials when they are
    # a clinician, else their email. Read only when marked, so an
    # unmarked cell never touches the relation.
    entered = entry is not None and entry.entered_at is not None
    entered_by = ""
    if entered and entry.entered_by is not None:
        who = getattr(entry.entered_by, "clinician", None)
        entered_by = who.initials if who else entry.entered_by.email
```

add `"entered": entered, "entered_by": entered_by,` to the dict, and in `one_block` add the clause

```python
            and (a.entered_at is None) == (b.entered_at is None)
```

with a sentence in its docstring: "both marked as entered in the clinical system or neither (the strike is per chip)".

`rota/services/grid.py`, `_load`: `select_related("session_type", "clinician", "site", "entered_by", "entered_by__clinician")`.

`rota/admin.py`, `RotaEntryAdmin`:

```python
    list_display = ("day", "part", "clinician", "session_type", "site",
                    "is_published", "manually_set", "entered_at")
    list_filter = ("is_published", "manually_set",
                   ("entered_at", admin.EmptyFieldListFilter),
                   "session_type", "clinician")
    readonly_fields = ("entered_at", "entered_by")
```

and the "State" fieldset's fields become `("is_published", "manually_set", "fill_reason", "entered_at", "entered_by")` with this appended to its description: `" Entered says when the session was keyed into the clinical system, from the grid's ticking mode."`

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_entered.py tests/test_cells.py tests/test_swaps.py tests/test_admin_render.py tests/test_grid_window.py -q`
Expected: pass. If `admin.EmptyFieldListFilter` does not render under unfold, replace it with a `SimpleListFilter` named `EnteredFilter` with lookups `("yes", "Entered")` / `("no", "Not entered")` filtering `entered_at__isnull`.

- [ ] **Step 6: Checks and commit**

```bash
ruff check . && DEBUG=1 python manage.py makemigrations --check && pytest -q && graphify update .
git add rota/models/entries.py rota/migrations/0030_rotaentry_entered.py rota/services/entries.py rota/services/swaps.py rota/services/cells.py rota/services/grid.py rota/admin.py tests/test_entered.py tests/test_cells.py graphify-out
git commit -m "feat: a rota entry records when it was entered into the clinical system, and what clears that

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Ticking mode

**Files:**
- Modify: `rota/views/grid.py` (the `tick` flag), `rota/views/edit.py` (the `entered` endpoint), `rota/urls.py`
- Modify: `templates/rota/grid.html` (toolbar link, banner, body class, links carry the flag), `templates/rota/_grid_row.html` (cell attributes, `is-entered`, tooltip)
- Modify: `static/css/components.css` (`.chip.is-entered`, after `.chip.has-note::after`)
- Modify: `tests/test_grid_pane.py` (unchanged assertion must still hold with the flag off)
- Test: `tests/test_ticking.py` (new)

**Interfaces:**
- Consumes: `entries.set_entered`, `cell_state()["entered"]`/`["entered_by"]` (Task 8); `grid_svc.Window.build_row`, `parse_anchor` (Task 6).
- Produces: `POST /rota/entered/` with `clinician_id`, `day`, `part` (`AM`/`PM`/`DAY`), `week`; returns the re-rendered `<tr>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ticking.py
"""Ticking mode: an admin-only URL flag under which clicking a chip marks
the session as entered in the clinical system, in place, no form. The
mark is struck through for admins and invisible to everyone else."""

from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from tests.factories import MON, make_clinician, make_entry, make_pattern, make_session_type

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)


def _setup():
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    e = make_entry(c, day=TUE, part="AM", session_type=rout)
    return c, e


def test_the_toolbar_offers_ticking_mode_to_an_admin_only(admin_client, gp_client):
    _setup()
    on = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert f'href="?week={MON}&amp;tick=1"' in on or f'href="?week={MON}&tick=1"' in on
    assert 'aria-pressed="false"' in on
    assert "Ticking mode" not in gp_client.get(f"/rota/?week={MON}").content.decode()


def test_the_flag_is_ignored_for_a_gp(gp_client):
    _setup()
    html = gp_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert "is-ticking" not in html and "/rota/entered/" not in html


def test_in_ticking_mode_cells_with_entries_post_and_empty_cells_do_nothing(admin_client):
    c, e = _setup()
    html = admin_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert 'class="page-grid is-ticking"' in html
    assert 'aria-pressed="true"' in html
    assert "click a session to mark it entered" in html
    i = html.index(f'"day": "{TUE}", "part": "AM"')
    td = html[html.rindex("<td", 0, i):i + 200]
    assert 'hx-post="/rota/entered/"' in td and 'hx-target="closest tr"' in td
    assert "hx-get" not in td
    assert f'"week": "{MON}"' in td
    assert f'hx-get="/rota/cell/{c.id}/{MON}/AM/"' not in html
    assert "/rota/cell/" not in html


def test_the_earlier_later_and_today_links_carry_the_flag(admin_client):
    _setup()
    html = admin_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert f'href="?week={MON - timedelta(days=28)}&amp;tick=1"' in html \
        or f'href="?week={MON - timedelta(days=28)}&tick=1"' in html
    assert 'name="tick" value="1"' in html            # the Go form


def test_posting_toggles_and_returns_the_row(admin_client, admin_user):
    c, e = _setup()
    resp = admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM", "week": str(MON)})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert html.lstrip().startswith("<tr") and html.count("<tr") == 1
    assert "is-entered" in html and "Entered " in html and "by admin@example.com" in html
    e.refresh_from_db()
    assert e.entered_by == admin_user
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM", "week": str(MON)})
    e.refresh_from_db()
    assert e.entered_at is None


def test_a_whole_day_post_marks_both_halves_and_unmarks_when_all_marked(admin_client, admin_user):
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY")
    entries_svc.assign_full_day(admin_user, c, TUE, duty, published=True)
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "DAY", "week": str(MON)})
    assert RotaEntry.objects.filter(day=TUE, entered_at__isnull=False).count() == 2
    entries_svc.set_entered(admin_user, RotaEntry.objects.get(day=TUE, part="PM"), False)
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "DAY", "week": str(MON)})
    assert RotaEntry.objects.filter(day=TUE, entered_at__isnull=False).count() == 2, (
        "one half unmarked means the day is not all done: mark, don't unmark")


def test_the_endpoint_is_admin_only_and_post_only(gp_client, admin_client):
    c, e = _setup()
    assert gp_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM"}).status_code in (302, 403)
    assert admin_client.get("/rota/entered/").status_code == 405


def test_the_strike_shows_for_an_admin_and_not_a_gp(admin_client, gp_client, admin_user):
    c, e = _setup()
    entries_svc.set_entered(admin_user, e, True)
    admin_html = admin_client.get(f"/rota/?week={MON}").content.decode()
    gp_html = gp_client.get(f"/rota/?week={MON}").content.decode()
    assert "is-entered" in admin_html and "Entered " in admin_html
    assert "is-entered" not in gp_html and "Entered " not in gp_html
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_ticking.py -q`
Expected: all fail (no link, no endpoint).

- [ ] **Step 3: View flag and URL**

`rota/views/grid.py`: after `is_admin = ...` add `tick = is_admin and request.GET.get("tick") == "1"` and put `"tick": tick,` in the context.

`rota/urls.py`: after the publish route add `path("rota/entered/", edit.entered, name="entered"),`.

`rota/views/edit.py`: add `from rota.services import grid as grid_svc` to the imports and, after `publish`:

```python
@admin_required
@parse_errors_as_400
@require_POST
def entered(request):
    """Ticking mode's click. Marks every entry in the parts given as
    entered in the clinical system — or, when all of them already are,
    unmarks them — and answers with the clinician's re-rendered row, so
    the pane does not move."""
    clinician = get_object_or_404(Clinician.objects.select_related("group"),
                                  pk=request.POST["clinician_id"])
    day = date.fromisoformat(request.POST["day"])
    parts = _parts(_clean_scope(request.POST["part"]))
    with transaction.atomic():
        held = list(RotaEntry.objects.filter(
            clinician=clinician, day=day, part__in=parts).select_related("session_type"))
        on = not (held and all(e.entered_at for e in held))
        for e in held:
            entries_svc.set_entered(request.user, e, on)
    anchor = grid_svc.parse_anchor(request.POST.get("week"))
    window = grid_svc.Window(anchor, True, request.user)
    row = window.build_row(clinician, clinician.group.is_locum_group)
    if row is None:
        return _refresh()
    return render(request, "rota/_grid_row.html",
                  {"row": row, "is_admin": True, "tick": True, "anchor": anchor})
```

- [ ] **Step 4: Templates**

`templates/rota/grid.html`:

- `{% block body_attrs %} class="page-grid{% if tick %} is-ticking{% endif %}"{% endblock %}`
- The three toolbar links and the Go form carry the flag: append `{% if tick %}&tick=1{% endif %}` to each `href="?week=..."`, and inside the Go form add `{% if tick %}<input type="hidden" name="tick" value="1">{% endif %}` before the button.
- After the Propose swap link, inside the toolbar:

```django
  {% if is_admin %}
  <a href="?week={{ anchor|date:'Y-m-d' }}{% if not tick %}&tick=1{% endif %}" class="btn{% if tick %} btn-primary{% endif %}" aria-pressed="{% if tick %}true{% else %}false{% endif %}">Ticking mode</a>
  {% endif %}
```

- After the toolbar's closing `</div>`:

```django
{% if tick %}
<div class="flash">Ticking mode — click a session to mark it entered in the clinical system; click again to unmark. Turn it off to edit cells.</div>
{% endif %}
```

- Each `{% include "rota/_grid_row.html" %}` already sees `tick` and `anchor` from the page context.

`templates/rota/_grid_row.html`: replace the `<td ...>` opening tag's attribute block with:

```django
  <td {% if cell.merged %}colspan="2"{% endif %}
      class="{% if cell.entry and not cell.entry.is_published %}draft{% endif %}{% if cell.closed %} closed{% endif %}{% if cell.week_start %} week-start{% endif %}{% if cell.today %} is-today{% endif %}"
      {% if is_admin and tick %}{% if cell.entry %}hx-post="/rota/entered/" hx-vals='{"clinician_id": {{ row.clinician.id }}, "day": "{{ cell.day_str }}", "part": "{{ cell.part }}", "week": "{{ anchor|date:'Y-m-d' }}"}' hx-target="closest tr" hx-swap="outerHTML"{% endif %}{% elif is_admin %}hx-get="/rota/cell/{{ row.clinician.id }}/{{ cell.day_str }}/{{ cell.part }}/" hx-target="#modal"{% endif %}
      title="{% if is_admin and cell.entered %}Entered {{ cell.entry.entered_at|date:'D j M H:i' }} by {{ cell.entered_by }} — {% endif %}{{ cell.entry.fill_reason|default:'' }} {{ cell.note }}{% if cell.partner %} with {{ cell.partner }}{% endif %}{% if cell.clash %}{% if cell.entry.fill_reason or cell.note or cell.partner %} — {% endif %}On Breathe leave: {{ cell.leave_label }}{% endif %}">
```

and the entry chip's class list gains `{% if is_admin and cell.entered %} is-entered{% endif %}` after `has-note`.

`static/css/components.css`, after `.chip.has-note::after { ... }`:

```css
/* Entered in the clinical system's appointment screen (rendered for rota
   admins only — the templates gate the class). A strike in the chip's
   own foreground, so it holds on every tint in both themes with no new
   token; the tint, the draft hatch, the clash ring and the note dot are
   untouched. What the practice did on the sheet, so it needs no legend. */
.chip.is-entered {
  text-decoration: line-through;
  text-decoration-color: var(--chip-fg, var(--muted));
  text-decoration-thickness: 2px;
}
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_ticking.py tests/test_grid_window.py tests/test_grid_rendering.py tests/test_grid_pane.py tests/test_grid_view.py tests/test_entered.py -q`
Expected: pass. `test_grid_pane.py` asserts `'<body class="page-grid" hx-headers='` on the plain week page — the `{% if tick %}` renders nothing when off, so the string is unchanged. `test_grid_rendering.py`'s `_CELL_RE` reads the `hx-get` URL, which is present whenever `tick` is off.

- [ ] **Step 6: Look at it**

`DEBUG=1 python manage.py runserver 0.0.0.0:8000`, open `/rota/` as an admin, switch Ticking mode on: the banner shows, clicking a chip strikes it without a reload and without the pane moving, clicking again clears it, a whole-day chip strikes both halves, the tooltip names you and the time, Publish still works and returns with the mode still on. Switch it off: cells open the form again. Sign in as a GP: no strike, no button. Stop the server.

- [ ] **Step 7: Checks and commit**

```bash
ruff check . && pytest -q && graphify update .
git add rota/views/grid.py rota/views/edit.py rota/urls.py templates/rota/grid.html templates/rota/_grid_row.html static/css/components.css tests/test_ticking.py graphify-out
git commit -m "feat: ticking mode marks sessions as entered in the clinical system, struck through for admins

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Documentation and backlog

**Files:**
- Modify: `docs/admin/day-to-day.md` ("## Rota entries" section: the grid paragraph; the "Is published" / "Manually set" bullets gain an "Entered" bullet), `README.md:3-9`, `docs/backlog.md` ("## Settled" gets five entries at the top; the `day_warnings` note under "## Open — minor" is updated)

- [ ] **Step 1: day-to-day.md**

In "## Rota entries", after the sentence "Normally edited by clicking a cell on the grid; the admin view is for bulk corrections and for seeing the fields the grid hides.", add a paragraph:

```markdown
The grid shows **eight weeks at once** — one before the week you asked for
and six after — in one sideways-scrolling table. Each week has its own
header cell with the week's date, its **Publish** button (shown only while
the week holds drafts, and publishing only that week), and any per-week
ceiling warning. A heavier line marks where each week starts; today's
column is tinted. **Earlier** and **Later** move the window four weeks;
**Today** scrolls to today's column, or reloads on this week when today
is off the page; the date box jumps to any week. After you save a cell the
page comes back where you left it.

**Ticking mode** is for keying sessions into the clinical system's
appointment screen. Switch it on from the toolbar (admins only): clicking
a session marks it as entered and strikes its code through, clicking again
unmarks it, and a whole-day chip marks both halves. Nothing else on the
grid changes and the page does not reload. Switch it off to edit cells
again. The mark records when and by whom (the cell's tooltip says), and it
is **cleared automatically** when the session's type or site is changed,
when a swap moves it, or when assisted fill replaces a draft — because the
appointment screen would need redoing. Only admins see the strike; GPs see
the session as usual.
```

In the bullet list of fields, after "**Manually set**", add:

```markdown
- **Entered** — when, and by whom, the session was keyed into the clinical
  system's appointment screen. Set from the grid's ticking mode; the admin
  list filters on it ("Entered: empty" is what is left to key in).
```

- [ ] **Step 2: README.md**

In the first paragraph, after "passkeys" and before the full stop, add: "; the grid and fill round 2 — the eight-week grid, ticking mode, the suggested fill week, clinician order and the OFF chip".

- [ ] **Step 3: backlog.md**

Under "## Settled", insert at the top:

```markdown
- **Grid and fill, round 2** (2026-09-15; spec
  `docs/superpowers/specs/2026-09-15-grid-fill-round-2-design.md`). The
  grid renders eight weeks in one table — a header cell per week with
  that week's Publish and ceiling warning, a heavier rule at each week
  boundary, today tinted, Earlier/Later stepping four weeks, a Today
  button, and scroll position kept across the refresh a save triggers.
  The row assembly moved from the view into `rota/services/grid.py`
  (`Window`) and the warnings gained a `WarningBundle`, so forty days
  cost the same queries as five (pinned by a test). **Ticking mode**
  marks a session as entered in the clinical system — a timestamp and
  actor on the entry, struck through for admins only, cleared by a type
  or site change, a swap, or a fill replacing the draft. The fill screen
  opens on the first week under half filled
  (`rota/services/next_week.py`). Clinicians carry a display order within
  their group. A usual non-working half-day reads OFF; closed and
  out-of-window cells stay blank.
```

Under "## Open — minor", change the sentence "The dashboard's query count scales with coverage rules and entries (from the admin overhaul, PR #8); a windowed resolver in `day_warnings` is service work." to: "The dashboard's query count scales with coverage rules and entries (from the admin overhaul, PR #8). `day_warnings` now takes a prefetched `WarningBundle` and the grid passes one; the dashboard and the staffing report still call it per day and could pass one too."

- [ ] **Step 4: Commit**

```bash
git add docs/admin/day-to-day.md README.md docs/backlog.md
git commit -m "docs: the eight-week grid, ticking mode, the suggested fill week

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Finishing

Run the whole suite one last time, then `ruff check .`, `DEBUG=1 python manage.py makemigrations --check`, and `DEBUG=1 python manage.py check`. Push the branch and open a PR against `master` titled "Grid and fill, round 2"; the PR body lists the five sections of the spec and ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. CI (`ruff`, `makemigrations --check`, the suite on 3.13 and 3.14, `collectstatic` + `check --deploy`) must be green before merge; the ruleset requires rebase.
