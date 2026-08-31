# Frontend Phase 2 — Mobile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a day view, rebuild My Schedule for a phone, and give the app a navigation that works on a narrow screen — changing no scheduling logic.

**Architecture:** One extraction and two new screens. The cell precedence currently inline in `grid()` moves to `rota/services/cells.py` so the day view cannot become a second answer to it; the grid's existing tests are the regression net. The day view and My Schedule are ordinary Django views and templates. Responsive behaviour is a single `@media (max-width: 640px)` block plus a `.tabbar` component — no JavaScript beyond `<details>`.

**Tech Stack:** Django 5.2 LTS, htmx, SQLite WAL, Python 3.13, pytest. Plain CSS.

**Spec:** `docs/superpowers/specs/2026-08-31-frontend-phase2-design.md`

## Global Constraints

- **No build step, no node, no preprocessor, no new dependencies.** A solo GP maintains this.
- Every colour comes from `static/css/tokens.css`. **No hex literal, `rgb(`, `rgba(`, `hsl(` or `hsla(` may appear in `components.css` or `screens.css`** — `tests/test_chrome_contrast.py::test_no_colour_literals` greps for exactly those and fails.
- Three-state dark mode: bare `:root`, then `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`, then `:root[data-theme="dark"]`.
- WCAG AA: **4.5:1** for text, **3:1** for the visible boundary of any UI component. Touch targets at least **44px**.
- **No pre-existing test may be edited, with exactly one authorised exception: Task 1.** Nothing else in this plan may modify a file under `tests/` that already exists.
- All schedule mutations stay in `rota/services/*`. This phase adds no mutations.
- The breakpoint is **640px**, written as `@media (max-width: 640px)`, and it is the only width-based media query this phase adds.
- Run tests with `SECRET_KEY=throwaway .venv/bin/python -m pytest`. `DEBUG` defaults off and `SECRET_KEY` has no default, so every `manage.py` and `pytest` invocation needs it.
- The full suite is **680 passing** at the start of this phase. It must be 680 plus whatever you add, with nothing failing, at the end of every task.

---

### Task 1: Teach the cascade parser about `@media`

`tests/test_css_cascade.py` refuses at-rules by assertion. Its own comment invites the next person to clear it: *"if one is ever added, this fails loudly instead of quietly scoring the cascade wrong."* Every later task in this plan writes a media query into those sheets, so this is first.

**This is the one authorised edit to a pre-existing test file in this plan.** The exception is narrow: the parser gains the ability to read a construct the codebase now legitimately uses, and **every existing assertion keeps its current meaning**. If you find yourself weakening or deleting an assertion to make CSS pass, stop — that is not covered.

**Files:**
- Modify: `tests/test_css_cascade.py` (the `_parse` function and its module docstring)

**Interfaces:**
- Produces: `Rule` objects gain a `.media` attribute — `None` for a top-level rule, or the media query text (e.g. `"(max-width: 640px)"`) for one inside an at-rule block. Later tasks rely on `RULES` continuing to contain every rule in both sheets.

- [ ] **Step 1: Read the existing parser**

Read `tests/test_css_cascade.py` from the top through `_read_all()`. You need `Rule.__init__`'s current signature and the `assert "@" not in css` line before you change anything.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_css_cascade.py`:

```python
# --------------------------------------------------------------------------
# the parser itself
# --------------------------------------------------------------------------

def test_parser_reads_rules_inside_a_media_block():
    """Phase 2 adds the first @media block to these sheets.

    The parser used to refuse at-rules outright, on the grounds that a naive
    brace-matcher would read `@media (max-width: 640px) {` as a selector and
    score the cascade wrong. It now reads them properly: rules inside the
    block are real rules, tagged with the query they sit under.
    """
    css = ".a { color: red; }\n@media (max-width: 640px) {\n  .b { color: blue; }\n}\n.c { color: green; }"
    rules, _ = _parse(css, "fake.css", 0)
    by_selector = {r.selector: r for r in rules}

    assert set(by_selector) == {".a", ".b", ".c"}
    assert by_selector[".a"].media is None
    assert by_selector[".b"].media == "(max-width: 640px)"
    assert by_selector[".c"].media is None, "a rule after the block is top-level again"
    assert by_selector[".b"].declarations == {"color": "blue"}
```

- [ ] **Step 3: Run it and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_css_cascade.py::test_parser_reads_rules_inside_a_media_block -v
```

Expected: `AssertionError: fake.css has grown an at-rule; this parser only handles flat rules`.

- [ ] **Step 4: Give `Rule` a `media` attribute**

In `Rule.__init__`, add a keyword-only `media` parameter defaulting to `None` and store it as `self.media`. Do not change any other attribute, and do not change how `order` is assigned — existing tests score the cascade by `order` and must keep their current results.

- [ ] **Step 5: Replace the refusal with a real read**

Replace the `assert "@" not in css` guard and the flat `re.finditer` loop in `_parse` with a reader that pulls `@media` and `@supports` block bodies out and parses them as real rulesets, tagged with their query.

**Number every rule by its position in the document**, whether it sits at top level or inside an at-rule block. `order` *is* the cascade (CSS 2.2 §6.4.3), and the media block this phase adds sits at the **end** of `screens.css`, so its rules must carry the **highest** order. A two-pass reader that walks all the at-rule blocks first and the top-level rules second gets this backwards, and the mistake is invisible until a cascade assertion silently scores the wrong way round. A single left-to-right walk that tracks brace depth is the straightforward way to get it right.

Refuse anything that is not `@media` or `@supports` — those are the only at-rules that nest rulesets, and a blockless `@import` or `@charset` would be mis-read as selector text. Keep `_parse` returning its existing `(rules, order)` tuple; `_read_all()` depends on that shape.

- [ ] **Step 6: Run the whole cascade module**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_css_cascade.py -v
```

Expected: PASS, including every pre-existing test. If any pre-existing test now fails, the parser change altered a result it was asserting — fix the parser, never the assertion.

- [ ] **Step 7: Run the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: 681 passed.

- [ ] **Step 8: Update the module docstring**

The docstring's "WHAT THESE TESTS CANNOT PROVE" section still says the parser only handles flat rules. Replace that clause with one sentence saying it now reads `@media` and `@supports` bodies and tags each rule with its query, and that a rule's applicability at a given viewport is still not proven by anything here.

- [ ] **Step 9: Commit**

```bash
git add tests/test_css_cascade.py
git commit -m "test: the cascade parser reads @media blocks

Its own comment invited this: the parser refused at-rules so that adding
one would fail loudly rather than score the cascade wrong. Phase 2 adds
the first media query to these sheets, so the parser learns to read them.

Every existing assertion keeps its meaning; rules gain a .media tag."
```

---

### Task 2: `SessionType.pin_on_day_view`

The day view pins the practice's critical session types above the roster. Which types those are is configuration, not inference — the practice's per-slot coverage rules cover Duty, Urgent *and* Routine, so any heuristic reading importance out of coverage rules pins the bulk of the rota.

**Files:**
- Modify: `rota/models/catalog.py` (the `SessionType` model)
- Create: `rota/migrations/0021_sessiontype_pin_on_day_view.py` (generated)
- Modify: `rota/admin.py` (`SessionTypeAdmin`)
- Modify: `docs/admin/session-types.md`
- Test: `tests/test_models_people_catalog.py` is pre-existing — create `tests/test_day_pinning.py` instead

**Interfaces:**
- Produces: `SessionType.pin_on_day_view` — `BooleanField(default=False)`. Tasks 5 and 6 read it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_day_pinning.py`:

```python
"""The flag that decides which session types head the day view."""

import pytest

from rota.models import SessionType
from tests.factories import make_session_type

pytestmark = pytest.mark.django_db


def test_types_are_not_pinned_by_default():
    t = make_session_type("Routine", code="ROUT")
    assert t.pin_on_day_view is False


def test_a_type_can_be_pinned_and_found_by_query():
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    make_session_type("Routine", code="ROUT")
    assert list(SessionType.objects.filter(pin_on_day_view=True)) == [duty]
```

- [ ] **Step 2: Run it and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_pinning.py -v
```

Expected: FAIL — `TypeError` or `FieldError` on `pin_on_day_view`.

- [ ] **Step 3: Add the field**

In `rota/models/catalog.py`, immediately after `fairness_tracked`, add:

```python
    pin_on_day_view = models.BooleanField(
        default=False,
        help_text="Show this type in its own block at the top of the day view. "
                  "Use it for the roles someone would open the day view to check "
                  "— Duty above all. Leave it off for the bulk of the rota.",
    )
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations rota
```

Expected: creates `rota/migrations/0021_sessiontype_pin_on_day_view.py` with a single `AddField`. Read it and confirm it contains nothing else.

- [ ] **Step 5: Run the test**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_pinning.py -v
```

Expected: PASS.

- [ ] **Step 6: Expose it in the admin**

In `rota/admin.py`, find `SessionTypeAdmin`. Add `"pin_on_day_view"` to `list_display` after `fairness_tracked`, to `list_filter`, and into whichever fieldset or `fields` list carries `fairness_tracked`. If the admin class relies on Django's default field ordering with no explicit `fields`, only `list_display` and `list_filter` need touching.

- [ ] **Step 7: Document it**

In `docs/admin/session-types.md`, add a section between "Fairness tracked" and "Counts toward entitlement":

```markdown
## Pin on day view

Puts this type in its own block at the **top of the day view**, above the
roster, so "who is on Duty today" is answered without reading every row.

Leave it off for the bulk of the rota. Pinning Routine would put most of the
practice in the pinned block and defeat the point of having one. If nothing is
pinned, the block does not appear at all.
```

- [ ] **Step 8: Check migrations are clean and run the suite**

```bash
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations --check --dry-run
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: "No changes detected", then 683 passed.

- [ ] **Step 9: Commit**

```bash
git add rota/models/catalog.py rota/migrations/0021_sessiontype_pin_on_day_view.py rota/admin.py docs/admin/session-types.md tests/test_day_pinning.py
git commit -m "feat: session types can be pinned to the top of the day view

Configuration rather than inference: the practice's per-slot coverage rules
cover Duty, Urgent and Routine, so any rule deducing importance from them
pins most of the rota."
```

---

### Task 3: Extract the cell precedence

`grid()` decides what a cell shows: entry, then ghosted leave, then off, then empty — with two guard clauses on the ghost that cost three review rounds in the previous phase. The day view needs the same decision. Extract it so there is one answer, and let the grid's existing tests prove the extraction changed nothing.

**Files:**
- Create: `rota/services/cells.py`
- Modify: `rota/views/grid.py:85-118` (the inner `for part, entry in ...` loop)
- Test: `tests/test_cells.py` (new — `tests/test_grid_rendering.py` is pre-existing and must not be touched)

**Interfaces:**
- Consumes: `rota.services.availability.AvailabilityResolver` — `works_on(clinician_id, day, part)`, `leave_type(clinician_id, day)`, `has_pattern(clinician_id)`, `in_service(clinician_id, day)`.
- Produces: `rota.services.cells.cell_state(clinician_id, day, part, *, entry, resolver, closed, partner=None) -> dict` with keys `day`, `day_str`, `part`, `entry`, `off`, `ghost_leave`, `closed`, `partner`. Tasks 4 and 5 call it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cells.py`:

```python
"""The precedence every rota cell obeys, tested once rather than per screen.

    entry exists           -> the entry
    on leave and ghostable -> a ghosted leave chip
    works_on               -> off=False, nothing allocated
    otherwise              -> off=True

The two guards on "ghostable" are the subtle part and cost three review
rounds in the previous phase, so each gets its own test here.
"""

from datetime import date

import pytest

from rota.models import LeaveRequest, PatternSlot
from rota.services import availability
from rota.services.cells import cell_state
from tests.factories import make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _resolver(clinicians, leave=()):
    rows = list(PatternSlot.objects.filter(clinician__in=clinicians))
    return availability.AvailabilityResolver(rows, list(clinicians), list(leave))


def _works(c, weekday=1):
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                                   works=True, effective_from=date(2020, 1, 1))


def test_an_entry_wins_over_everything():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["entry"] is e
    assert cell["off"] is False
    assert cell["ghost_leave"] is None


def test_a_working_session_with_no_entry_is_not_off():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is False
    assert cell["entry"] is None


def test_a_session_the_clinician_does_not_work_is_off():
    c = make_clinician()
    _works(c, weekday=0)  # Mondays only
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True


def test_approved_leave_with_no_entry_ghosts():
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=False)
    assert cell["ghost_leave"] == al


def test_a_ghost_is_suppressed_on_a_closed_day():
    """Approval writes nothing on a bank holiday, so a chip there accuses it
    of missing an entry it was right not to write."""
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=True)
    assert cell["ghost_leave"] is None


def test_a_ghost_is_suppressed_outside_the_contractual_window():
    """A clinician with no pattern rows still gets ghosts — but not across a
    week they are not employed for."""
    c = make_clinician(start_date=date(2026, 12, 1))  # starts long after TUE
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=False)
    assert cell["ghost_leave"] is None


def test_the_partner_is_carried_through():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False, partner="Dr Trainer")
    assert cell["partner"] == "Dr Trainer"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_cells.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'rota.services.cells'`.

- [ ] **Step 3: Write the module**

Create `rota/services/cells.py`. Move the comment block from `grid.py` with the code — it explains the two guards and is the reason they survived review:

```python
"""What a rota cell shows, decided once.

    entry exists                -> the entry
    on leave and ghostable      -> a ghosted leave chip
    works_on                    -> not off: here, nothing allocated
    otherwise                   -> off: not here

The week grid and the day view both render cells, and a second copy of this
would be a second answer to the question the availability consolidation
existed to give one answer to.
"""


def cell_state(clinician_id, day, part, *, entry, resolver, closed,
               partner=None):
    """One cell's state. Performs no queries — the caller prefetches."""
    works = resolver.works_on(clinician_id, day, part)
    leave_type = resolver.leave_type(clinician_id, day) if entry is None else None

    # Ghost only where it means something: on a session the clinician works
    # (approval should have written an entry and did not), or for a clinician
    # with no pattern at all (nothing would ever show for them otherwise).
    # Ghosting every session leave spans would put chips on every part-timer's
    # days off.
    #
    # Two things the "no pattern" clause must not skip:
    #  - the contractual window. leave.sessions_affected() and works_on() both
    #    refuse to write outside it, so a chip there accuses approval of
    #    missing an entry it was right not to write. `works` already carries
    #    the window; the no-pattern branch has to ask separately.
    #  - a closed day. sessions_affected() skips days where calendar.is_open()
    #    is false, so a bank holiday inside a leave range correctly has no
    #    entry, and a ghost there is noise on every Christmas closure.
    no_pattern_here = (not resolver.has_pattern(clinician_id)
                       and resolver.in_service(clinician_id, day))
    ghostable = (works or no_pattern_here) and not closed

    return {
        "day": day,
        "day_str": day.isoformat(),
        "part": part,
        "entry": entry,
        "off": entry is None and not works,
        "ghost_leave": leave_type if ghostable else None,
        "closed": closed,
        "partner": partner,
    }
```

- [ ] **Step 4: Run the new test**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_cells.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Make the grid call it**

In `rota/views/grid.py`, add `from rota.services.cells import cell_state` to the imports, then replace the whole body of the `for part, entry in (("AM", am), ("PM", pm)):` loop — from `if merged and part == "PM":` through the `cells.append({...})` call — with:

```python
                for part, entry in (("AM", am), ("PM", pm)):
                    if merged and part == "PM":
                        continue
                    cells.append({
                        **cell_state(
                            clinician.id, d, part, entry=entry,
                            resolver=resolver, closed=d in closed,
                            partner=companion_partner.get(
                                (clinician.id, d, part)),
                        ),
                        "merged": merged and part == "AM",
                    })
```

Delete the now-unused local variables and the comment block you moved. `grid.py` should lose roughly 30 lines.

- [ ] **Step 6: Prove the extraction changed nothing**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_grid_rendering.py tests/test_grid_view.py -v
```

Expected: PASS, every test, unchanged. **These are the regression net. If any fails, the extraction altered behaviour — fix `cells.py`, never the test.**

- [ ] **Step 7: Run the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: 690 passed.

- [ ] **Step 8: Commit**

```bash
git add rota/services/cells.py rota/views/grid.py tests/test_cells.py
git commit -m "refactor: cell precedence moves out of the grid view

The day view needs the same decision, and a second copy would be a second
answer to the question the availability consolidation existed to answer
once. The grid's existing tests are the regression net and are unchanged."
```

---

### Task 4: The day view — route, roster, groups

The day's roster: one row per clinician, AM and PM as columns. Plus the two groups that sit below it — people on leave, and people not in that day.

**Files:**
- Create: `rota/views/day.py`
- Create: `templates/rota/day.html`
- Modify: `rota/urls.py`
- Test: `tests/test_day_view.py` (new)

**Interfaces:**
- Consumes: `rota.services.cells.cell_state(clinician_id, day, part, *, entry, resolver, closed, partner=None) -> dict`; `availability.AvailabilityResolver`.
- Produces: view `rota.views.day.day_view(request, day=None)`, URL name `day`. Context keys `target`, `roster`, `on_leave`, `not_in`, `in_count`, `leave_count`, `day_note` — Tasks 5 and 6 add to this context and must not rename these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_day_view.py`:

```python
"""The day view: who is on, and nothing about whether that is enough.

The screen deliberately carries no coverage, staffing or group warnings for
either role. A GP reading a roster can judge cover themselves, and an app
that says "covered" when it is not is worse than one that says nothing.
"""

from datetime import date

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _html(client, day=TUE):
    PracticeSettings.load()
    return client.get(f"/rota/day/{day.isoformat()}/").content.decode()


def test_a_clinician_working_the_day_appears_with_both_parts(gp_client, gp_user):
    c = make_clinician("Emma Hall", user=gp_user)
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=rout)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Emma Hall" in html
    assert html.count("ROUT") >= 2


def test_a_clinician_on_leave_all_day_is_in_the_leave_group_not_the_roster(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Anwer Al-Hasani")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=al)
    resp = _html(gp_client)
    assert "Anwer Al-Hasani" in resp
    assert "On leave" in resp


def test_half_a_day_of_leave_keeps_the_clinician_in_the_roster(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Esther Lomas")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Esther Lomas" in html and "ROUT" in html


def test_someone_who_does_not_work_that_day_is_on_the_not_in_line(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nesreen Mayoub")
    make_pattern(c, weekdays=(0,))  # Mondays only; TUE is a Tuesday
    html = _html(gp_client)
    assert "Not in" in html and "Nesreen Mayoub" in html


def test_a_gp_sees_no_staffing_warnings(gp_client, gp_user):
    """The week grid warns. This screen never does, for either role."""
    make_clinician("Viewer", user=gp_user)
    html = _html(gp_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_an_admin_sees_no_staffing_warnings_either(admin_client):
    html = _html(admin_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_a_gp_does_not_see_unpublished_entries(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" not in _html(gp_client)


def test_an_admin_does_see_unpublished_entries(admin_client):
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" in _html(admin_client)


def test_a_bare_day_url_renders_today(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/")
    assert resp.status_code == 200
    assert date.today().strftime("%d").lstrip("0") in resp.content.decode()


def test_a_malformed_date_falls_back_to_today_like_the_grid_does(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/not-a-date/")
    assert resp.status_code == 200


def test_the_day_note_is_shown_to_everyone(gp_client, gp_user):
    from rota.models import DayNote
    make_clinician("Viewer", user=gp_user)
    DayNote.objects.create(day=TUE, text="Flu clinic in the back room")
    assert "Flu clinic in the back room" in _html(gp_client)
```

- [ ] **Step 2: Run and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view.py -v
```

Expected: every test fails with 404, because the route does not exist.

- [ ] **Step 3: Write the view**

Create `rota/views/day.py`:

```python
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (Clinician, ClosedDay, DayNote, LeaveRequest,
                         PatternSlot, PracticeSettings, RotaEntry, SessionType)
from rota.services import availability
from rota.services.cells import cell_state


@login_required
def day_view(request, day=None):
    try:
        target = date.fromisoformat(day) if day else date.today()
    except (TypeError, ValueError):
        # Matches how grid() treats a malformed ?week=: fall back rather than
        # raise, so the two screens behave alike on a mistyped URL.
        target = date.today()

    settings = PracticeSettings.load()
    closed_days = set(
        ClosedDay.objects.filter(day=target).values_list("day", flat=True))
    is_closed = (target in closed_days
                 or target.weekday() not in settings.open_weekday_list())

    entries = RotaEntry.objects.filter(day=target).select_related(
        "session_type", "clinician", "site")
    if not request.user.is_rota_admin:
        entries = entries.filter(is_published=True)
    entries = list(entries)

    by_clinician = {}
    for e in entries:
        by_clinician.setdefault(e.clinician_id, {})[e.part] = e

    partner = {}
    groups = {}
    for e in entries:
        if e.companion_group:
            groups.setdefault(e.companion_group, []).append(e)
    for pair in groups.values():
        if len(pair) == 2:
            a, b = pair
            partner[(a.clinician_id, a.part)] = b.clinician.name
            partner[(b.clinician_id, b.part)] = a.clinician.name

    active = list(Clinician.objects.filter(active=True).order_by("name"))
    pattern_rows = list(PatternSlot.objects.filter(clinician__in=active))
    approved_leave = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=target, end_date__gte=target,
    ).select_related("session_type")
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, approved_leave)

    roster, on_leave, not_in = [], [], []
    for c in active:
        if not resolver.in_service(c.id, target):
            continue
        mine = by_clinician.get(c.id, {})
        cells = [
            cell_state(c.id, target, part, entry=mine.get(part),
                       resolver=resolver, closed=is_closed,
                       partner=partner.get((c.id, part)))
            for part in ("AM", "PM")
        ]
        absence = SessionType.Category.ABSENCE
        if mine and all(e.session_type.category == absence for e in mine.values()):
            on_leave.append({"clinician": c, "cells": cells})
        elif mine or any(not cell["off"] for cell in cells):
            roster.append({"clinician": c, "cells": cells})
        else:
            not_in.append(c)

    return render(request, "rota/day.html", {
        "target": target,
        "is_closed": is_closed,
        "closed_reason": next(
            (cd.reason for cd in ClosedDay.objects.filter(day=target)), ""),
        "roster": roster,
        "on_leave": on_leave,
        "not_in": not_in,
        "in_count": len(roster),
        "leave_count": len(on_leave),
        "weekday_name": target.strftime("%A"),
        "day_note": DayNote.objects.filter(day=target).first(),
        "is_admin": request.user.is_rota_admin,
    })
```

- [ ] **Step 4: Add the route**

In `rota/urls.py`, import the module alongside the others and add two patterns immediately after the `rota/` grid line. Both carry the same name; Django's reverse picks by argument count:

```python
    path("rota/day/", day.day_view, name="day"),
    path("rota/day/<str:day>/", day.day_view, name="day"),
```

- [ ] **Step 5: Write the template**

Create `templates/rota/day.html`. Tasks 5 and 6 extend it; this is the roster and the two groups:

```html
{% extends "base.html" %}
{% block title %}{{ target|date:"D j M Y" }}{% endblock %}
{% block content %}
<div class="day-head">
  <div>
    <h1>{{ target|date:"D j M" }}</h1>
    <p class="day-count">{{ in_count }} in &middot; {{ leave_count }} on leave</p>
  </div>
</div>

{% if day_note %}<p class="day-note">{{ day_note.text }}</p>{% endif %}

<table class="day-roster">
  <caption class="visually-hidden">Who is working on {{ target|date:"j F Y" }}</caption>
  <thead>
    <tr><th scope="col">Clinician</th><th scope="col">AM</th><th scope="col">PM</th></tr>
  </thead>
  <tbody>
  {% for row in roster %}
    <tr>
      <th scope="row">{{ row.clinician.name }}</th>
      {% for cell in row.cells %}
      <td>
        {% if cell.entry %}
          <span class="chip tint-{{ cell.entry.session_type.colour }}">{{ cell.entry.session_type.code }}{% if cell.entry.site %}<span class="site-marker">{{ cell.entry.site.name|slice:":1" }}</span>{% endif %}</span>
          {% if cell.partner %}<span class="day-partner">with {{ cell.partner }}</span>{% endif %}
        {% elif cell.ghost_leave %}
          <span class="chip is-ghost tint-{{ cell.ghost_leave.colour }}">{{ cell.ghost_leave.code }}</span>
        {% else %}
          <span class="day-dash">&mdash;</span>
        {% endif %}
      </td>
      {% endfor %}
    </tr>
  {% endfor %}
  </tbody>
</table>

{% if on_leave %}
<h2 class="day-group">On leave</h2>
<table class="day-roster">
  <tbody>
  {% for row in on_leave %}
    <tr>
      <th scope="row">{{ row.clinician.name }}</th>
      {% for cell in row.cells %}
      <td>{% if cell.entry %}<span class="chip tint-{{ cell.entry.session_type.colour }}">{{ cell.entry.session_type.code }}</span>{% else %}<span class="day-dash">&mdash;</span>{% endif %}</td>
      {% endfor %}
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

{% if not_in %}
<p class="day-not-in">Not in {{ weekday_name }}s:
  {% for c in not_in %}{{ c.name }}{% if not forloop.last %}, {% endif %}{% endfor %}
</p>
{% endif %}
{% endblock %}
```

Check how `grid.html` writes a chip's tint class before you commit this — copy that form exactly rather than the `tint-{{ ... }}` shown here if it differs.

- [ ] **Step 6: Run the day view tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view.py -v
```

Expected: PASS, 12 tests.

- [ ] **Step 7: Run the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: 702 passed.

- [ ] **Step 8: Commit**

```bash
git add rota/views/day.py templates/rota/day.html rota/urls.py tests/test_day_view.py
git commit -m "feat: a day view showing who is on, and no judgement about it

One row per clinician with AM and PM as columns — the week grid narrowed
to one column, so anyone who can read the grid can read this. Carries no
coverage or staffing warnings for either role, deliberately."
```

---

### Task 5: The day view — pinned block, closed days, steppers

**Files:**
- Modify: `rota/views/day.py`
- Modify: `templates/rota/day.html`
- Test: `tests/test_day_view.py` (created in Task 4 — yours to extend)

**Interfaces:**
- Consumes: `SessionType.pin_on_day_view` (Task 2); the context keys Task 4 produced.
- Produces: context keys `pinned`, `prev_day`, `next_day`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_day_view.py`:

```python
# --------------------------------------------------------------- pinned ---

def test_a_pinned_type_appears_above_the_roster(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Amjad Mahmood")
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    make_entry(c, day=TUE, part="AM", session_type=duty)
    html = _html(gp_client)
    assert html.index("day-pinned") < html.index("day-roster")


def test_no_pinned_types_means_no_block_at_all(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Emma Hall")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert "day-pinned" not in _html(gp_client)


def test_a_pinned_type_with_nobody_on_it_shows_no_block(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    assert "day-pinned" not in _html(gp_client)


# --------------------------------------------------------------- closed ---

def test_a_closed_day_says_so_and_shows_no_roster(gp_client, gp_user):
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Emma Hall")
    make_pattern(c)
    ClosedDay.objects.create(day=TUE, reason="August bank holiday")
    html = _html(gp_client)
    assert "August bank holiday" in html
    assert "day-roster" not in html


def test_a_closed_day_still_shows_its_day_note(gp_client, gp_user):
    from rota.models import ClosedDay, DayNote
    make_clinician("Viewer", user=gp_user)
    ClosedDay.objects.create(day=TUE, reason="Bank holiday")
    DayNote.objects.create(day=TUE, text="Emergency line diverted")
    assert "Emergency line diverted" in _html(gp_client)


def test_a_weekend_is_closed_without_a_closedday_row(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    saturday = date(2026, 9, 12)
    assert saturday.weekday() == 5
    assert "day-roster" not in _html(gp_client, day=saturday)


# -------------------------------------------------------------- steppers ---

def test_the_next_link_from_friday_skips_the_weekend(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    friday = date(2026, 9, 11)
    assert friday.weekday() == 4
    html = _html(gp_client, day=friday)
    assert "/rota/day/2026-09-14/" in html


def test_the_stepper_skips_a_closed_day(gp_client, gp_user):
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    ClosedDay.objects.create(day=date(2026, 9, 9), reason="Training")
    html = _html(gp_client, day=TUE)  # Tue 8th; Wed 9th is closed
    assert "/rota/day/2026-09-10/" in html


def test_the_stepper_terminates_when_the_practice_has_no_open_weekdays(
        gp_client, gp_user):
    """open_weekdays = '' parses to [] and clean() accepts it. A stepper that
    walks forward looking for an open day would never find one."""
    make_clinician("Viewer", user=gp_user)
    s = PracticeSettings.load()
    s.open_weekdays = ""
    s.save()
    resp = gp_client.get(f"/rota/day/{TUE.isoformat()}/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view.py -v -k "pinned or closed or stepper or weekend"
```

Expected: FAIL on every one.

- [ ] **Step 3: Add the stepper helper**

At the top of `rota/views/day.py`, after the imports:

```python
from datetime import timedelta

_STEP_LIMIT = 14  # a fortnight: enough to clear Christmas, short enough to end


def _adjacent_open_day(target, delta, open_weekdays, closed):
    """The previous or next day the surgery is open.

    Bounded, because open_weekdays can legitimately be empty — it parses from
    a free-text field that clean() accepts blank — and an unbounded walk
    looking for an open day would then never return.
    """
    if not open_weekdays:
        return target + timedelta(days=delta)
    day = target
    for _ in range(_STEP_LIMIT):
        day += timedelta(days=delta)
        if day.weekday() in open_weekdays and day not in closed:
            return day
    return target + timedelta(days=delta)
```

- [ ] **Step 4: Wire the steppers and the pinned block into the view**

In `day_view`, replace the single-day `closed_days` lookup with one covering the stepper's range, and add the pinned list. Insert after `is_closed` is computed:

```python
    span = timedelta(days=_STEP_LIMIT)
    nearby_closed = set(ClosedDay.objects.filter(
        day__range=(target - span, target + span)
    ).values_list("day", flat=True))
    open_weekdays = set(settings.open_weekday_list())
    prev_day = _adjacent_open_day(target, -1, open_weekdays, nearby_closed)
    next_day = _adjacent_open_day(target, +1, open_weekdays, nearby_closed)
```

and change `is_closed` to read from `nearby_closed`:

```python
    is_closed = (target in nearby_closed
                 or target.weekday() not in open_weekdays)
```

Build the pinned list after `entries` is materialised:

```python
    pinned = sorted(
        (e for e in entries if e.session_type.pin_on_day_view),
        key=lambda e: (e.session_type.name, e.clinician.name, e.part),
    )
```

Add `"pinned": pinned`, `"prev_day": prev_day` and `"next_day": next_day` to the context dict, and delete the now-unused `closed_days` variable.

Leave `closed_reason` exactly as Task 4 wrote it. It is one indexed lookup on a unique column, on the only page that shows it, and folding it into `nearby_closed` would mean carrying reasons for a fortnight of days to render one.

- [ ] **Step 5: Extend the template**

In `templates/rota/day.html`, add the stepper to `.day-head`, and the pinned block and closed-day branch around the roster:

```html
<div class="day-head">
  <div>
    <h1>{{ target|date:"D j M" }}</h1>
    <p class="day-count">{{ in_count }} in &middot; {{ leave_count }} on leave</p>
  </div>
  <div class="day-step">
    <a href="/rota/day/{{ prev_day|date:'Y-m-d' }}/" class="btn" rel="prev">&larr;<span class="visually-hidden"> previous open day</span></a>
    <a href="/rota/day/{{ next_day|date:'Y-m-d' }}/" class="btn" rel="next">&rarr;<span class="visually-hidden"> next open day</span></a>
  </div>
</div>

{% if day_note %}<p class="day-note">{{ day_note.text }}</p>{% endif %}

{% if is_closed %}
  <p class="day-closed">{% if closed_reason %}{{ closed_reason }}{% else %}Surgery closed{% endif %}</p>
{% else %}
  {% if pinned %}
  <div class="day-pinned">
    {% for e in pinned %}
    <div class="day-pin-row">
      <span class="day-pin-who">{{ e.clinician.name }}</span>
      <span class="day-pin-part">{{ e.part }}</span>
      <span class="chip tint-{{ e.session_type.colour }}">{{ e.session_type.code }}{% if e.site %}<span class="site-marker">{{ e.site.name|slice:":1" }}</span>{% endif %}</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  ... the existing roster table, on-leave table and not-in line ...
{% endif %}
```

Move the roster table, the on-leave block and the not-in line inside the `{% else %}` branch. Do not duplicate them.

- [ ] **Step 6: Run the day view tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view.py -v
```

Expected: PASS, 21 tests.

- [ ] **Step 7: Run the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: 711 passed.

- [ ] **Step 8: Commit**

```bash
git add rota/views/day.py templates/rota/day.html tests/test_day_view.py
git commit -m "feat: day view pins the critical roles, and knows about closures

Steppers move to the next open day rather than the next calendar one, and
they terminate when open_weekdays is blank — which clean() permits."
```

---

### Task 6: Day view styling

**Files:**
- Modify: `static/css/screens.css` (a new `day view` section, before the `reports` section)
- Test: `tests/test_day_view_css.py` (new)

**Interfaces:**
- Consumes: the class names Tasks 4 and 5 put in the template — `.day-head`, `.day-count`, `.day-step`, `.day-note`, `.day-closed`, `.day-pinned`, `.day-pin-row`, `.day-pin-who`, `.day-pin-part`, `.day-roster`, `.day-partner`, `.day-dash`, `.day-group`, `.day-not-in`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_day_view_css.py`:

```python
"""The day view's styling, checked for the two failures this project repeats.

Colour literals (every colour must come from tokens.css) and rules that are
written but never apply. Nothing here proves a browser paints the result.
"""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "css" / "screens.css").read_text()


def test_the_day_view_section_exists():
    assert "day view" in CSS


def test_every_class_the_template_uses_is_styled():
    for cls in (".day-head", ".day-count", ".day-step", ".day-closed",
                ".day-pinned", ".day-roster", ".day-dash", ".day-not-in"):
        assert cls in CSS, f"{cls} appears in day.html but nowhere in screens.css"


def test_no_colour_literals_in_the_day_view_rules():
    start = CSS.index("day view")
    end = CSS.index("reports", start)
    section = CSS[start:end]
    literals = re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", section)
    assert not literals, f"day view CSS hard-codes colours: {literals}"
```

- [ ] **Step 2: Run and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view_css.py -v
```

Expected: FAIL on `test_the_day_view_section_exists`.

- [ ] **Step 3: Write the CSS**

In `static/css/screens.css`, immediately before the `/* --- reports --- */` banner, add:

```css
/* ---------------------------------------------------------- day view --- */

.day-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.day-count {
  color: var(--muted);
  font-size: var(--fs-sm);
  margin: var(--sp-1) 0 0;
}

.day-step { display: flex; gap: var(--sp-2); flex: none; }

.day-note {
  background: var(--sunken);
  border-left: 3px solid var(--accent);
  padding: var(--sp-3) var(--sp-4);
  margin: 0 0 var(--sp-4);
  border-radius: var(--r-sm);
}

.day-closed {
  color: var(--muted);
  background: var(--sunken);
  padding: var(--sp-5);
  border-radius: var(--r-md);
  text-align: center;
  margin: 0;
}

.day-pinned {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-5);
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--r-md);
}

.day-pin-row { display: flex; align-items: center; gap: var(--sp-3); }
.day-pin-who { flex: 1; font-weight: 600; }
.day-pin-part { color: var(--muted); font-size: var(--fs-sm); }

.day-roster { width: 100%; border-collapse: collapse; }

.day-roster th,
.day-roster td {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
}

.day-roster thead th {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--muted);
}

.day-roster tbody th { font-weight: 500; }
.day-roster td { width: 38%; }

.day-partner {
  display: block;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.day-dash { color: var(--muted); }

.day-group {
  font-size: var(--fs-lg);
  margin: var(--sp-6) 0 var(--sp-2);
}

.day-not-in {
  color: var(--muted);
  font-size: var(--fs-sm);
  margin: var(--sp-5) 0 0;
}
```

- [ ] **Step 4: Run the CSS test**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_day_view_css.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Run the cascade and contrast audits**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_css_cascade.py tests/test_chrome_contrast.py -v
```

Expected: PASS. These parse the sheet you just edited; a colour literal or a malformed rule fails here.

- [ ] **Step 6: Run the full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add static/css/screens.css tests/test_day_view_css.py
git commit -m "style: the day view"
```

Expected: 714 passed.

---

### Task 7: My Schedule — view, template and styling

The view and the template are one deliverable here, not two. The rewritten
view drops the `entries` context key the current template renders, so a task
that changed only the view would end with `tests/test_my_schedule.py` red —
and every task in this plan ends on a green suite.

The current view hands the template a flat 28-day queryset. Replace that with the five sections the spec sets out, in order.

**Files:**
- Modify: `rota/views/my_schedule.py`
- Modify: `templates/rota/my_schedule.html` (rewrite)
- Modify: `static/css/screens.css` (the existing `my schedule` section)
- Test: `tests/test_my_schedule_weeks.py` (new — `tests/test_my_schedule.py` is pre-existing and must not be touched)

**Interfaces:**
- Consumes: `rota.services.leave.leave_summary(clinician, today) -> {"entitlement", "taken", "booked", "remaining"}`.
- Produces: context keys `today_cells`, `today_state`, `weeks`, `leave`, `my_requests`, `to_accept`. Task 8 renders them.
  `weeks` is a list of `{"heading": str, "count_label": str, "days": [{"day": date, "am": entry|None, "pm": entry|None}]}`.
  `today_state` is one of `"working"`, `"not_in"`, `"closed"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_my_schedule_weeks.py`:

```python
"""My Schedule's agenda: four weeks as blocks, open days only.

Two rules from the spec that pull in opposite directions and are easy to
conflate:
  - a day the SURGERY is closed is not shown at all
  - a day you do not work, on an open day, IS shown, as dashes
The first is not your day off. The second is.
"""

from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _ctx(client):
    PracticeSettings.load()
    return client.get("/me/").context


def test_there_are_four_week_blocks(gp_client, gp_user):
    make_clinician(user=gp_user)
    assert len(_ctx(gp_client)["weeks"]) == 4


def test_the_first_block_is_headed_this_week(gp_client, gp_user):
    make_clinician(user=gp_user)
    assert _ctx(gp_client)["weeks"][0]["heading"] == "This week"


def test_later_blocks_are_headed_with_their_monday(gp_client, gp_user):
    make_clinician(user=gp_user)
    weeks = _ctx(gp_client)["weeks"]
    assert weeks[1]["heading"].startswith("Week of ")


def test_a_closed_day_is_absent_from_its_block(gp_client, gp_user):
    make_clinician(user=gp_user)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    # pick an open weekday in this week that is not today
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    days = [d["day"] for d in _ctx(gp_client)["weeks"][0]["days"]]
    assert victim not in days


def test_an_open_day_you_do_not_work_is_present_as_dashes(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=(0,))  # Mondays only
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    tuesday = monday + timedelta(days=1)
    row = next(d for d in _ctx(gp_client)["weeks"][0]["days"]
               if d["day"] == tuesday)
    assert row["am"] is None and row["pm"] is None


def test_the_count_label_counts_sessions(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=monday, part="AM", session_type=rout)
    make_entry(c, day=monday, part="PM", session_type=rout)
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "2 sessions"


def test_one_session_is_singular(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_entry(c, day=monday, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "1 session"


def test_a_week_of_nothing_but_absence_says_so(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    for n in range(5):
        for part in ("AM", "PM"):
            make_entry(c, day=monday + timedelta(days=n), part=part,
                       session_type=al)
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "On leave all week"


def test_today_says_not_in_when_you_have_no_sessions(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=())
    assert _ctx(gp_client)["today_state"] == "not_in"


def test_today_says_closed_when_the_surgery_is_shut(gp_client, gp_user):
    make_clinician(user=gp_user)
    ClosedDay.objects.create(day=date.today(), reason="Bank holiday")
    assert _ctx(gp_client)["today_state"] == "closed"


def test_today_is_working_when_you_have_a_session(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    if today.weekday() > 4:
        pytest.skip("weekend: the practice is closed and this case cannot arise")
    make_entry(c, day=today, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert _ctx(gp_client)["today_state"] == "working"
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py -v
```

Expected: FAIL — `KeyError: 'weeks'`.

- [ ] **Step 3: Rewrite the view**

Replace the body of `my_schedule` in `rota/views/my_schedule.py`:

```python
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (ClosedDay, LeaveRequest, PracticeSettings, RotaEntry,
                         SessionType, SwapRequest)
from rota.services import leave as leave_svc

WEEKS_SHOWN = 4


def _blocks(clinician, today, open_weekdays, closed, entries_by):
    """Four Monday-based blocks of open days, with a count for each."""
    monday = today - timedelta(days=today.weekday())
    absence = SessionType.Category.ABSENCE
    blocks = []
    for index in range(WEEKS_SHOWN):
        start = monday + timedelta(weeks=index)
        days = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            if day.weekday() not in open_weekdays or day in closed:
                continue
            days.append({
                "day": day,
                "am": entries_by.get((day, "AM")),
                "pm": entries_by.get((day, "PM")),
            })
        sessions = [e for row in days
                    for e in (row["am"], row["pm"]) if e is not None]
        if sessions and all(e.session_type.category == absence
                            for e in sessions):
            label = "On leave all week"
        else:
            n = len(sessions)
            label = f"{n} session" if n == 1 else f"{n} sessions"
        blocks.append({
            "heading": "This week" if index == 0
                       else f"Week of {start.strftime('%-d %b')}",
            "count_label": label,
            "days": days,
        })
    return blocks


@login_required
def my_schedule(request):
    clinician = getattr(request.user, "clinician", None)
    if clinician is None:
        return render(request, "rota/my_schedule.html", {"clinician": None})

    today = date.today()
    settings = PracticeSettings.load()
    open_weekdays = set(settings.open_weekday_list())
    monday = today - timedelta(days=today.weekday())
    last = monday + timedelta(weeks=WEEKS_SHOWN) - timedelta(days=1)

    closed = set(ClosedDay.objects.filter(
        day__range=(monday, last)).values_list("day", flat=True))

    entries = RotaEntry.objects.filter(
        clinician=clinician, is_published=True, day__range=(monday, last),
    ).select_related("session_type", "site")
    entries_by = {(e.day, e.part): e for e in entries}

    if today in closed or today.weekday() not in open_weekdays:
        today_state = "closed"
    elif entries_by.get((today, "AM")) or entries_by.get((today, "PM")):
        today_state = "working"
    else:
        today_state = "not_in"

    return render(request, "rota/my_schedule.html", {
        "clinician": clinician,
        "today": today,
        "today_state": today_state,
        "today_cells": [entries_by.get((today, "AM")),
                        entries_by.get((today, "PM"))],
        "today_closed_reason": next(
            (cd.reason for cd in ClosedDay.objects.filter(day=today)), ""),
        "weeks": _blocks(clinician, today, open_weekdays, closed, entries_by),
        "leave": leave_svc.leave_summary(clinician, today),
        "my_requests": list(LeaveRequest.objects.filter(
            clinician=clinician, status=LeaveRequest.Status.PENDING
        ).select_related("session_type")),
        "my_swaps": list(SwapRequest.objects.filter(
            proposer=clinician
        ).exclude(status=SwapRequest.Status.DECLINED
                  ).select_related("colleague")[:10]),
        "to_accept": SwapRequest.objects.filter(
            colleague=clinician, status=SwapRequest.Status.PROPOSED
        ).select_related("proposer"),
    })
```

`%-d` is a glibc extension and is correct on this Linux deployment; it prints "7 Sep" rather than "07 Sep".

- [ ] **Step 4: Run the new tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py -v
```

Expected: PASS, 11 tests.

- [ ] **Step 5: Write the rendering tests**

Append to `tests/test_my_schedule_weeks.py`:

```python
# ------------------------------------------------------------- rendering ---

def _html(client):
    PracticeSettings.load()
    return client.get("/me/").content.decode()


def test_the_five_column_table_is_gone(gp_client, gp_user):
    """The old agenda was a table in a sideways scroller, which is the thing
    this phase exists to remove from this screen."""
    make_clinician(user=gp_user)
    assert "table-scroll" not in _html(gp_client)


def test_the_agenda_comes_before_the_leave_balance(gp_client, gp_user):
    """The old order made a GP scroll past their leave balance to find out
    where they are working tomorrow."""
    make_clinician(user=gp_user)
    html = _html(gp_client)
    assert html.index("ms-weeks") < html.index("ms-balance")


def test_a_swap_awaiting_you_comes_before_everything(gp_client, gp_user):
    from rota.models import SwapRequest
    from tests.factories import MON
    me = make_clinician("Me Person", user=gp_user)
    other = make_clinician("Other Person")
    SwapRequest.objects.create(
        proposer=other, proposer_day=MON, proposer_part="AM",
        colleague=me, colleague_day=MON, colleague_part="PM")
    html = _html(gp_client)
    assert html.index("ms-awaiting") < html.index("ms-today")


def test_not_in_today_is_worded_for_a_human(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=())
    if date.today().weekday() > 4:
        pytest.skip("weekend: today_state is 'closed', not 'not_in'")
    assert "Not in today" in _html(gp_client)
```

- [ ] **Step 6: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py -v -k "table_scroll or before or worded"
```

Expected: FAIL.

- [ ] **Step 7: Rewrite the template**

Replace `templates/rota/my_schedule.html` entirely:

```html
{% extends "base.html" %}
{% block title %}My schedule{% endblock %}
{% block content %}
{% if not clinician %}
<p>No clinician profile is linked to this account. Ask an admin to link one.</p>
{% else %}
<div class="page-head">
  <h1>{{ clinician.name }}</h1>
  <div class="form-actions">
    <a href="/me/leave/new/" class="btn">Request leave</a>
    <a href="/me/swap/new/" class="btn">Propose a swap</a>
  </div>
</div>

{% if to_accept %}
<section class="ms-awaiting">
  <h2>Waiting for you</h2>
  {% for s in to_accept %}
  <div class="card">
    <p>{{ s.proposer.name }} proposes swapping their
       {{ s.proposer_day|date:"D j M" }} {{ s.proposer_part }} with your
       {{ s.colleague_day|date:"D j M" }} {{ s.colleague_part }}. {{ s.message }}</p>
    <div class="form-actions">
      <form method="post" action="/me/swap/{{ s.pk }}/accept/">
        {% csrf_token %}<button type="submit" class="btn btn-primary">Accept</button>
      </form>
      <form method="post" action="/me/swap/{{ s.pk }}/decline/">
        {% csrf_token %}<button type="submit" class="btn">Decline</button>
      </form>
    </div>
  </div>
  {% endfor %}
</section>
{% endif %}

<section class="ms-today">
  <h2 class="ms-today-label">Today &middot; {{ today|date:"D j M" }}</h2>
  {% if today_state == "closed" %}
    <p class="ms-today-note">{% if today_closed_reason %}{{ today_closed_reason }}{% else %}Surgery closed{% endif %}</p>
  {% elif today_state == "not_in" %}
    <p class="ms-today-note">Not in today.</p>
  {% else %}
    <div class="ms-today-cells">
      {% for e in today_cells %}
        {% if e %}<span class="chip tint-{{ e.session_type.colour }}">{{ e.session_type.code }}{% if e.site %}<span class="site-marker">{{ e.site.name|slice:":1" }}</span>{% endif %}</span>
        {% else %}<span class="ms-dash">&mdash;</span>{% endif %}
      {% endfor %}
    </div>
  {% endif %}
</section>

<section class="ms-weeks">
  <h2>Next four weeks</h2>
  {% for week in weeks %}
  <div class="ms-week">
    <div class="ms-week-head">
      <span>{{ week.heading }}</span>
      <span class="ms-week-count">{{ week.count_label }}</span>
    </div>
    {% for row in week.days %}
    <div class="ms-day">
      <span class="ms-date"><b>{{ row.day|date:"D j" }}</b> {{ row.day|date:"M" }}</span>
      <span class="ms-cells">
        {% if row.am %}<span class="chip tint-{{ row.am.session_type.colour }}">{{ row.am.session_type.code }}{% if row.am.site %}<span class="site-marker">{{ row.am.site.name|slice:":1" }}</span>{% endif %}</span>{% else %}<span class="ms-dash">&mdash;</span>{% endif %}
        {% if row.pm %}<span class="chip tint-{{ row.pm.session_type.colour }}">{{ row.pm.session_type.code }}{% if row.pm.site %}<span class="site-marker">{{ row.pm.site.name|slice:":1" }}</span>{% endif %}</span>{% else %}<span class="ms-dash">&mdash;</span>{% endif %}
      </span>
    </div>
    {% empty %}
    <p class="empty">Surgery closed all week.</p>
    {% endfor %}
  </div>
  {% endfor %}
</section>

<section class="ms-leave">
  <h2>Leave</h2>
  <div class="ms-balance">
    <div><span class="ms-v">{{ leave.entitlement }}</span><span class="ms-k">Entitled</span></div>
    <div><span class="ms-v">{{ leave.taken }}</span><span class="ms-k">Taken</span></div>
    <div><span class="ms-v">{{ leave.booked }}</span><span class="ms-k">Booked</span></div>
    <div><span class="ms-v">{{ leave.remaining }}</span><span class="ms-k">Left</span></div>
  </div>
</section>

{% if my_requests or my_swaps %}
<section class="ms-requests">
  <h2>Your requests</h2>
  {% for r in my_requests %}
  <div class="ms-day">
    <span class="ms-date"><b>{{ r.start_date|date:"j M" }}</b>&ndash;{{ r.end_date|date:"j M" }}</span>
    <span class="ms-cells"><span class="chip tint-{{ r.session_type.colour }}">{{ r.session_type.code }}</span>
      <span class="ms-status">{{ r.get_status_display }}</span></span>
  </div>
  {% endfor %}
  {% for s in my_swaps %}
  <div class="ms-day">
    <span class="ms-date"><b>{{ s.proposer_day|date:"j M" }}</b></span>
    <span class="ms-cells">Swap with {{ s.colleague.name }}
      <span class="ms-status">{{ s.get_status_display }}</span></span>
  </div>
  {% endfor %}
</section>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 8: Replace the `my schedule` CSS section**

In `static/css/screens.css`, replace the whole existing `/* --- my schedule --- */` section with:

```css
/* ------------------------------------------------------- my schedule --- */

.ms-awaiting, .ms-today, .ms-weeks, .ms-leave, .ms-requests {
  margin-bottom: var(--sp-6);
}

.ms-today-label { font-size: var(--fs-lg); margin: 0 0 var(--sp-2); }

.ms-today-note, .ms-today-cells {
  background: var(--accent-soft);
  border: 1px solid var(--accent);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  margin: 0;
}

.ms-today-cells { display: flex; gap: var(--sp-2); align-items: center; }

.ms-week { margin-bottom: var(--sp-5); }

.ms-week-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: var(--fs-xs);
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--muted);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--hairline);
}

.ms-week-count { font-weight: 500; letter-spacing: 0; text-transform: none; }

.ms-day {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-height: var(--row-h);
  padding: var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}

.ms-day:last-child { border-bottom: 0; }

.ms-date {
  flex: none;
  width: 5.5rem;
  font-size: var(--fs-sm);
  color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}

.ms-cells { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
.ms-dash { color: var(--muted); }
.ms-status { color: var(--muted); font-size: var(--fs-sm); }

.ms-balance {
  display: flex;
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: var(--r-md);
  overflow: hidden;
}

.ms-balance > div {
  flex: 1;
  padding: var(--sp-3) var(--sp-2);
  text-align: center;
  border-right: 1px solid var(--hairline);
}

.ms-balance > div:last-child { border-right: 0; }

.ms-v {
  display: block;
  font-size: var(--fs-xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.ms-k { font-size: var(--fs-xs); color: var(--muted); }
```

- [ ] **Step 9: Run everything that touches this screen**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py tests/test_my_schedule.py tests/test_css_cascade.py tests/test_chrome_contrast.py -v
```

Expected: PASS. `tests/test_my_schedule.py` is pre-existing and unedited — if it fails, the template is not rendering something a GP relied on, and the template is what changes.

- [ ] **Step 10: Run the full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/views/my_schedule.py templates/rota/my_schedule.html static/css/screens.css tests/test_my_schedule_weeks.py
git commit -m "feat: My Schedule reads on a phone

Five sections in the order a GP needs them. A closed surgery is not your
day off so it is not your row; an open day you do not work is, so it stays
and shows dashes. The sideways-scrolling five-column table is gone."
```

Expected: 729 passed.

---

### Task 8: The bottom tab bar

The one media query this phase adds, and the guard that proves it applies.

**Files:**
- Modify: `templates/base.html`
- Modify: `static/css/components.css` (the `.tabbar` component)
- Modify: `static/css/screens.css` (the `@media (max-width: 640px)` block)
- Test: `tests/test_responsive_nav.py` (new)

**Interfaces:**
- Consumes: nothing. Produces the `/rota/day/` link that makes Task 4's route reachable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_responsive_nav.py`:

```python
"""The bottom tab bar, and proof that its rules are not inert.

Phase 1's repeat failure was CSS that looked right and never applied. The
tab bar is invisible above 640px by design, so "it is in the stylesheet" is
exactly the kind of evidence that has been wrong here before. These tests
assert the rules sit INSIDE the media query, using the cascade parser that
learned to read at-rules in Task 1.

What this cannot prove: that a browser paints a usable bar at 375px. That is
a live measurement, and it is still outstanding.
"""

import re
from pathlib import Path

import pytest

from tests.test_css_cascade import RULES

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text()
COMPONENTS = (ROOT / "static" / "css" / "components.css").read_text()
SCREENS = (ROOT / "static" / "css" / "screens.css").read_text()

BREAKPOINT = "(max-width: 640px)"


def _rules_for(selector):
    return [r for r in RULES if r.selector == selector]


def test_the_bar_is_in_the_markup():
    assert 'class="tabbar"' in BASE


def test_the_bar_links_to_the_day_view():
    assert "/rota/day/" in BASE


def test_the_bar_is_hidden_by_default():
    """Above the breakpoint there is no tab bar at all, so its base rule must
    hide it rather than relying on the media query to do so."""
    base = [r for r in _rules_for(".tabbar") if r.media is None]
    assert base, ".tabbar has no top-level rule"
    assert any(r.declarations.get("display") == "none" for r in base)


def test_the_bar_is_revealed_only_inside_the_breakpoint():
    revealed = [r for r in _rules_for(".tabbar")
                if r.media == BREAKPOINT
                and r.declarations.get("display") not in (None, "none")]
    assert revealed, (
        ".tabbar is never shown inside the 640px media query — the rule is "
        "inert and the bar can never appear"
    )


def test_the_top_nav_is_hidden_inside_the_breakpoint():
    hidden = [r for r in _rules_for(".nav")
              if r.media == BREAKPOINT
              and r.declarations.get("display") == "none"]
    assert hidden, "the top nav is never hidden, so both navs show at once"


def test_the_body_clears_the_fixed_bar():
    """A fixed bar overlays the end of the page unless something reserves
    space for it."""
    padded = [r for r in RULES
              if r.media == BREAKPOINT
              and "padding-bottom" in r.declarations
              and r.selector in ("body", ".main")]
    assert padded, "nothing reserves space for the fixed bar; content is hidden behind it"


def test_touch_targets_are_large_enough():
    """WCAG 2.5.8 and plain usability: 44px."""
    sized = [r for r in RULES
             if r.selector.startswith(".tabbar")
             and ("min-height" in r.declarations or "height" in r.declarations)]
    assert sized, ".tabbar items have no height, so touch target size is unknowable"
    values = [r.declarations.get("min-height") or r.declarations.get("height")
              for r in sized]
    assert any(
        v and v.endswith("px") and int(re.sub(r"\D", "", v)) >= 44
        for v in values
    ), f"no tab bar rule reaches a 44px touch target: {values}"


def test_there_is_exactly_one_width_breakpoint_in_the_project():
    """The spec allows one. More than one means someone invented a second
    mental model for narrow screens."""
    queries = set()
    for sheet in (COMPONENTS, SCREENS):
        queries.update(re.findall(r"@media\s*\(([^)]*width[^)]*)\)", sheet))
    assert queries == {"max-width: 640px"}, f"unexpected breakpoints: {queries}"


@pytest.mark.django_db
def test_the_more_menu_needs_no_javascript(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/rota/day/").content.decode()
    assert "<details" in html and "<summary" in html
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_responsive_nav.py -v
```

Expected: FAIL on every test.

- [ ] **Step 3: Add the bar to `base.html`**

Immediately before `</body>` in `templates/base.html`:

```html
<nav class="tabbar" aria-label="Sections">
  <a href="/rota/" class="tabbar-item{% if request.path == '/rota/' %} is-active{% endif %}">Week</a>
  <a href="/rota/day/" class="tabbar-item{% if '/rota/day/' in request.path %} is-active{% endif %}">Day</a>
  <a href="/me/" class="tabbar-item{% if request.path == '/me/' %} is-active{% endif %}">Me</a>
  <details class="tabbar-more">
    <summary class="tabbar-item">More</summary>
    <div class="tabbar-sheet">
      {% if user.is_rota_admin %}
        <a href="/requests/" class="tabbar-link">Requests</a>
        <a href="/rota/fill/" class="tabbar-link">Assisted fill</a>
      {% endif %}
      <a href="/reports/fairness/" class="tabbar-link">Reports</a>
      <button type="button" id="theme-toggle-mobile" class="tabbar-link">Theme</button>
      {% if user.is_authenticated %}
        <span class="tabbar-user">{{ user.email }}</span>
        <form method="post" action="/accounts/logout/">{% csrf_token %}<button class="tabbar-link">Log out</button></form>
      {% endif %}
    </div>
  </details>
</nav>
```

Also add a `Day` link to the existing top `.nav`, after `Week`, so the day view is reachable on desktop:

```html
  <a href="/rota/day/" class="nav-link{% if '/rota/day/' in request.path %} is-active{% endif %}">Day</a>
```

- [ ] **Step 4: Check the theme toggle still binds**

`static/js/theme.js` binds by the id `theme-toggle`. The mobile button uses `theme-toggle-mobile`, so it will not work until the script binds both. Read `static/js/theme.js`, and change its lookup from `getElementById("theme-toggle")` to `document.querySelectorAll('[id^="theme-toggle"]')` with a loop attaching the same handler, keeping every existing behaviour (the `try`/`catch` around `localStorage` and the system→light→dark cycle) untouched.

Run the pre-existing toggle tests before going further:

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_theme_toggle.py -v
```

Expected: PASS, unchanged.

- [ ] **Step 5: Add the `.tabbar` component**

At the end of `static/css/components.css`:

```css
/* ------------------------------------------------------------ tab bar --- */
/* Hidden here and revealed only inside the 640px block in screens.css. The
   default is `display: none` rather than the reverse, so a stylesheet that
   somehow loses the media query hides the bar instead of stranding it in the
   middle of a desktop page. */

.tabbar { display: none; }

.tabbar-item {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 48px;
  font-size: var(--fs-sm);
  color: var(--muted);
  text-decoration: none;
  cursor: pointer;
  list-style: none;
}

.tabbar-item.is-active {
  color: var(--accent);
  font-weight: 700;
  box-shadow: inset 0 2px 0 var(--accent);
}

.tabbar-item:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

.tabbar-sheet {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-3);
  background: var(--surface);
  border-top: 1px solid var(--hairline);
}

.tabbar-link {
  display: flex;
  align-items: center;
  min-height: 44px;
  padding: 0 var(--sp-3);
  background: none;
  border: 0;
  font: inherit;
  color: var(--ink);
  text-decoration: none;
  text-align: left;
  cursor: pointer;
}

.tabbar-user { color: var(--muted); font-size: var(--fs-sm); padding: 0 var(--sp-3); }
```

- [ ] **Step 6: Add the media query**

At the end of `static/css/screens.css`:

```css
/* ---------------------------------------------------------- narrow --- */
/* The project's only width breakpoint. Below it the top nav is replaced by
   a fixed bottom bar; above it nothing on any screen changes. */

@media (max-width: 640px) {
  .nav { display: none; }

  .tabbar {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    position: fixed;
    inset: auto 0 0 0;
    z-index: 20;
    background: var(--surface);
    border-top: 1px solid var(--hairline);
  }

  .tabbar-more { position: relative; }

  .tabbar-more[open] .tabbar-sheet {
    position: absolute;
    inset: auto 0 100% auto;
    min-width: 12rem;
    border: 1px solid var(--hairline);
    border-radius: var(--r-md) var(--r-md) 0 0;
    box-shadow: 0 -2px 12px var(--shadow);
  }

  body { padding-bottom: 64px; }

  .main { padding-left: var(--sp-4); padding-right: var(--sp-4); }

  .day-roster td { width: auto; }
}
```

- [ ] **Step 7: Run the responsive tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_responsive_nav.py -v
```

Expected: PASS, 9 tests.

- [ ] **Step 8: Run the full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add templates/base.html static/css/components.css static/css/screens.css static/js/theme.js tests/test_responsive_nav.py
git commit -m "feat: a bottom tab bar below 640px

The project's first width breakpoint, with the tab bar's reveal asserted to
sit inside it — Phase 1's repeat failure was CSS that read correctly and
never applied, and a bar that is invisible above 640px by design is exactly
where that failure hides."
```

Expected: 738 passed.

---

### Task 9: Query counts, hygiene, and the live check

Both new screens loop over clinicians and days. Pin their query counts before someone adds a `select_related` and nobody notices it was needed.

**Files:**
- Test: `tests/test_phase2_queries.py` (new)

- [ ] **Step 1: Write the tests**

Create `tests/test_phase2_queries.py`:

```python
"""Query counts and rendered-page hygiene for the two new screens.

The counts are asserted as "does not grow", not as an exact number: an exact
count is a tripwire that fires on every unrelated change, and what matters is
that adding a clinician does not add a query.
"""

from datetime import date, timedelta

import pytest

from rota.models import DayNote, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)

LEAKED = ["{#", "#}", "{%", "TODO:", "FIXME:", "XXX:", "vestigial"]


def _populate(n, day=TUE):
    rout = make_session_type("Routine", code="ROUT")
    for i in range(n):
        c = make_clinician(f"Clinician {i:02d}")
        make_pattern(c)
        make_entry(c, day=day, part="AM", session_type=rout)
        make_entry(c, day=day, part="PM", session_type=rout)


def test_the_day_view_does_not_query_per_clinician(gp_client, gp_user,
                                                   django_assert_num_queries):
    PracticeSettings.load()
    make_clinician("Viewer", user=gp_user)
    _populate(3)
    url = f"/rota/day/{TUE.isoformat()}/"
    gp_client.get(url)  # warm caches

    with django_assert_num_queries(None) as captured:
        gp_client.get(url)
    baseline = len(captured)

    _populate(12, day=TUE)
    with django_assert_num_queries(baseline):
        gp_client.get(url)


def test_my_schedule_does_not_query_per_week(gp_client, gp_user,
                                             django_assert_num_queries):
    PracticeSettings.load()
    c = make_clinician(user=gp_user)
    make_pattern(c)
    gp_client.get("/me/")

    with django_assert_num_queries(None) as captured:
        gp_client.get("/me/")
    baseline = len(captured)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rout = make_session_type("Routine", code="ROUT")
    for n in range(20):
        day = monday + timedelta(days=n)
        if day.weekday() < 5:
            make_entry(c, day=day, part="AM", session_type=rout)

    with django_assert_num_queries(baseline):
        gp_client.get("/me/")


@pytest.mark.parametrize("url", ["/rota/day/", "/me/"])
def test_no_developer_notes_reach_the_page(admin_client, url):
    PracticeSettings.load()
    DayNote.objects.create(day=date.today(), text="A normal note")
    html = admin_client.get(url).content.decode()
    for frag in LEAKED:
        assert frag not in html, f"{url} renders {frag!r} to the page"
```

- [ ] **Step 2: Run them**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_phase2_queries.py -v
```

Expected: the two count tests fail if either view queries per row. If they do, add `select_related` to the offending queryset in `rota/views/day.py` or `rota/views/my_schedule.py` — never relax the assertion.

- [ ] **Step 3: Run the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: 741 passed, "No changes detected".

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase2_queries.py
git commit -m "test: query counts and page hygiene for the day view and My Schedule"
```

- [ ] **Step 5: The live check**

Everything above is read out of source text. Nothing has proved a browser paints a usable screen at 375px, and Phase 1 shipped four defects of exactly that shape.

Start the dev server, open the app at a 375px viewport, and check by measurement rather than by eye:

1. The tab bar is fixed to the bottom, all four items reachable, and no page content is hidden behind it.
2. "More" opens upward and its items are tappable without the sheet running off-screen.
3. The day roster's three columns fit without the page scrolling sideways — measure `document.documentElement.scrollWidth` against `clientWidth`.
4. My Schedule's week blocks and the leave strip fit at 375px.
5. Both screens in dark mode, and with the theme toggle in each of its three states.
6. At 641px the top nav is back and the tab bar is gone.

Record what you measured in the task report. **A visual check that says "looks fine" is not a measurement** — this project has been wrong that way before.

---

## Self-review

**Spec coverage.** Day view route and fallback: Task 4. Header, counts, steppers: Tasks 4 and 5. Closed days: Task 5. Pinned block and the new field: Tasks 2 and 5. Roster, on-leave split, not-in line, day note: Task 4. Ghost inheritance: Task 3. My Schedule's five sections, week blocks, counts, dashes, closed-day omission, "Not in today": Task 7. Tab bar: Task 8. The architecture extraction: Task 3. Testing including the inert-CSS guard and the live check: Tasks 6, 8 and 9. The cascade tripwire the spec names: Task 1.

**Not covered by any task, deliberately:** the `/admin/` config fix giving Routine – PMC its own code, which the spec files as a prerequisite rather than code; and whether ghost chips should be visible to non-admins, which the spec defers.

**Type consistency.** `cell_state(clinician_id, day, part, *, entry, resolver, closed, partner=None)` is defined in Task 3 and called with that exact signature in Tasks 3 and 4. `pin_on_day_view` is spelled identically in Tasks 2, 5 and the docs. Context keys `weeks`, `today_state`, `today_cells`, `my_requests` are produced and consumed within Task 7 under the same names. `RULES` and `Rule.media` come from Task 1 and are imported in Task 8.

**Known ordering constraint.** Task 1 must precede Tasks 6, 7 and 8, all of which write CSS its parser reads; Task 8 imports `Rule.media` directly. Task 2 must precede Task 5. Task 3 must precede Task 4.

**A defect this review found and fixed.** The view and template for My Schedule were originally two tasks. They cannot be: the rewritten view drops the `entries` context key the current template renders, so the first of the pair would have ended with `tests/test_my_schedule.py` red. They are one task now. Every task in this plan ends on a green suite, and any task that cannot is drawn wrong.
