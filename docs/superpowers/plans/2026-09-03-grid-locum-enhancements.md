# Grid, Leave and Locum Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seven bounded changes to the rota's screens: a visible note marker, Breathe clashes that name people and mark the cell, the leave reason as a tooltip, a delete-drafts card with a preview, a fourth locum status, who a locum covers, and locums hidden until booked.

**Architecture:** One piece of plumbing carries three of the seven — `cell_state()` learns that a cell can be on leave *and* hold an entry, and returns `clash` and `leave_label`; the warning, the templates and the day-view partition all read those keys, so nothing re-derives them. The locum work is a model change (one migration) plus the form and two roster screens. Draft deletion is a new service function that the fill engine also calls, so there is one deletion rule.

**Tech Stack:** Django 5.2, htmx, SQLite, pytest-django. Python 3.13. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-grid-locum-enhancements-design.md`

## Global Constraints

- No build step, no node, no new dependencies.
- Every colour comes from `static/css/tokens.css`. `components.css` and `screens.css` carry **no colour literals** — `tests/test_chrome_contrast.py::test_no_colour_literals_outside_tokens_css` greps for `#hex`, `rgb(`, `hsl(`.
- Exactly one width media query in the stylesheets: `@media (max-width: 640px)`. Add no other.
- `cell_state()` in `rota/services/cells.py` is the single answer to "what does this cell show". No view or template re-derives leave, clash or off state.
- Availability never fails open. Nothing in this plan touches `AvailabilityResolver.available()`, `works_on()` or the fill engine's eligibility.
- No pre-existing test assertion is weakened. When a message or title changes, the assertion is re-pointed at the new text; none is deleted. Every re-pointing is listed in the task that causes it.
- The Breathe API key appears in no file. Nothing here talks to Breathe; the autouse fixture in `tests/conftest.py` keeps the key empty.
- Run the full suite with `/root/rota/.venv/bin/python -m pytest -q` from `/root/rota`. It takes about five minutes. Run the targeted file first, the whole suite before each commit.
- Commit messages follow the repo's style: a lower-case type prefix (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`) and a sentence that says what changed and why. Every commit ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Baseline: **880 tests pass** on `master` at `da0f71c`. The branch is `feature/grid-locum-enhancements`.

---

## File map

| File | Responsibility after this plan |
|---|---|
| `rota/services/availability.py` | `covering()` becomes public (was `_covering`). |
| `rota/services/cells.py` | `leave_label()`, `shows_on_roster()`, and `cell_state()` returning `clash` and `leave_label`. |
| `rota/services/warnings.py` | `_breathe_conflicts()` names people via `cell_state`; `day_warnings()` accepts a resolver. |
| `rota/services/entries.py` | `drafts()` and `delete_drafts()`. |
| `rota/services/fill/__init__.py` | `run_fill()` clears its drafts through `delete_drafts()`. |
| `rota/services/locums.py` | `save_requirement(covering=...)`. |
| `rota/models/requests.py` | `LocumRequirement.Status.APPROVED`; `LocumRequirement.covering`. |
| `rota/migrations/0024_locum_status_and_covering.py` | One migration for both. |
| `rota/views/grid.py`, `rota/views/day.py` | Pass the resolver to warnings; hide idle locums. |
| `rota/views/my_schedule.py` | `_blocks()` guards `is_leave` with `is_open`. |
| `rota/views/fill.py` | `delete_drafts` view; shared base context. |
| `rota/views/edit.py` | Locum form reads `covering_id`. |
| `rota/urls.py` | `rota/drafts/delete/`. |
| `rota/admin.py` | `LocumRequirementAdmin.list_display` gains `covering`. |
| `templates/rota/grid.html`, `day.html`, `my_schedule.html` | Clash ring, leave tooltip, note marker and note text. |
| `templates/rota/_locum_form.html` | Covering-for dropdown. |
| `templates/rota/fill.html` | Delete-drafts card and preview. |
| `static/css/components.css` | `.chip` positioned; `.chip.is-clash`; `.chip.has-note::after`; `.badge.APPROVED`. |
| `static/css/screens.css` | `.day-note-text`; `.ms-note`; `.ms-today-cells` wraps. |
| `docs/admin/breathe.md`, `docs/admin/day-to-day.md` | Updated wording. |

---

### Task 1: `cell_state` knows a cell can be on leave and hold an entry

**Files:**
- Modify: `rota/services/availability.py:146-175`
- Modify: `rota/services/cells.py`
- Test: `tests/test_cells.py`

**Interfaces:**
- Consumes: `AvailabilityResolver._covering(clinician_id, day, part) -> (kind, reason) | None` (existing, private).
- Produces:
  - `AvailabilityResolver.covering(clinician_id, day, part) -> tuple[str, str] | None` (public).
  - `rota.services.cells.leave_label(kind: str, reason: str) -> str`.
  - `cell_state(...)` dict gains `"leave_label": str | None` and `"clash": bool`; `"on_leave"` is now `True` whenever Breathe covers the part, entry or not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cells.py`. Add `make_session_type` to the factories import at the top of the file (`from tests.factories import make_absence, make_clinician, make_entry, make_session_type`). The existing `_resolver` and `_works` helpers are reused.

```python
# ------------------------------------------------ leave under an entry ---
#
# A published week, then leave approved in Breathe: the entry still stands
# (an entry beats leave for what the cell SHOWS, by design) but the cell
# must know it is standing on leave, or nothing can mark it. `on_leave`
# used to be forced False whenever an entry existed. It is not any more.

from rota.services.cells import leave_label


def test_leave_label_per_kind():
    assert leave_label("holiday", "") == "Holiday"
    assert leave_label("holiday", "Annual") == "Holiday"
    assert leave_label("sickness", "") == "Sick"
    assert leave_label("other", "Jury service") == "Other leave: Jury service"
    assert leave_label("other", "") == "Other leave"
    assert leave_label("study", "") == "Study"


def test_covering_is_public_and_names_the_absence():
    c = make_clinician()
    _works(c)
    absences = [make_absence(c, TUE, kind="other", reason="Jury service")]
    r = _resolver([c], absences)
    assert r.covering(c.id, TUE, "AM") == ("other", "Jury service")
    assert r.covering(c.id, TUE + timedelta(days=1), "AM") is None
    assert not hasattr(r, "_covering"), "the private name was renamed, not duplicated"


def test_an_entry_over_breathe_leave_is_a_clash():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["entry"] is e
    assert cell["on_leave"] is True
    assert cell["clash"] is True
    assert cell["leave_label"] == "Holiday"
    assert cell["absence"] is None, "the chip shown is still the entry's"


def test_an_absence_entry_over_breathe_leave_agrees_and_is_not_a_clash():
    """An admin marking someone AL by hand when Breathe also says off is
    agreement, not a rostered session on a day off."""
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    e = make_entry(c, day=TUE, part="AM", session_type=al)
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["on_leave"] is True
    assert cell["clash"] is False
    assert cell["leave_label"] == "Holiday"


def test_an_entry_with_no_leave_is_not_a_clash():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["on_leave"] is False
    assert cell["clash"] is False
    assert cell["leave_label"] is None


def test_leave_with_no_entry_labels_but_is_not_a_clash():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["on_leave"] is True
    assert cell["clash"] is False
    assert cell["leave_label"] == "Holiday"
    assert cell["absence"] is not None


def test_an_unmapped_kind_still_labels():
    """The label never goes through the mapping. Deleting a mapping row
    empties the chip; it must not empty the tooltip or the warning."""
    BreatheLeaveMapping.objects.filter(kind="sickness").delete()
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [make_absence(c, TUE, kind="sickness")]),
                      closed=False)
    assert cell["absence"] is None
    assert cell["on_leave"] is True
    assert cell["leave_label"] == "Sick"


def test_a_clash_ignores_the_closed_flag():
    """An entry means someone is rostered, closed day or not."""
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=True)
    assert cell["clash"] is True
```

Add `from datetime import date, timedelta` at the top of the file (it currently imports only `date`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_cells.py -q`
Expected: the eight new tests FAIL — `ImportError: cannot import name 'leave_label'` for the module, then `KeyError: 'clash'` / `AttributeError: covering` once the import exists.

- [ ] **Step 3: Make `covering()` public in the resolver**

In `rota/services/availability.py`, rename `_covering` to `covering` and update its two callers. The method body is unchanged; the docstring gains one sentence:

```python
    def covering(self, clinician_id, day, part):
        """The (kind, reason) of the absence covering `day`/`part`, or None.
        The one place both leave_type() and on_leave() read the overlay, so
        they cannot disagree about which absence applies — only about
        whether it renders. Public because cell_state() labels the absence
        from it, entry or no entry."""
        for span, kind, reason in self._leave.get(clinician_id, ()):
            if part in parts_off(span, day):
                return kind, reason
        return None

    def leave_type(self, clinician_id, day, part):
        """...(docstring unchanged)..."""
        covering = self.covering(clinician_id, day, part)
        if covering is None:
            return None
        kind, reason = covering
        return self._mapping.get((kind, reason)) or self._mapping.get((kind, ""))

    def on_leave(self, clinician_id, day, part):
        """...(docstring unchanged)..."""
        return self.covering(clinician_id, day, part) is not None
```

Run `grep -rn "_covering" rota/ tests/` and confirm nothing else references the old name.

- [ ] **Step 4: Add `leave_label()` and the new keys to `cell_state()`**

Replace `rota/services/cells.py` with:

```python
"""What a rota cell shows, decided once.

    entry exists                -> the entry
    on leave and showable       -> the Breathe absence (`absence`, mapped)
    on leave, mapped or not     -> `on_leave`, entry or no entry
    entry AND on leave          -> `clash`, unless the entry is itself an absence
    works_on                    -> not off: here, nothing allocated
    otherwise                   -> off: not here

The week grid, the day view and My Schedule all render cells, and a second
copy of this would be a second answer to the question the availability
consolidation existed to give one answer to.
"""

from rota.models import SessionType


def leave_label(kind, reason):
    """The words for a Breathe absence — a tooltip, a warning line.

    Never goes through the mapping: an absence whose kind has lost its
    mapping row renders no chip, but it is still leave and still says which.
    Sickness carries no reason by construction (the type is health data and
    is never stored), so "Sick" is all it can ever say.
    """
    if kind == "holiday":
        return "Holiday"
    if kind == "sickness":
        return "Sick"
    if kind == "other":
        return f"Other leave: {reason}" if reason else "Other leave"
    return kind.capitalize()


def cell_state(clinician_id, day, part, *, entry, resolver, closed,
               partner=None):
    """One cell's state. Performs no queries — the caller prefetches."""
    works = resolver.works_on(clinician_id, day, part)
    covering = resolver.covering(clinician_id, day, part)
    # Two different questions, and they must not be answered by one value:
    # `absence` is what to *render* on an empty cell and goes through the
    # mapping, so a kind with no mapping row is None; `on_leave` is whether
    # Breathe says the clinician is off, never touches the mapping, and is
    # answered whether or not an entry stands on the cell. It used to be
    # forced False under an entry — which is exactly why a published
    # session over later-approved leave could not be marked anywhere.
    on_leave = covering is not None
    leave_type = resolver.leave_type(clinician_id, day, part) if entry is None else None

    # A rostered session on someone Breathe says is off. An absence-category
    # entry (an admin marking AL by hand) over Breathe leave is agreement,
    # not a clash.
    clash = (entry is not None and on_leave
             and entry.session_type.category != SessionType.Category.ABSENCE)

    # Show the absence only where it means something: on a session the
    # clinician works, or for a clinician with no pattern at all (nothing
    # would ever show for them otherwise). Showing it on every session a
    # leave span covers would put chips on every part-timer's days off —
    # a part-timer's day off must not read "AL" on a day they never work.
    #
    # Two things the "no pattern" clause must not skip:
    #  - the contractual window. `works` already carries the window; the
    #    no-pattern branch has to ask separately, or a chip would show for a
    #    week the clinician was never employed for.
    #  - a closed day. A bank holiday inside a leave range correctly has no
    #    entry, and a chip there is noise on every Christmas closure.
    no_pattern_here = (not resolver.has_pattern(clinician_id)
                       and resolver.in_service(clinician_id, day))
    showable = (works or no_pattern_here) and not closed

    return {
        "day": day,
        "day_str": day.isoformat(),
        "part": part,
        "entry": entry,
        "off": entry is None and not works,
        "absence": leave_type if showable else None,
        "on_leave": on_leave,
        "leave_label": leave_label(*covering) if covering else None,
        "clash": clash,
        "closed": closed,
        "partner": partner,
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_cells.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the whole suite**

Run: `/root/rota/.venv/bin/python -m pytest -q`
Expected: 888 passed. Nothing else should change: every existing consumer of `on_leave` (the day view's partition, My Schedule's `_is_leave_cell`) only ever read it on cells without an entry in the existing tests. If anything else fails, stop and report it — do not adjust the failing test.

- [ ] **Step 7: Commit**

```bash
git add rota/services/availability.py rota/services/cells.py tests/test_cells.py
git commit -m "feat: a cell knows it stands on Breathe leave, entry or not

cell_state forced on_leave False under an entry, so a published session
over later-approved leave could not be marked anywhere. It now answers
on_leave regardless, labels the absence (never via the mapping), and
reports a clash — unless the entry is itself an absence, which is
agreement. The resolver's covering() is public for it.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The clash warning names people and costs no queries per day

**Files:**
- Modify: `rota/services/warnings.py:24-57` and `:60-64`
- Modify: `rota/views/grid.py:69`
- Test: `tests/test_breathe_conflicts.py`

**Interfaces:**
- Consumes: `cell_state(...)["clash"]`, `["leave_label"]` from Task 1; `Clinician.initials`.
- Produces: `day_warnings(day, include_drafts=True, resolver=None)`; message format `On Breathe leave but rostered ({part}): {initials} ({label})[, ...]` with initials sorted; `Warning.code == "breathe"` unchanged.

- [ ] **Step 1: Re-point the existing assertions and write the new tests**

In `tests/test_breathe_conflicts.py`:

Change the module constant:

```python
TEXT = "On Breathe leave but rostered"
```

In `test_a_published_entry_over_a_full_day_absence_warns_for_both_parts`, the two message assertions become:

```python
    assert warnings[0].message == "On Breathe leave but rostered (AM): AA (Holiday)"
    assert warnings[1].message == "On Breathe leave but rostered (PM): AA (Holiday)"
```

In `test_the_warning_appears_in_the_admin_grids_day_header`:

```python
    assert "On Breathe leave but rostered (AM): AA (Holiday)" in html
```

Update the module docstring's last two sentences to: `The cell is marked and the header names who — see the spec. Non-admins see the cell, never the header line: judgement signals are the admin's.`

Append these tests (the file already imports `make_clinician`, `make_entry`, `make_pattern`, `make_absence`, `make_session_type`, `MON`, `PracticeSettings`, `BreatheLeaveMapping`, `day_warnings`, `date`, `timedelta`):

```python
def test_the_warning_names_everyone_in_initials_order():
    for name, kw in (("Bob Baker", {"kind": "sickness"}),
                     ("Ann Able", {})):
        c = make_clinician(name)
        make_pattern(c)
        make_entry(c, day=MON, part="AM",
                   session_type=make_session_type("Routine", code="ROUT"))
        make_absence(c, MON, **kw)
    (w,) = _breathe()
    assert w.message == "On Breathe leave but rostered (AM): AA (Holiday), BB (Sick)"


def test_an_absence_entry_over_breathe_leave_is_agreement_not_a_clash():
    """An admin marked AL by hand and Breathe agrees. Nothing to fix."""
    c = make_clinician("Ann Able")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=MON, part="AM", session_type=al)
    make_absence(c, MON)
    assert _breathe() == []


def test_an_unmapped_absence_still_names_its_kind():
    BreatheLeaveMapping.objects.filter(kind="holiday").delete()
    _rostered_on_leave()
    assert _breathe()[0].message.endswith("AA (Holiday)")


def test_the_conflict_check_adds_no_queries_per_open_day(admin_client):
    """The rule used to build its own resolver per day: three queries for
    every open day that had entries. The grid now hands over the resolver
    it already built. Measured as "a week with entries on one day costs the
    same as a week with entries on five" — no coverage rules exist here,
    so no other warning's query count depends on the data."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    PracticeSettings.load()
    rout = make_session_type("Routine", code="ROUT")
    people = [make_clinician(f"Doc {i}", initials=f"D{i}") for i in range(3)]
    for c in people:
        make_pattern(c)
        make_entry(c, day=MON, part="AM", session_type=rout)
        make_absence(c, MON, MON + timedelta(days=4))

    def queries():
        with CaptureQueriesContext(connection) as ctx:
            resp = admin_client.get(f"/rota/?week={MON.isoformat()}")
        assert resp.status_code == 200
        assert TEXT in resp.content.decode(), "the warning must be rendering"
        return len(ctx)

    queries()  # warm up
    one_day = queries()

    for c in people:
        for offset in range(1, 5):
            make_entry(c, day=MON + timedelta(days=offset), part="AM",
                       session_type=rout)
    assert queries() == one_day, (
        "the grid issues more queries when more open days carry entries — "
        "the Breathe rule is building a resolver per day again"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_breathe_conflicts.py -q`
Expected: the two re-pointed tests and the four new ones FAIL on the old message text and the query count (the last one fails with a count difference of 12).

- [ ] **Step 3: Rewrite `_breathe_conflicts` and thread the resolver**

In `rota/services/warnings.py`, add the import after the existing `AvailabilityResolver` import:

```python
from rota.services.cells import cell_state
```

Replace `_breathe_conflicts` entirely:

```python
def _breathe_conflicts(day, entries, resolver=None):
    """Rostered sessions standing on a clinician Breathe says is off.

    Leave used to be approved in the rota, and approving it overwrote the
    entries. Breathe owns leave now and nothing overwrites anything, so the
    ordinary sequence — publish the week, then leave is approved in Breathe
    — leaves a published session against someone who is not coming in. The
    cell is ringed (cell_state's `clash`) and this line names who, with the
    kind of leave, so an admin can clear the session by hand.

    Decided by cell_state, so the header and the cell cannot disagree: an
    absence-category entry over Breathe leave is agreement, and an absence
    whose (kind, reason) has no mapping row is still leave.

    `resolver` is optional so the grid, which has already built one for the
    week, need not pay for another per day. Built here only for callers
    that have none.
    """
    if not entries:
        return []
    if resolver is None:
        clinicians = {e.clinician_id: e.clinician for e in entries}
        resolver = AvailabilityResolver(
            PatternSlot.objects.filter(clinician_id__in=clinicians),
            clinicians.values(),
            BreatheAbsence.objects.filter(clinician_id__in=clinicians,
                                          start_date__lte=day, end_date__gte=day),
            BreatheLeaveMapping.as_dict(),
        )
    warnings = []
    for part in ["AM", "PM"]:
        clashing = {}
        for e in entries:
            if e.part != part:
                continue
            cell = cell_state(e.clinician_id, day, part, entry=e,
                              resolver=resolver, closed=False)
            if cell["clash"]:
                clashing[e.clinician.initials] = cell["leave_label"]
        if clashing:
            who = ", ".join(f"{initials} ({label})"
                            for initials, label in sorted(clashing.items()))
            warnings.append(Warning(
                "breathe", part, f"On Breathe leave but rostered ({part}): {who}"))
    return warnings
```

Change the signature and the last call in `day_warnings`:

```python
def day_warnings(day, include_drafts=True, resolver=None):
    ...
    warnings.extend(_breathe_conflicts(day, entries, resolver))
    return warnings
```

In `rota/views/grid.py`, the `day_headers` comprehension (currently `"warnings": day_warnings(d, include_drafts=is_admin) if is_admin else []`) becomes:

```python
         "warnings": (day_warnings(d, include_drafts=is_admin, resolver=resolver)
                      if is_admin else [])}
```

`resolver` is already defined a few lines above `day_headers` in that function.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_breathe_conflicts.py tests/test_warnings.py tests/test_grid_rendering.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite, then commit**

Run: `/root/rota/.venv/bin/python -m pytest -q` — expected 892 passed.

```bash
git add rota/services/warnings.py rota/views/grid.py tests/test_breathe_conflicts.py
git commit -m "feat: the clash warning names who, with their kind of leave

\"1 rostered on Breathe leave (AM)\" becomes \"On Breathe leave but rostered
(AM): TH (Holiday), JS (Sick)\". Decided by cell_state, so the header and
the cell cannot disagree. The grid hands over its week resolver, which
removes the three queries the rule cost per open day.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The cell marks a clash, and every Breathe chip says which leave

**Files:**
- Modify: `templates/rota/grid.html:44-61`
- Modify: `templates/rota/day.html:44-58` and `:78-92`
- Modify: `templates/rota/my_schedule.html:42-54` and `:70-91`
- Modify: `static/css/components.css:337-370`
- Modify: `docs/admin/breathe.md:41-44`
- Test: `tests/test_grid_rendering.py`, `tests/test_day_view.py`, `tests/test_my_schedule_weeks.py`, `tests/test_css_cascade.py`

**Interfaces:**
- Consumes: `cell.clash`, `cell.leave_label` from Task 1.
- Produces: chip class `is-clash`; absence chip title `{label} — from Breathe`; grid `<td>` title suffix ` — On Breathe leave: {label}`.

- [ ] **Step 1: Re-point the ten existing `From Breathe` references**

Every one of these referenced the literal `title="From Breathe"`, which no longer exists after this task. Each is re-pointed at the new text — none is removed.

`tests/test_grid_rendering.py`:

- Line 58 (docstring inside `_chips`): change `title="From Breathe"` to `a title ending "— from Breathe"`.
- Line 64: `if not classes and "from Breathe" in m["rest"]:`
- Line 117 (`test_approved_leave_ghosts_on_a_session_the_clinician_works`): `assert 'title="Holiday — from Breathe"' in html`
- Line 131 (`test_a_part_timer_gets_no_ghost...`): `n = html.count("from Breathe")`
- Line 159 (`test_a_clinician_with_no_pattern_at_all_gets_ghosts`): `assert 'title="Holiday — from Breathe"' in html`
- Line 170 (`test_a_real_entry_beats_a_ghost`): the entry there is absence-category, so it is not a clash either. Replace the single assertion with:

```python
    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "", (
        "the AL entry renders as a plain published chip — not the Breathe "
        "absence chip, and not ringed as a clash: an absence entry over "
        "Breathe leave is agreement"
    )
    assert "On Breathe leave" not in html
```

- Line 249 (`test_a_clinician_with_no_pattern_gets_no_ghosts_outside_their_window`): `n = html.count("from Breathe")`
- Line 344 (`test_the_grid_query_count_does_not_grow...`): `assert "from Breathe" in admin_client.get(`

`tests/test_my_schedule_weeks.py:364`: `assert 'title="Holiday — from Breathe"' in html`

`tests/test_day_view.py:133`: `assert "from Breathe" in _on_leave_tbody(html)`; `:187`: `assert "from Breathe" in _roster_tbody(html)`

- [ ] **Step 2: Write the new tests**

Append to `tests/test_grid_rendering.py`:

```python
# ------------------------------------------------------------- clashes ---


def _rostered_on_leave(name, initials, **absence_kw):
    c = make_clinician(name, initials=initials)
    _pattern(c, 0, "AM")
    make_entry(c, day=MON, part="AM",
               session_type=make_session_type("Routine", code="ROUT"),
               **{k: v for k, v in absence_kw.items() if k == "is_published"})
    make_absence(c, MON, **{k: v for k, v in absence_kw.items() if k != "is_published"})
    return c


@pytest.mark.django_db
def test_a_rostered_session_over_breathe_leave_is_ringed_for_everyone(
        admin_client, gp_client):
    """Tom's decision: the marker and the kind of leave are for every user
    who can see the cell. The header line stays admin-only."""
    c = _rostered_on_leave("Clash", "CL")
    for client in (admin_client, gp_client):
        html = _cells(client)
        assert "is-clash" in _chips(html)[(c.id, _iso(0), "AM")] if client is admin_client \
            else 'class="chip is-clash"' in html
        assert "On Breathe leave: Holiday" in html


@pytest.mark.django_db
def test_a_draft_clash_is_invisible_to_a_gp(admin_client, gp_client):
    c = _rostered_on_leave("Draft", "DR", is_published=False)
    assert "is-clash" in _chips(_cells(admin_client))[(c.id, _iso(0), "AM")]
    gp_html = _cells(gp_client)
    assert "is-clash" not in gp_html
    assert "On Breathe leave" not in gp_html


@pytest.mark.django_db
def test_the_absence_tooltip_names_the_kind_and_reason(admin_client):
    for name, initials, kw in (
            ("Holly Day", "HD", {}),
            ("Sid Sick", "SS", {"kind": "sickness"}),
            ("Jo Jury", "JJ", {"kind": "other", "reason": "Jury service"})):
        c = make_clinician(name, initials=initials)
        _pattern(c, 0, "AM")
        make_absence(c, MON, **kw)
    html = _cells(admin_client)
    assert 'title="Holiday — from Breathe"' in html
    assert 'title="Sick — from Breathe"' in html
    assert 'title="Other leave: Jury service — from Breathe"' in html
```

The non-admin grid carries no per-cell `hx-get`, so `_chips()` cannot address a GP's cells; the GP branch above asserts on the rendered class attribute instead. Keep it that way — do not add `hx-get` for non-admins.

Append to `tests/test_day_view.py`:

```python
def test_a_clash_files_under_on_leave_with_the_marker(gp_client, gp_user):
    """Breathe says they are off, so the section says so; the ringed chip
    is what makes the session the visible anomaly."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Cara Clash")
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=rout)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    make_absence(c, TUE)
    html = _html(gp_client)
    leave = _on_leave_tbody(html)
    assert "Cara Clash" in leave
    assert "is-clash" in leave
    assert "On Breathe leave: Holiday" in leave
    assert "0 in &middot; 1 on leave" in html
```

Append to `tests/test_css_cascade.py`:

```python
def test_the_clash_ring_is_an_inset_danger_shadow():
    """A ring rather than a background: the tint underneath and the draft
    hatch both still have to read."""
    rules = [r for r in RULES if r.selector == ".chip.is-clash" and r.media is None]
    assert rules, ".chip.is-clash has no rule"
    shadow = rules[-1].declarations.get("box-shadow", "")
    assert "inset" in shadow and "var(--danger)" in shadow, shadow
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py -q`
Expected: the re-pointed tests FAIL (old title still rendered), the new ones FAIL.

- [ ] **Step 4: Change the templates**

`templates/rota/grid.html` — the `<td>` and its two chip branches (lines 44-61) become:

```html
  <td {% if cell.merged %}colspan="2"{% endif %}
      class="{% if cell.entry and not cell.entry.is_published %}draft{% endif %}{% if cell.closed %} closed{% endif %}"
      {% if is_admin %}hx-get="/rota/cell/{{ row.clinician.id }}/{{ cell.day_str }}/{{ cell.part }}/"
      hx-target="#modal"{% endif %}
      title="{{ cell.entry.fill_reason|default:'' }} {{ cell.entry.note|default:'' }}{% if cell.partner %} with {{ cell.partner }}{% endif %}{% if cell.clash %}{% if cell.entry.fill_reason or cell.entry.note or cell.partner %} — {% endif %}On Breathe leave: {{ cell.leave_label }}{% endif %}">
    {% if cell.entry %}
      <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}{% if cell.clash %} is-clash{% endif %}"
            style="--chip-bg: var(--tint-{{ cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.entry.session_type.tint.key }}-fg);">
        {{ cell.entry.session_type.code }}{% if cell.entry.site %}<span class="site-marker">{{ cell.entry.site.name|slice:":1" }}</span>{% endif %}
      </span>
    {% elif cell.absence %}
      <span class="chip" title="{{ cell.leave_label }} — from Breathe"
            style="--chip-bg: var(--tint-{{ cell.absence.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.absence.tint.key }}-fg);">
        {{ cell.absence.code }}
      </span>
```

`templates/rota/day.html` — in **both** the roster table and the on-leave table, the entry chip and the absence chip become (the on-leave table's entry chip has no site marker today; keep that difference):

```html
          {% if cell.entry %}
            <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}{% if cell.clash %} is-clash{% endif %}"
                  {% if cell.clash %}title="On Breathe leave: {{ cell.leave_label }}"{% endif %}
                  style="--chip-bg: var(--tint-{{ cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.entry.session_type.tint.key }}-fg);">
              ...(the existing chip body, unchanged)...
            </span>
            ...(the existing partner span in the roster table, unchanged)...
          {% elif cell.absence %}
            <span class="chip" title="{{ cell.leave_label }} — from Breathe"
                  style="--chip-bg: var(--tint-{{ cell.absence.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.absence.tint.key }}-fg);">
              {{ cell.absence.code }}
            </span>
```

The pinned block iterates entries, not cells, and has no clash information; leave it unchanged.

`templates/rota/my_schedule.html` — the today cells (one loop) and the week rows (`row.am_cell` and `row.pm_cell`, two blocks): entry chips gain `{% if cell.clash %} is-clash{% endif %}` (substituting `row.am_cell` / `row.pm_cell` for `cell`) and a `title="On Breathe leave: {{ ....leave_label }}"` when clashing; absence chips' `title="From Breathe"` becomes `title="{{ ....leave_label }} — from Breathe"`. Three absence sites, three entry sites.

- [ ] **Step 5: Add the ring**

In `static/css/components.css`, after the `.chip.is-draft` rule (line ~370):

```css
/* A session rostered on someone Breathe says is off. An inset ring rather
   than a background change: the tint under it still has to read, and the
   draft hatch may be there too. --danger holds AA on every ground in both
   themes (tests/test_chrome_contrast.py). */
.chip.is-clash {
  box-shadow: inset 0 0 0 2px var(--danger);
}
```

- [ ] **Step 6: Update the doc**

In `docs/admin/breathe.md`, replace the paragraph beginning `**A week already published keeps its sessions.**` with:

```markdown
**A week already published keeps its sessions.** Nothing in the rota overwrites
a session when leave is approved in Breathe afterwards. Instead the cell is
ringed in red, its tooltip says "On Breathe leave: Holiday", and the day's
header names who — "On Breathe leave but rostered (AM): TH (Holiday)". The
ring and tooltip are visible to everyone who can see the session; the header
line is for admins, who clear the session by hand. On the day view and on My
Schedule the clinician files under "On leave", with the ringed session still
shown.

Every Breathe chip's tooltip names the kind of leave — "Holiday — from
Breathe", "Sick — from Breathe", "Other leave: Jury service — from Breathe".
The reason on "other" leave is whatever Breathe recorded; sickness never
carries one.
```

- [ ] **Step 7: Run the tests, then the suite, then commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py tests/test_chrome_contrast.py tests/test_template_hygiene.py -q` — expected all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — expected 897 passed.

```bash
git add templates/rota/grid.html templates/rota/day.html templates/rota/my_schedule.html static/css/components.css docs/admin/breathe.md tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py
git commit -m "feat: a clash rings the cell, and every Breathe chip says which leave

An inset --danger ring on a session rostered over Breathe leave, with
\"On Breathe leave: Holiday\" in the tooltip, for everyone who can see the
cell. Absence chips' tooltips read \"Holiday — from Breathe\", \"Sick — from
Breathe\", \"Other leave: Jury service — from Breathe\" — the reason Breathe
recorded, which nothing showed before.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: My Schedule does not style a closed day as leave

**Files:**
- Modify: `rota/views/my_schedule.py:63-66`
- Test: `tests/test_my_schedule_weeks.py`

**Interfaces:**
- Consumes: `cell_state(...)["on_leave"]`, now `True` under an entry (Task 1).
- Produces: nothing new; `row["is_leave"]` is `False` on any non-open day.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_my_schedule_weeks.py`:

```python
def test_a_closed_day_with_a_session_is_never_styled_as_leave(gp_client, gp_user):
    """A bank holiday inside a leave span, with a published session left on
    it: the row shows (a real session beats the closure) but must not take
    the leave style — that decision belongs to open days, the same guard
    today_state already applies. Before this, `on_leave` under an entry
    made the row read as a day off."""
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    make_entry(c, day=victim, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    make_absence(c, monday, monday + timedelta(days=4))
    rows = {d["day"]: d for d in _ctx(gp_client)["weeks"][0]["days"]}
    assert victim in rows, "a closed day with a session is still shown"
    assert rows[victim]["is_leave"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_my_schedule_weeks.py -q -k closed_day_with_a_session`
Expected: FAIL — `is_leave` is `True`.

- [ ] **Step 3: Guard the row**

In `rota/views/my_schedule.py`, inside `_blocks()`, the two lines

```python
            worked_cells = [c for c in (am_cell, pm_cell) if not c["off"]]
            is_leave = bool(worked_cells) and all(
                _is_leave_cell(c) for c in worked_cells)
```

become

```python
            worked_cells = [c for c in (am_cell, pm_cell) if not c["off"]]
            # `is_open and`: the same guard today_state applies. A closed day
            # is shown here only because a session is on it, and a session
            # is not a day off — whatever Breathe says about the date.
            is_leave = is_open and bool(worked_cells) and all(
                _is_leave_cell(c) for c in worked_cells)
```

- [ ] **Step 4: Run the file, then the suite, then commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_my_schedule_weeks.py tests/test_my_schedule.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 898 passed.

```bash
git add rota/views/my_schedule.py tests/test_my_schedule_weeks.py
git commit -m "fix: My Schedule never styles a closed day as leave

_blocks() lacked the is_open guard today_state already had; with
on_leave now answered under an entry, a bank holiday carrying a stray
session took the leave style.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Notes get a visible marker, and the phone screens print them

**Files:**
- Modify: `templates/rota/grid.html` (entry chip), `templates/rota/day.html` (pinned block, roster, on-leave table), `templates/rota/my_schedule.html` (today cells, week rows)
- Modify: `static/css/components.css:337-352` (`.chip`), new rule after `.chip.is-clash`
- Modify: `static/css/screens.css:139-146` (`.ms-today-cells`), `:194` (`.ms-cells` area), `:276-280` (`.day-partner`)
- Test: `tests/test_grid_rendering.py`, `tests/test_day_view.py`, `tests/test_my_schedule_weeks.py`, `tests/test_css_cascade.py`, `tests/test_day_view_css.py`

**Interfaces:**
- Consumes: `entry.note`.
- Produces: chip class `has-note`; `.day-note-text` span; `.ms-note` span.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_grid_rendering.py`:

```python
# --------------------------------------------------------------- notes ---


@pytest.mark.django_db
def test_a_note_marks_its_chip_and_a_fill_reason_alone_does_not(admin_client):
    """A note is something a person wrote; fill_reason is the engine's
    diagnostic. Only the first earns a dot."""
    rout = make_session_type("Routine", code="ROUT")
    noted = make_clinician("Noted", initials="NT")
    _pattern(noted, 0, "AM")
    make_entry(noted, day=MON, part="AM", session_type=rout, note="Bring the laptop")
    plain = make_clinician("Plain", initials="PL")
    _pattern(plain, 0, "AM")
    make_entry(plain, day=MON, part="AM", session_type=rout, fill_reason="default fill")
    chips = _chips(_cells(admin_client))
    assert "has-note" in chips[(noted.id, _iso(0), "AM")]
    assert "has-note" not in chips[(plain.id, _iso(0), "AM")]
```

Append to `tests/test_day_view.py`:

```python
def test_a_note_is_printed_under_the_chip(gp_client, gp_user):
    """No hover on a phone, and the day view is the phone screen."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nora Note")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM", note="Bring the laptop",
               session_type=make_session_type("Routine", code="ROUT"))
    roster = _roster_tbody(_html(gp_client))
    assert "has-note" in roster
    assert 'class="day-note-text">Bring the laptop<' in roster
```

Append to `tests/test_my_schedule_weeks.py`:

```python
def test_a_note_is_printed_in_the_week_row_and_the_today_box(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    make_entry(c, day=date.today(), part="AM", note="Bring the laptop",
               session_type=make_session_type("Routine", code="ROUT"))
    PracticeSettings.load()
    html = gp_client.get("/me/").content.decode()
    assert html.count("has-note") == 2, "the today box and the week row"
    assert html.count('class="ms-note">AM — Bring the laptop<') == 2
```

Append to `tests/test_css_cascade.py`:

```python
def test_the_note_marker_is_a_positioned_dot_in_the_chips_own_colour():
    chip = [r for r in RULES if r.selector == ".chip" and r.media is None]
    assert chip and chip[-1].declarations.get("position") == "relative", (
        ".chip is not positioned, so the marker's absolute position is "
        "relative to something else entirely"
    )
    dot = [r for r in RULES if r.selector == ".chip.has-note::after" and r.media is None]
    assert dot, ".chip.has-note::after has no rule"
    d = dot[-1].declarations
    assert d.get("content") is not None
    assert d.get("position") == "absolute"
    assert "var(--chip-fg" in d.get("background", ""), (
        "the dot must take the cell's own foreground so it holds on every tint"
    )


def test_the_today_box_wraps_so_a_note_can_take_its_own_line():
    rules = [r for r in RULES if r.selector == ".ms-today-cells" and r.media is None]
    assert any(r.declarations.get("flex-wrap") == "wrap" for r in rules)
    note = [r for r in RULES if r.selector == ".ms-today-cells .ms-note" and r.media is None]
    assert note and note[-1].declarations.get("color") == "var(--ink-soft)", (
        "--muted fails AA on the today box's --accent-soft ground; the note "
        "there needs its own foreground, as .ms-today-cells .ms-dash has"
    )
```

In `tests/test_day_view_css.py::test_every_class_the_template_uses_is_styled`, add `".day-note-text"` to the tuple.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py tests/test_day_view_css.py -q`
Expected: the six new/changed tests FAIL.

- [ ] **Step 3: Templates**

`templates/rota/grid.html` — the entry chip's class attribute becomes:

```html
      <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}{% if cell.clash %} is-clash{% endif %}{% if cell.entry.note %} has-note{% endif %}"
```

`templates/rota/day.html`:

- Pinned block: `<span class="chip{% if not e.is_published %} is-draft{% endif %}{% if e.note %} has-note{% endif %}"`. Marker only — the row is a compact flex line, and the same entry prints its text in the roster below.
- Roster table and on-leave table: entry chips gain `{% if cell.entry.note %} has-note{% endif %}`, and immediately after each entry chip's closing `</span>` (in the roster table, after the partner span) add:

```html
            {% if cell.entry.note %}<span class="day-note-text">{{ cell.entry.note }}</span>{% endif %}
```

`templates/rota/my_schedule.html`:

- Today cells: the entry chip gains `{% if cell.entry.note %} has-note{% endif %}`. After the `{% endfor %}` that closes the today loop, still inside `<div class="ms-today-cells">`, add:

```html
      {% for cell in today_cells %}{% if cell.entry.note %}<span class="ms-note">{{ cell.part }} — {{ cell.entry.note }}</span>{% endif %}{% endfor %}
```

- Week rows: `row.am_cell` and `row.pm_cell` entry chips gain `{% if row.am_cell.entry.note %} has-note{% endif %}` (and `pm`). After the PM branch's `{% endif %}`, still inside `<span class="ms-cells">`, add:

```html
        {% if row.am_cell.entry.note %}<span class="ms-note">AM — {{ row.am_cell.entry.note }}</span>{% endif %}
        {% if row.pm_cell.entry.note %}<span class="ms-note">PM — {{ row.pm_cell.entry.note }}</span>{% endif %}
```

- [ ] **Step 4: CSS**

`static/css/components.css` — add `position: relative;` as the first declaration of the existing `.chip` rule, then after `.chip.is-clash` add:

```css
/* A note on the entry. A corner dot rather than a glyph: the chip clips
   its overflow with an ellipsis, so a glyph would be the first thing lost
   on a narrow column. --chip-fg is the cell's own foreground, set per cell
   by the template, so the dot holds on every tint in both themes with no
   new token. */
.chip.has-note::after {
  content: "";
  position: absolute;
  top: 3px;
  right: 3px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--chip-fg, var(--muted));
}
```

`static/css/screens.css`:

- `.ms-today-cells { display: flex; gap: var(--sp-2); align-items: center; }` gains `flex-wrap: wrap;`.
- After the `.ms-today-cells .ms-dash` rule add:

```css
/* The note under a chip. flex-basis: 100% drops it onto its own line
   beneath the two chips, aligned with the cells column rather than the
   date. Inside the today box the ground is --accent-soft, where --muted
   fails AA — the same reason .ms-today-cells .ms-dash takes --ink-soft. */
.ms-note { flex-basis: 100%; color: var(--muted); font-size: var(--fs-xs); }
.ms-today-cells .ms-note { color: var(--ink-soft); }
```

- The `.day-partner` rule's selector becomes `.day-partner, .day-note-text` (declarations unchanged).

- [ ] **Step 5: Run the tests, then the suite, then commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py tests/test_day_view_css.py tests/test_chrome_contrast.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 903 passed.

```bash
git add templates/rota/grid.html templates/rota/day.html templates/rota/my_schedule.html static/css/components.css static/css/screens.css tests/test_grid_rendering.py tests/test_day_view.py tests/test_my_schedule_weeks.py tests/test_css_cascade.py tests/test_day_view_css.py
git commit -m "feat: a note shows as a dot on the chip, and in full on the phone screens

Notes reached the grid only as a hover title. A corner dot in the cell's
own foreground says one exists; the day view and My Schedule — the
screens a phone reads — print the text beneath the chip.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `LocumRequirement` gains a status and a covering clinician

**Files:**
- Modify: `rota/models/requests.py:7-33`
- Create: `rota/migrations/0024_locum_status_and_covering.py` (generated)
- Modify: `rota/admin.py:462-465`
- Test: `tests/test_locums.py`

**Interfaces:**
- Produces: `LocumRequirement.Status.APPROVED == "APPROVED"` (label `Need approved`), ordered second; `LocumRequirement.covering: Clinician | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_locums.py`:

```python
def test_the_statuses_run_possible_approved_advertised_booked():
    S = LocumRequirement.Status
    assert [s.value for s in S] == ["POSSIBLE", "APPROVED", "ADVERTISED", "BOOKED"]
    assert S.APPROVED.label == "Need approved"


def test_covering_is_an_optional_clinician_that_survives_deletion():
    field = LocumRequirement._meta.get_field("covering")
    assert field.null and field.blank
    assert field.remote_field.model.__name__ == "Clinician"
    from django.db import models
    assert field.remote_field.on_delete is models.SET_NULL
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_locums.py -q -k "statuses or covering_is"`
Expected: FAIL.

- [ ] **Step 3: Change the model**

In `rota/models/requests.py`, `LocumRequirement` becomes:

```python
class LocumRequirement(models.Model):
    class Status(models.TextChoices):
        POSSIBLE = "POSSIBLE", "Possibly needed"
        # Approval to seek a locum, before advertising — Tom, 2026-09-03.
        # The value stays inside max_length=10.
        APPROVED = "APPROVED", "Need approved"
        ADVERTISED = "ADVERTISED", "Advertised"
        BOOKED = "BOOKED", "Booked"

    day = models.DateField()
    part = models.CharField(max_length=2, choices=Part.choices)
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.POSSIBLE
    )
    details = models.TextField(blank=True)
    clinician = models.ForeignKey(
        "rota.Clinician", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locum_bookings",
    )
    covering = models.ForeignKey(
        "rota.Clinician", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="The clinician this locum stands in for.",
    )
    rota_entry = models.OneToOneField(
        "rota.RotaEntry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locum_requirement",
    )
```

`__str__` and `Meta` are unchanged.

- [ ] **Step 4: Generate the migration**

Run: `/root/rota/.venv/bin/python manage.py makemigrations rota -n locum_status_and_covering`
Expected: `rota/migrations/0024_locum_status_and_covering.py` with one `AddField` (covering) and one `AlterField` (status). Open it and confirm exactly those two operations. Then:

Run: `/root/rota/.venv/bin/python manage.py makemigrations --check` — expected `No changes detected`.

- [ ] **Step 5: Admin**

In `rota/admin.py`, `LocumRequirementAdmin.list_display` becomes `("day", "part", "session_type", "status", "clinician", "covering")`.

- [ ] **Step 6: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_locums.py tests/test_admin*.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 905 passed.

```bash
git add rota/models/requests.py rota/migrations/0024_locum_status_and_covering.py rota/admin.py tests/test_locums.py
git commit -m "feat: a locum requirement can need approval, and can say who it covers

Status gains APPROVED (\"Need approved\") between Possibly needed and
Advertised; a nullable covering FK names the clinician the locum stands
in for. One migration for both.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The new status has a badge, a warning suffix and a place in the form

**Files:**
- Modify: `static/css/components.css:384-386`
- Modify: `docs/admin/day-to-day.md:89-106`
- Test: `tests/test_css_cascade.py`, `tests/test_warnings.py`, `tests/test_edit_views.py`

**Interfaces:**
- Consumes: `LocumRequirement.Status.APPROVED` (Task 6).
- Produces: `.badge.APPROVED` rule.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_css_cascade.py`:

```python
def test_the_approved_badge_is_an_amber_outline():
    """Progress in one colour family: red = possibly needed, amber outline
    = need approved, amber filled = advertised, green = booked. Not a
    fourth hue, because --accent and --ok are the same green in dark mode
    and any green-ish choice would read as booked."""
    rules = [r for r in RULES if r.selector == ".badge.APPROVED" and r.media is None]
    assert rules, ".badge.APPROVED has no rule"
    d = rules[-1].declarations
    assert d.get("background") == "transparent"
    assert "var(--warning)" in d.get("box-shadow", "") and "inset" in d.get("box-shadow", "")
    assert d.get("color") == "var(--warning)"
```

Append to `tests/test_warnings.py`:

```python
def test_a_need_approved_locum_is_named_in_the_suffix(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    LocumRequirement.objects.create(
        day=MON, part="PM", session_type=duty_rule,
        status=LocumRequirement.Status.APPROVED,
    )
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert any(w.message.endswith("— locum need approved") for w in warnings)
```

Append to `tests/test_edit_views.py`:

```python
def test_the_locum_form_lists_the_four_statuses_in_order(admin_client):
    make_session_type()
    html = admin_client.get(f"/rota/locum/new/?day={MON.isoformat()}&part=AM").content.decode()
    labels = ["Possibly needed", "Need approved", "Advertised", "Booked"]
    positions = [html.index(label) for label in labels]
    assert positions == sorted(positions), labels
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_css_cascade.py tests/test_warnings.py tests/test_edit_views.py -q -k "approved"`
Expected: the CSS test FAILS; the other two PASS already (the enum and `get_status_display()` do the work) — keep them, they pin the behaviour.

- [ ] **Step 3: The badge rule**

In `static/css/components.css`, the three badge status rules become four, in status order:

```css
.badge.POSSIBLE   { background: var(--danger-soft);  color: var(--danger); }
/* Outline, not a fourth hue: --accent and --ok are one green in dark mode,
   so any green-ish "approved" would read as booked. Same family as
   Advertised, one step less filled. */
.badge.APPROVED   { background: transparent; box-shadow: inset 0 0 0 1px var(--warning); color: var(--warning); }
.badge.ADVERTISED { background: var(--warning-soft); color: var(--warning); }
.badge.BOOKED     { background: var(--ok-soft);      color: var(--ok); }
```

- [ ] **Step 4: The doc**

In `docs/admin/day-to-day.md`, under `## Locum requirements`, replace `**Possibly needed → Advertised → Booked.**` and the sentence before it with:

```markdown
`/admin/rota/locumrequirement/` — tracks a gap you are trying to fill
externally, through four states:

**Possibly needed → Need approved → Advertised → Booked.**

The badge colour follows: red, amber outline, amber, green. "Need approved"
is approval to seek a locum, before anyone advertises.
```

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_css_cascade.py tests/test_warnings.py tests/test_edit_views.py tests/test_chrome_contrast.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 908 passed.

```bash
git add static/css/components.css docs/admin/day-to-day.md tests/test_css_cascade.py tests/test_warnings.py tests/test_edit_views.py
git commit -m "feat: the Need approved badge — an amber outline between red and amber

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The locum form records who the locum covers

**Files:**
- Modify: `rota/services/locums.py`
- Modify: `rota/views/edit.py:118-175`
- Modify: `rota/views/grid.py:106`
- Modify: `templates/rota/_locum_form.html`
- Modify: `templates/rota/grid.html:76-78`
- Modify: `docs/admin/day-to-day.md:99-102`
- Test: `tests/test_locums.py`, `tests/test_edit_views.py`, `tests/test_grid_view.py`

**Interfaces:**
- Consumes: `LocumRequirement.covering` (Task 6).
- Produces: `save_requirement(actor, *, pk=None, day, part, session_type, status, details="", clinician=None, covering=None)`; POST field `covering_id`; context key `coverable`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_locums.py`:

```python
def test_covering_is_saved_and_refuses_a_locum(admin_user):
    st = make_session_type("Routine")
    covered = make_clinician("Cara Covered")
    req = locums.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.POSSIBLE, covering=covered,
    )
    assert req.covering == covered
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    a_locum = make_clinician("Larry Locum", group=locum_group)
    with pytest.raises(ValueError, match="outside the locum group"):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
            status=LocumRequirement.Status.POSSIBLE, covering=a_locum,
        )


def test_a_booking_note_names_who_is_covered(admin_user):
    st = make_session_type("Routine")
    covered = make_clinician("Cara Covered")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    locum = make_clinician("Larry Locum", group=locum_group)
    locums.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, clinician=locum,
        covering=covered, details="£700",
    )
    assert RotaEntry.objects.get().note == "Covering Cara Covered. £700"


def test_a_booking_without_covering_keeps_the_plain_note(admin_user):
    st, locum, req = _book(admin_user)
    assert RotaEntry.objects.get().note == "£700"
```

Append to `tests/test_edit_views.py`:

```python
def test_locum_save_records_covering(admin_client):
    st = make_session_type()
    covered = make_clinician("Cara Covered")
    admin_client.post("/rota/locum/save/", {
        "day": MON.isoformat(), "part": "AM", "session_type_id": st.id,
        "status": "APPROVED", "covering_id": covered.id})
    assert LocumRequirement.objects.get().covering == covered


def test_the_covering_dropdown_offers_no_locums(admin_client):
    make_session_type()
    make_clinician("Cara Covered")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Larry Locum", group=locum_group)
    html = admin_client.get(f"/rota/locum/new/?day={MON.isoformat()}&part=AM").content.decode()
    covering = html[html.index('id="id_covering_id"'):html.index("</select>", html.index('id="id_covering_id"'))]
    assert "Cara Covered" in covering
    assert "Larry Locum" not in covering
```

Append to `tests/test_grid_view.py` (the file already imports `LocumRequirement`, `make_group`, `make_session_type`, `PracticeSettings`, `MON`, `URL`; add `make_clinician` to its factories import):

```python
def test_the_badge_tooltip_says_who_is_covered(admin_client):
    PracticeSettings.load()
    make_group("Locum", is_locum_group=True, display_order=99)
    covered = make_clinician("Cara Covered")
    LocumRequirement.objects.create(
        day=MON, part="AM", session_type=make_session_type("Routine"),
        status=LocumRequirement.Status.ADVERTISED, covering=covered,
        details="agency emailed",
    )
    html = admin_client.get(URL).content.decode()
    assert 'title="Covering Cara Covered — agency emailed"' in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_locums.py tests/test_edit_views.py tests/test_grid_view.py -q -k "covering or covered"`
Expected: FAIL (`TypeError: unexpected keyword argument 'covering'`, missing markup).

- [ ] **Step 3: The service**

`rota/services/locums.py` becomes:

```python
from django.db import transaction

from rota.models import LocumRequirement
from rota.services import entries


@transaction.atomic
def save_requirement(actor, *, pk=None, day, part, session_type, status,
                     details="", clinician=None, covering=None):
    if covering is not None and covering.group.is_locum_group:
        raise ValueError("Covering must be a clinician outside the locum group.")
    if pk:
        req = LocumRequirement.objects.get(pk=pk)
        if req.status == LocumRequirement.Status.BOOKED and req.rota_entry_id is not None and (
            status != LocumRequirement.Status.BOOKED
            or (clinician is not None and clinician != req.clinician)
            or day != req.day
            or part != req.part
            or session_type != req.session_type
        ):
            raise ValueError(
                "Already booked — clear the booked session on the grid and "
                "start a new requirement instead."
            )
    else:
        req = LocumRequirement(day=day, part=part)
    req.day, req.part = day, part
    req.session_type = session_type
    req.details = details
    req.covering = covering
    if (status == LocumRequirement.Status.BOOKED
            and (req.status != LocumRequirement.Status.BOOKED
                 or req.rota_entry_id is None)):
        if clinician is None or not clinician.group.is_locum_group:
            raise ValueError("Booking requires a clinician in the locum group.")
        # The note is what the grid cell shows on hover and what lights the
        # note marker, so it says who the locum stands in for.
        note = details
        if covering is not None:
            note = f"Covering {covering.name}. {details}".rstrip()
        entry = entries.assign(
            actor, clinician, day, part, session_type,
            note=note[:200], published=True, manually_set=True,
        )
        req.clinician = clinician
        req.rota_entry = entry
    req.status = status
    req.save()
    return req
```

- [ ] **Step 4: The view and form**

In `rota/views/edit.py`, `_locum_form_context` gains a key:

```python
        "coverable": Clinician.objects.filter(
            active=True, group__is_locum_group=False).order_by("name"),
```

In `locum_save`, after the `clinician = ...` lookup add:

```python
    covering = Clinician.objects.filter(
        pk=request.POST.get("covering_id") or None).first()
```

and pass `covering=covering,` to `save_requirement` after `clinician=clinician,`.

In `templates/rota/_locum_form.html`, insert before the Details field:

```html
    <div class="field">
      <label for="id_covering_id">Covering for</label>
      <select name="covering_id" id="id_covering_id"><option value="">—</option>
        {% for c in coverable %}
        <option value="{{ c.id }}" {% if req.covering_id == c.id %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
      </select>
    </div>
```

- [ ] **Step 5: The badge tooltip**

In `rota/views/grid.py`, the requirements query becomes `LocumRequirement.objects.filter(day__in=days).select_related("session_type", "covering")`.

In `templates/rota/grid.html`, the badge's `title="{{ r.details }}"` becomes:

```html
          title="{% if r.covering %}Covering {{ r.covering.name }}{% if r.details %} — {% endif %}{% endif %}{{ r.details }}">{{ r.get_status_display }}</span>
```

- [ ] **Step 6: The doc**

In `docs/admin/day-to-day.md`, in the bullet list under Locum requirements, after the `**Clinician**` bullet add:

```markdown
- **Covering for** — optional: the clinician the locum stands in for. Shown
  on the badge's tooltip, and written into the booked session's note
  ("Covering Tom Hodges. Agency X") so the grid cell says it too.
```

- [ ] **Step 7: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_locums.py tests/test_edit_views.py tests/test_grid_view.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 914 passed.

```bash
git add rota/services/locums.py rota/views/edit.py rota/views/grid.py templates/rota/_locum_form.html templates/rota/grid.html docs/admin/day-to-day.md tests/test_locums.py tests/test_edit_views.py tests/test_grid_view.py
git commit -m "feat: a locum requirement says who the locum covers

A Covering-for dropdown of non-locum clinicians; the badge tooltip and
the booked session's note both name them.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Locums appear only when they hold a session in the period shown

**Files:**
- Modify: `rota/services/cells.py` (new function)
- Modify: `rota/views/grid.py:74-103`
- Modify: `rota/views/day.py:78-83` and `:100-104`
- Modify: `docs/admin/day-to-day.md` (Locum requirements section)
- Test: `tests/test_cells.py`, `tests/test_grid_view.py`, `tests/test_day_view.py`

**Interfaces:**
- Produces: `rota.services.cells.shows_on_roster(*, is_locum: bool, has_entry: bool) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cells.py`:

```python
# ------------------------------------------------------------- locums ---

from rota.services.cells import shows_on_roster


@pytest.mark.parametrize("is_locum,has_entry,shown", [
    (False, False, True),
    (False, True, True),
    (True, False, False),
    (True, True, True),
])
def test_only_an_idle_locum_is_hidden(is_locum, has_entry, shown):
    assert shows_on_roster(is_locum=is_locum, has_entry=has_entry) is shown
```

Append to `tests/test_grid_view.py`:

```python
def test_an_idle_locum_has_no_row_but_the_need_row_stays(admin_client):
    PracticeSettings.load()
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Idle Locum", group=locums)
    html = admin_client.get(URL).content.decode()
    assert "Idle Locum" not in html
    assert ">Need<" in html


def test_a_booked_locum_has_a_row_that_week(admin_client):
    PracticeSettings.load()
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    busy = make_clinician("Busy Locum", group=locums)
    make_entry(busy, day=MON, part="AM", session_type=make_session_type("Routine"))
    html = admin_client.get(URL).content.decode()
    assert 'title="Busy Locum"' in html
```

(`test_grid_view.py` needs `make_entry` in its factories import if absent.)

Append to `tests/test_day_view.py`:

```python
def test_an_idle_locum_is_listed_nowhere_on_the_day(gp_client, gp_user):
    """Many locums are defined and few are booked; the "Not in" line was
    where they all piled up."""
    from tests.factories import make_group
    make_clinician("Viewer", user=gp_user)
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Idle Locum", group=locums)
    html = _html(gp_client)
    assert "Idle Locum" not in html


def test_a_locum_with_a_session_is_on_the_roster(gp_client, gp_user):
    from tests.factories import make_group
    make_clinician("Viewer", user=gp_user)
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    busy = make_clinician("Busy Locum", group=locums)
    make_entry(busy, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert "Busy Locum" in _roster_tbody(_html(gp_client))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_cells.py tests/test_grid_view.py tests/test_day_view.py -q -k "locum"`
Expected: the `shows_on_roster` import fails; the two "idle" tests FAIL; the two "booked" tests PASS already (keep them — they pin that the rule is not "hide all locums").

- [ ] **Step 3: The rule**

Append to `rota/services/cells.py`:

```python
def shows_on_roster(*, is_locum, has_entry):
    """Whether a clinician gets a row on a roster screen at all.

    Many locums are defined and few are booked in any given week, so an
    idle locum is a blank row on the grid and a name on the day view's
    "Not in" line — noise, on every screen, for every locum, every day.
    A locum is listed only while they hold a session in the period shown.
    Everyone else is listed regardless: a salaried GP's empty week is
    information (nothing allocated yet), a locum's is not.

    The grid and the day view both ask this; admin dropdowns and the
    booking form do not — they need every locum.
    """
    return has_entry or not is_locum
```

- [ ] **Step 4: The grid**

In `rota/views/grid.py`, import `shows_on_roster` alongside `cell_state`, and at the top of the `for clinician in group.clinicians.all():` loop add:

```python
            has_entry = any((clinician.id, d, part) in cell_map
                            for d in days for part in ("AM", "PM"))
            if not shows_on_roster(is_locum=group.is_locum_group,
                                   has_entry=has_entry):
                continue
```

The `if rows or group.is_locum_group:` line below already keeps the section (and its Need row) when every locum is hidden.

- [ ] **Step 5: The day view**

In `rota/views/day.py`, import `shows_on_roster` alongside `cell_state`. The `active` query becomes:

```python
    active = list(Clinician.objects.filter(active=True)
                  .select_related("group").order_by("name"))
```

(`select_related("group")` — without it the rule below costs a query per clinician, and `tests/test_phase2_queries.py::test_the_day_view_does_not_query_per_clinician` fails.)

At the top of the `for c in active:` loop, before the `in_service` check:

```python
        if not shows_on_roster(is_locum=c.group.is_locum_group,
                               has_entry=c.id in by_clinician):
            continue
```

- [ ] **Step 6: The doc**

In `docs/admin/day-to-day.md`, at the end of the Locum requirements section (after the paragraph about booked requirements being protected), add:

```markdown
Locums appear on the grid and the day view **only in a period where they hold
a session**. An idle locum is neither a blank row nor a name on the "Not in"
line. The booking form and the admin still list every locum.
```

- [ ] **Step 7: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_cells.py tests/test_grid_view.py tests/test_day_view.py tests/test_phase2_queries.py tests/test_grid_rendering.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 922 passed.

```bash
git add rota/services/cells.py rota/views/grid.py rota/views/day.py docs/admin/day-to-day.md tests/test_cells.py tests/test_grid_view.py tests/test_day_view.py
git commit -m "feat: locums are listed only while they hold a session

One rule, shows_on_roster, asked by the grid and the day view. An idle
locum is no longer a blank row or a name on the Not-in line.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: One deletion rule for drafts, which the fill engine also uses

**Files:**
- Modify: `rota/services/entries.py`
- Modify: `rota/services/fill/__init__.py:13-18`
- Test: `tests/test_delete_drafts.py` (new)

**Interfaces:**
- Produces:
  - `entries.drafts(start=None, end=None, *, include_manual) -> QuerySet[RotaEntry]`
  - `entries.delete_drafts(actor, start=None, end=None, *, include_manual) -> tuple[int, int]` — `(deleted, hand_placed)`.
  - `RotaEntryLog` row with `action="deleted drafts"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_delete_drafts.py`:

```python
"""Deleting unpublished work in bulk.

One function decides what is "in scope" (drafts()) and one deletes it
(delete_drafts()). The fill engine's own re-run clearing calls the same
function, so there is one deletion rule in the codebase, not two.
"""

import uuid
from datetime import timedelta

import pytest

from rota.models import RotaEntry, RotaEntryLog
from rota.services import entries
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

FRI = MON + timedelta(days=4)
NEXT_MON = MON + timedelta(days=7)


@pytest.fixture
def world():
    """Inside MON..FRI: a published entry, a fill draft, a hand-placed draft.
    Outside it: a fill draft next week."""
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    return {
        "published": make_entry(c, day=MON, part="AM", session_type=rout),
        "fill": make_entry(c, day=MON, part="PM", session_type=rout,
                           is_published=False, manually_set=False),
        "manual": make_entry(c, day=FRI, part="AM", session_type=rout,
                             is_published=False, manually_set=True),
        "later": make_entry(c, day=NEXT_MON, part="AM", session_type=rout,
                            is_published=False, manually_set=False),
    }


@pytest.mark.parametrize("include_manual,bounded,expected", [
    (True, False, {"fill", "manual", "later"}),
    (True, True, {"fill", "manual"}),
    (False, False, {"fill", "later"}),
    (False, True, {"fill"}),
])
def test_scope_is_the_product_of_manual_and_range(world, include_manual, bounded, expected):
    start, end = (MON, FRI) if bounded else (None, None)
    qs = entries.drafts(start, end, include_manual=include_manual)
    assert {k for k, e in world.items() if e in qs} == expected
    assert world["published"] not in qs


def test_delete_returns_the_counts_and_leaves_published_alone(world, admin_user):
    deleted, hand_placed = entries.delete_drafts(
        admin_user, MON, FRI, include_manual=True)
    assert (deleted, hand_placed) == (2, 1)
    assert set(RotaEntry.objects.values_list("pk", flat=True)) == {
        world["published"].pk, world["later"].pk}


def test_fill_scope_keeps_hand_placed_work(world, admin_user):
    deleted, hand_placed = entries.delete_drafts(
        admin_user, None, None, include_manual=False)
    assert (deleted, hand_placed) == (2, 0)
    assert RotaEntry.objects.filter(pk=world["manual"].pk).exists()


def test_the_deletion_is_logged_once(world, admin_user):
    entries.delete_drafts(admin_user, MON, FRI, include_manual=True)
    (log,) = RotaEntryLog.objects.filter(action="deleted drafts")
    assert log.actor == admin_user
    assert log.detail == f"{MON}..{FRI} (2 entries, 1 hand-placed)"


def test_an_unbounded_deletion_logs_all_dates(world, admin_user):
    entries.delete_drafts(admin_user, include_manual=True)
    log = RotaEntryLog.objects.get(action="deleted drafts")
    assert log.detail == "all dates (3 entries, 1 hand-placed)"


def test_a_published_survivor_loses_the_group_its_deleted_half_shared(admin_user):
    """A hand-placed full day, one half published by mistake: deleting the
    draft half must not leave the published half pointing at a pair that
    no longer exists — that is what the cell-by-cell clear() does too."""
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    group = uuid.uuid4()
    kept = make_entry(c, day=MON, part="AM", session_type=rout, allocation_group=group)
    make_entry(c, day=MON, part="PM", session_type=rout, allocation_group=group,
               is_published=False)
    other = make_clinician("Other One")
    pair = uuid.uuid4()
    kept2 = make_entry(other, day=FRI, part="AM", session_type=rout, companion_group=pair)
    make_entry(c, day=FRI, part="AM", session_type=rout, companion_group=pair,
               is_published=False)

    entries.delete_drafts(admin_user, MON, FRI, include_manual=True)

    kept.refresh_from_db()
    kept2.refresh_from_db()
    assert kept.allocation_group is None
    assert kept2.companion_group is None


def test_run_fill_clears_through_the_same_rule(admin_user):
    """The engine deletes its own drafts before running. It now does so
    through delete_drafts(include_manual=False), and so logs it."""
    from rota.services.fill import run_fill
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=rout,
               is_published=False, manually_set=False)
    make_entry(c, day=MON, part="PM", session_type=rout,
               is_published=False, manually_set=True)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(is_published=False, manually_set=True).count() == 1
    assert RotaEntryLog.objects.filter(action="deleted drafts").exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_delete_drafts.py -q`
Expected: FAIL — `AttributeError: module 'rota.services.entries' has no attribute 'drafts'`.

- [ ] **Step 3: The service**

In `rota/services/entries.py`, add `from datetime import date` to the imports, and append:

```python
def drafts(start=None, end=None, *, include_manual):
    """Every unpublished entry in scope — the one definition, used by the
    preview and the deletion so they cannot disagree. Bounded by
    `day__range` when both dates are given; otherwise every date.
    `include_manual=False` is the fill engine's rule: its own drafts only,
    never one an admin placed by hand."""
    qs = RotaEntry.objects.filter(is_published=False)
    if start is not None and end is not None:
        qs = qs.filter(day__range=(start, end))
    if not include_manual:
        qs = qs.filter(manually_set=False)
    return qs


@transaction.atomic
def delete_drafts(actor, start=None, end=None, *, include_manual):
    """Delete the drafts in scope. Returns (deleted, hand_placed).

    Un-groups survivors: a published entry whose allocation_group or
    companion_group was shared with a deleted draft has that field set to
    None, as clear() does cell by cell — a pair with one half gone is not
    a pair. One log row for the whole operation.
    """
    qs = drafts(start, end, include_manual=include_manual)
    hand_placed = qs.filter(manually_set=True).count()
    allocation = set(qs.exclude(allocation_group=None)
                     .values_list("allocation_group", flat=True))
    companion = set(qs.exclude(companion_group=None)
                    .values_list("companion_group", flat=True))
    _, by_model = qs.delete()
    deleted = by_model.get("rota.RotaEntry", 0)
    if allocation:
        RotaEntry.objects.filter(allocation_group__in=allocation).update(
            allocation_group=None)
    if companion:
        RotaEntry.objects.filter(companion_group__in=companion).update(
            companion_group=None)
    span = f"{start}..{end}" if start is not None and end is not None else "all dates"
    _log(actor, start or date.today(), "", "", "deleted drafts",
         f"{span} ({deleted} entries, {hand_placed} hand-placed)")
    return deleted, hand_placed
```

- [ ] **Step 4: The fill engine**

In `rota/services/fill/__init__.py`, `run_fill` starts with:

```python
@transaction.atomic
def run_fill(actor, start, end, fill_default=False):
    # Its own previous drafts, never a published entry or one an admin
    # placed by hand — the same rule the Delete-drafts card offers as
    # "fill drafts only", and the same function, so there is one rule.
    entries.delete_drafts(actor, start, end, include_manual=False)

    result = FillResult()
```

Remove the three-line `RotaEntry.objects.filter(...).delete()` it replaces. If `RotaEntry` is now unused in that module, remove its import.

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_delete_drafts.py tests/test_fill.py tests/test_entries.py -q` — all PASS. `test_fill.py::test_rerun_replaces_own_drafts_but_keeps_manual` and `test_published_fill_drafts_survive_rerun` are the existing guards on the engine's behaviour and must still pass untouched.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 933 passed.

```bash
git add rota/services/entries.py rota/services/fill/__init__.py tests/test_delete_drafts.py
git commit -m "feat: one rule for deleting drafts, which the fill engine now uses too

entries.drafts() defines the scope; delete_drafts() deletes it, logs one
row, and un-groups any published survivor whose pair it broke. run_fill
clears its own drafts through the same function.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: The Delete-drafts card, with a preview before anything goes

**Files:**
- Modify: `rota/views/fill.py`
- Modify: `rota/urls.py`
- Modify: `templates/rota/fill.html`
- Modify: `tests/test_security.py:156-172`
- Modify: `docs/admin/day-to-day.md:7-13` and a new section after Assisted fill
- Test: `tests/test_delete_drafts_view.py` (new)

**Interfaces:**
- Consumes: `entries.drafts()`, `entries.delete_drafts()` (Task 10).
- Produces: `POST /rota/drafts/delete/` (URL name `drafts-delete`), fields `scope` ∈ {`all`,`fill`}, `range` ∈ {`all`,`dates`}, `start`, `end`, `confirm`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_delete_drafts_view.py`:

```python
"""The Delete-drafts card on the fill screen. Nothing is deleted without
the second click — the spec's preview rule for destructive actions."""

from datetime import timedelta

import pytest

from rota.models import RotaEntry
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

URL = "/rota/drafts/delete/"
FRI = MON + timedelta(days=4)


@pytest.fixture
def drafts():
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=rout)                       # published
    make_entry(c, day=MON, part="PM", session_type=rout, is_published=False,
               manually_set=False)
    make_entry(c, day=FRI, part="AM", session_type=rout, is_published=False)   # hand-placed
    make_entry(c, day=FRI + timedelta(days=3), part="AM", session_type=rout,
               is_published=False, manually_set=False)


def test_the_card_is_on_the_fill_screen(admin_client):
    html = admin_client.get("/rota/fill/").content.decode()
    assert "Delete drafts" in html
    assert f'action="{URL}"' in html


def test_a_gp_cannot_reach_it(gp_client):
    assert gp_client.post(URL, {"scope": "all", "range": "all"}).status_code == 403


def test_get_is_not_allowed(admin_client):
    assert admin_client.get(URL).status_code == 405


def test_the_first_post_previews_and_deletes_nothing(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": MON.isoformat(), "end": FRI.isoformat()})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "2 drafts" in html and "1 placed by hand" in html
    assert 'name="confirm"' in html
    assert RotaEntry.objects.filter(is_published=False).count() == 3


def test_the_confirmed_post_deletes_flashes_and_returns_to_the_fill_screen(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": MON.isoformat(), "end": FRI.isoformat(),
                                   "confirm": "1"})
    assert resp.status_code == 302 and resp["Location"] == "/rota/fill/"
    assert RotaEntry.objects.filter(is_published=False).count() == 1
    assert RotaEntry.objects.filter(is_published=True).count() == 1
    followed = admin_client.get("/rota/fill/").content.decode()
    assert "Deleted 2 drafts." in followed


def test_fill_scope_over_all_dates(drafts, admin_client):
    admin_client.post(URL, {"scope": "fill", "range": "all", "confirm": "1"})
    left = RotaEntry.objects.filter(is_published=False)
    assert left.count() == 1 and left.get().manually_set


def test_a_bad_date_is_a_400(admin_client):
    assert admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": "junk", "end": "junk"}).status_code == 400


def test_an_end_before_the_start_is_a_400(admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": FRI.isoformat(), "end": MON.isoformat()})
    assert resp.status_code == 400
    assert b"before" in resp.content
```

In `tests/test_security.py`, add `"/rota/drafts/delete/"` to both `PROTECTED` and `ADMIN_ONLY`.

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_delete_drafts_view.py tests/test_security.py -q`
Expected: the new tests FAIL with 404s; the security parametrisations for the new URL FAIL.

- [ ] **Step 3: The view**

`rota/views/fill.py` — add imports:

```python
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from rota.services import entries as entries_svc
```

Extract the fill view's base context and add the new view. The whole tail of the file (from `@admin_required` above `def fill`) becomes:

```python
def _base_context():
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return {
        "start": next_monday,
        "end": next_monday + timedelta(days=27),
        "result": None,
        "default_type": PracticeSettings.load().default_fill_session_type,
    }


@admin_required
@parse_errors_as_400
def fill(request):
    context = _base_context()
    if request.method == "POST":
        start = date.fromisoformat(request.POST["start"])
        end = date.fromisoformat(request.POST["end"])
        result = run_fill(request.user, start, end,
                          fill_default=bool(request.POST.get("fill_default")))
        context.update({
            "start": start, "end": end,
            "result": result,
            "unfilled_groups": _group_unfilled(result.unfilled),
        })
    return render(request, "rota/fill.html", context)


def _delete_scope(post):
    """(start, end, include_manual) from the card's fields. A range whose
    end precedes its start is refused rather than silently matching
    nothing: the preview would say "0 drafts" about a typo."""
    include_manual = post.get("scope", "all") != "fill"
    if post.get("range", "all") == "dates":
        start = date.fromisoformat(post["start"])
        end = date.fromisoformat(post["end"])
        if end < start:
            raise ValueError("The end date is before the start date.")
    else:
        start = end = None
    return start, end, include_manual


@admin_required
@parse_errors_as_400
@require_POST
def delete_drafts(request):
    """Two POSTs. The first renders a preview — how many, how many placed by
    hand, which dates — and deletes nothing. The second, carrying `confirm`,
    deletes. The fill re-run's no-confirmation exemption does not apply: this
    button can remove work an admin placed by hand."""
    start, end, include_manual = _delete_scope(request.POST)
    if not request.POST.get("confirm"):
        qs = entries_svc.drafts(start, end, include_manual=include_manual)
        context = _base_context()
        context["delete_preview"] = {
            "count": qs.count(),
            "hand_placed": qs.filter(manually_set=True).count(),
            "start": start, "end": end,
            "scope": request.POST.get("scope", "all"),
            "range": request.POST.get("range", "all"),
            "include_manual": include_manual,
        }
        return render(request, "rota/fill.html", context)
    deleted, _ = entries_svc.delete_drafts(
        request.user, start, end, include_manual=include_manual)
    messages.success(request, f"Deleted {deleted} draft{'' if deleted == 1 else 's'}.")
    return redirect("/rota/fill/")
```

`rota/urls.py` — after the `rota/fill/` path:

```python
    path("rota/drafts/delete/", fill.delete_drafts, name="drafts-delete"),
```

- [ ] **Step 4: The template**

In `templates/rota/fill.html`, after the run-fill `<div class="card">…</div>` and before `{% if result %}`, add:

```html
  <div class="card">
    <h2>Delete drafts</h2>
    <form method="post" action="/rota/drafts/delete/">{% csrf_token %}
      <div class="field">
        <label><input type="radio" name="scope" value="all" checked> Every unpublished session</label>
        <label><input type="radio" name="scope" value="fill"> Only the fill engine's own drafts — keep sessions placed by hand</label>
      </div>
      <div class="field">
        <label><input type="radio" name="range" value="all" checked> Every date</label>
        <label><input type="radio" name="range" value="dates"> Between these dates</label>
        <input type="date" name="start" aria-label="From" value="{{ start|date:'Y-m-d' }}">
        <input type="date" name="end" aria-label="To" value="{{ end|date:'Y-m-d' }}">
      </div>
      <p class="field-help">Published sessions are never touched. You will see a count before anything is deleted.</p>
      <div class="form-actions">
        <button type="submit" class="btn">Preview</button>
      </div>
    </form>
    {% if delete_preview %}
    <p>This will delete <strong>{{ delete_preview.count }} draft{{ delete_preview.count|pluralize }}</strong>{% if delete_preview.range == "dates" %} between {{ delete_preview.start|date:"j M" }} and {{ delete_preview.end|date:"j M" }}{% else %} across every date{% endif %}{% if delete_preview.include_manual %}, {{ delete_preview.hand_placed }} placed by hand{% endif %}.</p>
    <form method="post" action="/rota/drafts/delete/">{% csrf_token %}
      <input type="hidden" name="scope" value="{{ delete_preview.scope }}">
      <input type="hidden" name="range" value="{{ delete_preview.range }}">
      {% if delete_preview.start %}
      <input type="hidden" name="start" value="{{ delete_preview.start|date:'Y-m-d' }}">
      <input type="hidden" name="end" value="{{ delete_preview.end|date:'Y-m-d' }}">
      {% endif %}
      <input type="hidden" name="confirm" value="1">
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Delete {{ delete_preview.count }} draft{{ delete_preview.count|pluralize }}</button>
      </div>
    </form>
    {% endif %}
  </div>
```

- [ ] **Step 5: The docs**

In `docs/admin/day-to-day.md`, the Assisted-fill paragraph ending `That is also why there is no confirmation step.` becomes `That is also why the run itself has no confirmation step — the Delete drafts card below, which can remove hand-placed work, does.`

After the `### Reading the unfilled list` table and its closing paragraph, before `## Rota entries`, add:

```markdown
## Delete drafts

Also on `/rota/fill/`. Two choices, then a preview, then the deletion.

- **Which drafts** — every unpublished session, or only the fill engine's own
  (the rule the engine itself applies before a re-run: unpublished **and** not
  placed by hand).
- **Which dates** — every date, or a range.

**Preview** shows how many drafts that is and how many were placed by hand.
Nothing is deleted until you press **Delete** on that preview. Published
sessions are never in scope; a booked locum's session is published when it is
booked, so it is never in scope either. One line goes to the rota entry log
per deletion, naming the range and the counts.
```

- [ ] **Step 6: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_delete_drafts_view.py tests/test_security.py tests/test_fill_view.py tests/test_template_hygiene.py -q` — all PASS.
Run: `/root/rota/.venv/bin/python -m pytest -q` — 943 passed (plus the two new `test_security` parametrisations: 945).

```bash
git add rota/views/fill.py rota/urls.py templates/rota/fill.html docs/admin/day-to-day.md tests/test_delete_drafts_view.py tests/test_security.py
git commit -m "feat: a Delete-drafts card on the fill screen, with a preview first

Scope (all unpublished, or the fill engine's own) and range (every date,
or between two). The first POST shows the count and how many were placed
by hand; only the second, confirmed POST deletes.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: The remaining words

**Files:**
- Modify: `docs/admin/day-to-day.md` (Rota entries bullets; Warnings on the grid)
- Modify: `README.md` (only if it describes any of these)
- Test: `tests/test_template_hygiene.py` (already runs)

**Interfaces:** none.

- [ ] **Step 1: Notes and the fourth warning source**

In `docs/admin/day-to-day.md`, under `## Rota entries`, the bullet `- **Note** — free text on this one entry, shown on the cell.` becomes:

```markdown
- **Note** — free text on this one entry. A dot in the chip's corner says
  one exists; the grid shows it on hover, and the day view and My Schedule
  print it under the session.
```

Under `## Warnings on the grid`, `come from **three separate sources**` becomes `come from **four separate sources**`, and after item 3 add:

```markdown
4. **Breathe clashes** — "On Breathe leave but rostered (AM): TH (Holiday)".
   A published or drafted session on someone Breathe says is off. The cell
   itself is ringed for everyone; this header line is yours. See
   [Leave from Breathe](breathe.md).
```

- [ ] **Step 2: Check the README**

Run: `grep -n -i "locum\|note\|draft\|leave" README.md`. If any line describes locum statuses as three, notes as hover-only, or draft deletion as impossible, update it to match the docs above. If nothing matches, change nothing.

- [ ] **Step 3: Run the suite and commit**

Run: `/root/rota/.venv/bin/python -m pytest -q` — 945 passed.

```bash
git add docs/admin/day-to-day.md README.md
git commit -m "docs: notes, the fourth warning source, and the README where it lagged

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

(If `README.md` did not change, leave it out of the `git add`.)

---

## Self-review against the spec

**Spec coverage.**

| Spec section | Task |
|---|---|
| 1 Notes marker (dot, day/Me text, fill_reason excluded) | 5 |
| 2 Plumbing: `covering()`, `leave_label()`, `on_leave` under an entry, `clash`, closed ignored | 1 |
| 2 Cell ring + tooltip; header line with initials + labels; day view files under On leave; My Schedule via `_is_leave_cell` | 2, 3 |
| 2 Leftover: resolver passed to `day_warnings`; leftover: `_blocks()` `is_open` guard | 2, 4 |
| 3 Tooltip label at six sites; ten re-pointed references | 3 |
| 4 Card, scope × range, preview, confirm, flash, redirect, URL, `drafts()` / `delete_drafts()`, un-grouping, log, `run_fill` reuse | 10, 11 |
| 5 Status order, value, label, outline badge, suffix, docs | 6, 7 |
| 6 `covering` field, form, refusal, tooltip, note prefix, admin, select_related, docs | 6, 8 |
| 7 `shows_on_roster`, grid, day view, Need row, select_related group, docs | 9 |
| Documentation: breathe.md; day-to-day (delete drafts, locum states, covering, locums hidden, notes, warning sources); backlog | 3, 7, 8, 9, 11, 12 — `docs/backlog.md` does not list the two PR #6 leftovers, so there is nothing to remove there. |

One spec detail deliberately narrowed: the spec says the note marker "renders wherever a chip does", and the pinned block on the day view iterates entries rather than cells, so it takes the **note** marker (Task 5, from `e.note`) but not the **clash** ring (Task 3 — it has no cell state). The same entry appears ringed in the roster below.

**Placeholder scan.** No "TBD", "TODO", "similar to Task N", or "add appropriate …". Every code step shows the code.

**Type consistency.** `leave_label(kind, reason) -> str` (Task 1) is what Tasks 2 and 3 read as `cell["leave_label"]`. `shows_on_roster(*, is_locum, has_entry)` (Task 9) is called with keywords in both views. `entries.drafts(start, end, *, include_manual)` and `delete_drafts(actor, start, end, *, include_manual) -> (int, int)` (Task 10) match every call in Task 11 and in `run_fill`. `save_requirement(..., covering=None)` (Task 8) matches the view's keyword. `LocumRequirement.Status.APPROVED == "APPROVED"` (Task 6) matches the CSS class `.badge.APPROVED` (Task 7) and the POST value in Task 8's test.

**Expected test counts** are running totals from the 880 baseline (+8, +4, +5, +1, +5, +2, +3, +6, +8, +11, +10, +0 = 943, plus two `test_security` parametrisations = 945). They are guidance for the implementer, not assertions: if a count differs, the implementer reports the actual number and why.
