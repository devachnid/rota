# Rota Fixes and Clinician Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six bugs and add seven improvements found in the first real use of the deployed rota app, consolidating availability (working pattern, clinician date window, approved leave) into one resolver that the grid and the fill engine share.

**Architecture:** `PatternResolver` stays as the pattern layer. A new `AvailabilityResolver` composes it with `active`, a new clinician start/end date window, and approved leave, and answers "can this clinician be given this session?" for both the grid and `FillContext`. Everything else in the plan is independent: range parsing, the pattern editor form, admin colour previews, a theme toggle, and two small template changes.

**Tech Stack:** Django 5.2, SQLite, htmx, hand-written CSS with custom properties, pytest. No new dependencies, no build step.

**Spec:** `docs/superpowers/specs/2026-08-30-rota-fixes-design.md`

## Global Constraints

- **No new dependencies and no build step.** Hand-written CSS with custom properties only.
- **Session colours come only from `rota/palette.py`.** No hex literals in `components.css` or `screens.css`; the sole sanctioned exception is the existing `rgba(255,255,255,.55)` draft hatch.
- **Three-state dark mode.** Colour tokens are defined in bare `:root`, in `@media (prefers-color-scheme: dark)` guarded as `:root:not([data-theme="light"])`, and in `:root[data-theme="dark"]`. No colour may have its only definition inside a media or `[data-theme]` block.
- **The existing test suite must pass**, except where this plan deliberately changes behaviour (grid cell classes in Task 5, the fill checkbox default in Task 12). Never edit a test to make it pass — if one fails, the code is wrong unless this plan says otherwise.
- **`DEBUG` defaults off.** Run management commands and `manage.py` with `DEBUG=1` locally, or set `SECRET_KEY`.
- **Test runner is `.venv/bin/pytest`.** Plain `pytest` and `python` are not on PATH; use `.venv/bin/python` for `manage.py`. The full suite takes about 2.5 minutes — allow a generous timeout.
- **Entries remain the accounting record for leave entitlement.** The resolver drives visibility and scheduling only. Never write rota entries for sessions a clinician does not work.

---

## File Structure

**Created:**
- `rota/services/ranges.py` — parsing and validating comma/range integer lists
- `rota/admin_widgets.py` — the tint swatch picker widget
- `rota/management/commands/pattern_report.py` — read-only damaged-pattern report
- `static/js/theme.js` — light/dark/system toggle
- `tests/test_ranges.py`, `tests/test_availability_resolver.py`, `tests/test_clinician_lifecycle.py`, `tests/test_pattern_editor.py`, `tests/test_grid_rendering.py`, `tests/test_theme_toggle.py`

**Modified:**
- `rota/models/catalog.py` — range parsing on `CoverageRule` and `PracticeSettings`
- `rota/models/people.py` — `Clinician.start_date` / `end_date`
- `rota/services/availability.py` — `AvailabilityResolver`, window-aware `works_on`
- `rota/services/fill/context.py` — build and expose the resolver
- `rota/services/fill/*.py` — call sites renamed to `ctx.available`
- `rota/views/grid.py`, `templates/rota/grid.html`, `static/css/components.css` — cell rendering
- `rota/views/requests.py`, `templates/rota/inbox.html` — zero-session leave warning
- `rota/admin.py`, `templates/admin/rota/patternslot/bulk_form.html` — editor and deletion guard
- `templates/base.html`, `templates/rota/fill.html`

---

## Task 1: Range parsing for months and weekdays

**Files:**
- Create: `rota/services/ranges.py`
- Create: `tests/test_ranges.py`
- Modify: `rota/models/catalog.py` (`CoverageRule.applies_on`, `CoverageRule.preferred_weekday_list`, `CoverageRule.clean`, `PracticeSettings.open_weekday_list`)

**Interfaces:**
- Produces: `parse_int_list(value: str) -> list[int]` and `validate_int_list(value: str, low: int, high: int, label: str) -> None` (raises `django.core.exceptions.ValidationError`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ranges.py`:

```python
"""Comma-and-range integer lists, as typed into coverage rules.

`1-6,9-12` raised `invalid literal for int() with base 10: '1-6'` from inside
a fill run, because the parse was `int(x) for x in value.split(",")` with no
validation anywhere. The failure landed on whoever ran the fill rather than on
whoever typed the value.
"""

import pytest
from django.core.exceptions import ValidationError

from rota.services.ranges import parse_int_list, validate_int_list


@pytest.mark.parametrize("value,expected", [
    ("", []),
    ("3", [3]),
    ("1,2,3", [1, 2, 3]),
    ("1-6", [1, 2, 3, 4, 5, 6]),
    ("1-6,9-12", [1, 2, 3, 4, 5, 6, 9, 10, 11, 12]),
    ("10,1-3", [10, 1, 2, 3]),          # order is preserved, not sorted
    (" 1 - 3 , 5 ", [1, 2, 3, 5]),      # whitespace tolerated
    ("4-4", [4]),                        # a range of one
    ("0,1,2,3,4", [0, 1, 2, 3, 4]),      # weekdays are zero-based
])
def test_parse_int_list(value, expected):
    assert parse_int_list(value) == expected


@pytest.mark.parametrize("bad", ["x", "1-", "-3", "1-2-3", "1,,2", "1..3", "1-x"])
def test_parse_rejects_malformed_input(bad):
    with pytest.raises(ValidationError):
        parse_int_list(bad)


def test_a_descending_range_is_rejected_rather_than_silently_empty():
    """range(6, 1) is empty, so `6-1` would quietly mean 'never applies' —
    a rule that silently does nothing is worse than one that refuses."""
    with pytest.raises(ValidationError):
        parse_int_list("6-1")


@pytest.mark.parametrize("value", ["1-12", "1,12", "6"])
def test_validate_accepts_in_range_months(value):
    validate_int_list(value, 1, 12, "months")


@pytest.mark.parametrize("value", ["0", "13", "1-13", "0-5"])
def test_validate_rejects_out_of_range_months(value):
    with pytest.raises(ValidationError):
        validate_int_list(value, 1, 12, "months")


def test_validation_message_names_the_field_and_the_bad_value():
    with pytest.raises(ValidationError) as exc:
        validate_int_list("13", 1, 12, "months")
    message = str(exc.value)
    assert "months" in message
    assert "13" in message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ranges.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rota.services.ranges'`

- [ ] **Step 3: Write the implementation**

Create `rota/services/ranges.py`:

```python
"""Comma-separated integer lists that also accept ranges.

Coverage rules take months and weekdays as free text. The original parse was
`int(x) for x in value.split(",")`, so `1-6,9-12` — the obvious way to write
"the winter half of the year" — raised ValueError from inside a fill run, in
front of whoever pressed the button rather than whoever typed the value.

Parsing and validation live together here so every field that takes this shape
behaves the same way: CoverageRule.months, .weekdays and .preferred_weekdays,
and PracticeSettings.open_weekdays.
"""

from django.core.exceptions import ValidationError

_ERROR = (
    "%(label)s: %(part)r is not a number or a range like 1-6. "
    "Use commas between values, for example 1,3,5 or 1-6,9-12."
)


def parse_int_list(value: str) -> list[int]:
    """"1-6,9-12" -> [1,2,3,4,5,6,9,10,11,12]. Blank -> []."""
    out: list[int] = []
    for raw in (value or "").split(","):
        part = raw.strip()
        if not part:
            if (value or "").strip():
                # "1,,2" is a typo, not an empty list
                raise ValidationError(_ERROR, params={"label": "value", "part": raw})
            continue
        if "-" in part:
            bits = part.split("-")
            if len(bits) != 2 or not all(b.strip().isdigit() for b in bits):
                raise ValidationError(_ERROR, params={"label": "value", "part": part})
            low, high = int(bits[0]), int(bits[1])
            if high < low:
                raise ValidationError(
                    "%(part)r counts downwards, so it would never match anything. "
                    "Write it as %(fixed)s.",
                    params={"part": part, "fixed": f"{high}-{low}"},
                )
            out.extend(range(low, high + 1))
        else:
            if not part.isdigit():
                raise ValidationError(_ERROR, params={"label": "value", "part": part})
            out.append(int(part))
    return out


def validate_int_list(value: str, low: int, high: int, label: str) -> None:
    """Raise if `value` does not parse, or holds anything outside [low, high]."""
    try:
        numbers = parse_int_list(value)
    except ValidationError as exc:
        raise ValidationError({label: exc.messages}) from exc
    bad = sorted({n for n in numbers if not low <= n <= high})
    if bad:
        raise ValidationError({label: [
            f"{label}: {', '.join(str(n) for n in bad)} "
            f"{'is' if len(bad) == 1 else 'are'} outside {low}-{high}."
        ]})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ranges.py -q`
Expected: PASS

- [ ] **Step 5: Use the parser everywhere those fields are read**

In `rota/models/catalog.py`, add the import at the top:

```python
from rota.services.ranges import parse_int_list, validate_int_list
```

Replace `CoverageRule.applies_on` and `CoverageRule.preferred_weekday_list`:

```python
    def applies_on(self, day):
        if self.months:
            if day.month not in parse_int_list(self.months):
                return False
        return day.weekday() in parse_int_list(self.weekdays)

    def preferred_weekday_list(self):
        return parse_int_list(self.preferred_weekdays)
```

Replace `PracticeSettings.open_weekday_list`:

```python
    def open_weekday_list(self):
        return parse_int_list(self.open_weekdays)
```

- [ ] **Step 6: Validate at save time, so the failure lands on whoever typed it**

Add to `CoverageRule.clean`, keeping the existing even-count check:

```python
        validate_int_list(self.months, 1, 12, "months")
        validate_int_list(self.weekdays, 0, 6, "weekdays")
        validate_int_list(self.preferred_weekdays, 0, 6, "preferred_weekdays")
```

Add a `clean` to `PracticeSettings`:

```python
    def clean(self):
        super().clean()
        validate_int_list(self.open_weekdays, 0, 6, "open_weekdays")
```

- [ ] **Step 7: Add the model-level tests**

Append to `tests/test_ranges.py`:

```python
@pytest.mark.django_db
def test_a_coverage_rule_with_a_month_range_applies_on_the_right_days():
    from datetime import date
    from rota.models import CoverageRule
    from tests.factories import make_session_type

    rule = CoverageRule(session_type=make_session_type("Winter", code="WIN"),
                        months="1-3,10-12", weekdays="0-4")
    assert rule.applies_on(date(2026, 1, 5)) is True     # Monday in January
    assert rule.applies_on(date(2026, 11, 4)) is True    # Wednesday in November
    assert rule.applies_on(date(2026, 6, 3)) is False    # Wednesday in June
    assert rule.applies_on(date(2026, 1, 4)) is False    # a Sunday


@pytest.mark.django_db
def test_a_bad_month_range_is_refused_at_save_not_at_fill_time():
    from rota.models import CoverageRule
    from tests.factories import make_session_type

    rule = CoverageRule(session_type=make_session_type("Bad", code="BAD"),
                        months="1-13")
    with pytest.raises(ValidationError):
        rule.full_clean()
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add rota/services/ranges.py rota/models/catalog.py tests/test_ranges.py
git commit -m "fix: coverage rules accept month and weekday ranges"
```

---

## Task 2: Clinician start and end dates

**Files:**
- Modify: `rota/models/people.py` (`Clinician`)
- Create: `rota/migrations/0020_clinician_date_window.py` (generated)
- Modify: `rota/admin.py` (`ClinicianAdmin`)
- Create: `tests/test_clinician_lifecycle.py`

**Interfaces:**
- Produces: `Clinician.start_date` and `Clinician.end_date`, both `DateField(null=True, blank=True)`; `Clinician.in_window(day) -> bool`.
- Consumed by Task 3's resolver and Task 9's admin.

- [ ] **Step 1: Write the failing test**

Create `tests/test_clinician_lifecycle.py`:

```python
"""Clinician start and end dates.

They sit alongside `active` rather than replacing it: `active` is the manual
"not schedulable right now" switch, the dates are the contractual window.
Both feed one composition in AvailabilityResolver so they cannot disagree.
"""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from tests.factories import make_clinician

TODAY = date(2026, 9, 15)
BEFORE = date(2026, 9, 1)
AFTER = date(2026, 9, 30)


@pytest.mark.django_db
def test_no_dates_means_always_in_window():
    c = make_clinician("Open Ended", initials="OE")
    assert c.start_date is None and c.end_date is None
    assert c.in_window(date(1999, 1, 1)) is True
    assert c.in_window(date(2099, 1, 1)) is True


@pytest.mark.django_db
def test_the_window_is_inclusive_at_both_ends():
    c = make_clinician("Bounded", initials="BD")
    c.start_date, c.end_date = BEFORE, AFTER
    assert c.in_window(BEFORE) is True
    assert c.in_window(AFTER) is True
    assert c.in_window(BEFORE - timedelta(days=1)) is False
    assert c.in_window(AFTER + timedelta(days=1)) is False


@pytest.mark.django_db
def test_a_start_date_alone_bounds_only_the_past():
    c = make_clinician("Starter", initials="ST")
    c.start_date = TODAY
    assert c.in_window(TODAY - timedelta(days=1)) is False
    assert c.in_window(date(2099, 1, 1)) is True


@pytest.mark.django_db
def test_an_end_date_alone_bounds_only_the_future():
    c = make_clinician("Leaver", initials="LR")
    c.end_date = TODAY
    assert c.in_window(date(1999, 1, 1)) is True
    assert c.in_window(TODAY + timedelta(days=1)) is False


@pytest.mark.django_db
def test_an_end_date_before_the_start_date_is_refused():
    c = make_clinician("Backwards", initials="BW")
    c.start_date, c.end_date = AFTER, BEFORE
    with pytest.raises(ValidationError):
        c.full_clean()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_clinician_lifecycle.py -q`
Expected: FAIL with `AttributeError: 'Clinician' object has no attribute 'in_window'`

- [ ] **Step 3: Add the fields and the predicate**

In `rota/models/people.py`, inside `Clinician`, after `leave_entitlement_sessions`:

```python
    start_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule before this date. Blank means no start bound.")
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule after this date. Blank means no end bound.")
```

Add the methods to `Clinician`:

```python
    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date is before the start date."})

    def in_window(self, day):
        """Whether `day` falls inside this clinician's contractual window.

        Separate from `active`, which is the manual override. Both are read
        together by AvailabilityResolver so they cannot drift apart.
        """
        if self.start_date and day < self.start_date:
            return False
        if self.end_date and day > self.end_date:
            return False
        return True
```

Add the import at the top of the file if it is not already present:

```python
from django.core.exceptions import ValidationError
```

- [ ] **Step 4: Generate and inspect the migration**

Run:
```bash
DEBUG=1 .venv/bin/python manage.py makemigrations rota --name clinician_date_window
```
Expected: one `AddField` for each of `start_date` and `end_date`. Open the file and confirm it contains no other operation.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_clinician_lifecycle.py -q`
Expected: PASS

- [ ] **Step 6: Surface the fields and warn about entries outside the window**

In `rota/admin.py`, extend `ClinicianAdmin`:

```python
    list_display = ("name", "initials", "group", "active", "is_trainer",
                    "start_date", "end_date",
                    "leave_entitlement_sessions", "pattern_link")
    list_filter = ("group", "active")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        outside = self._entries_outside_window(obj)
        if outside:
            messages.warning(
                request,
                f"{obj.name} has {outside} rota entr"
                f"{'y' if outside == 1 else 'ies'} outside "
                f"{obj.start_date or 'any start'} – {obj.end_date or 'any end'}. "
                f"Nothing has been deleted; review them on the grid."
            )

    @staticmethod
    def _entries_outside_window(clinician):
        from django.db.models import Q
        if not clinician.start_date and not clinician.end_date:
            return 0
        q = Q()
        if clinician.start_date:
            q |= Q(day__lt=clinician.start_date)
        if clinician.end_date:
            q |= Q(day__gt=clinician.end_date)
        return RotaEntry.objects.filter(q, clinician=clinician).count()
```

- [ ] **Step 7: Test the warning**

Append to `tests/test_clinician_lifecycle.py`:

```python
@pytest.mark.django_db
def test_saving_a_window_warns_about_entries_outside_it_but_deletes_nothing(
    staff_client
):
    """Silently destroying published rota because someone typed a date would
    be the wrong trade."""
    from rota.models import RotaEntry
    from tests.factories import make_entry, make_session_type, MON

    c = make_clinician("Windowed", initials="WD")
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="RT"))
    before = RotaEntry.objects.filter(clinician=c).count()
    assert before == 1

    r = staff_client.post(
        f"/admin/rota/clinician/{c.pk}/change/",
        {"name": c.name, "initials": c.initials, "group": c.group_id,
         "active": "on", "leave_entitlement_sessions": "0",
         "start_date": (MON + timedelta(days=365)).isoformat(),
         "end_date": "",
         "trainee_profile-TOTAL_FORMS": "0", "trainee_profile-INITIAL_FORMS": "0"},
        follow=True,
    )
    assert RotaEntry.objects.filter(clinician=c).count() == before, (
        "saving a date window deleted rota entries"
    )
    assert any("outside" in str(m) for m in r.context["messages"]), (
        "no warning was shown about the entries outside the new window"
    )
```

- [ ] **Step 8: Run the full suite and check migrations**

Run:
```bash
.venv/bin/pytest -q
DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run
```
Expected: tests PASS; `No changes detected`.

- [ ] **Step 9: Commit**

```bash
git add rota/models/people.py rota/migrations/ rota/admin.py tests/test_clinician_lifecycle.py
git commit -m "feat: clinician start and end dates"
```

---

## Task 3: AvailabilityResolver

**Files:**
- Modify: `rota/services/availability.py`
- Create: `tests/test_availability_resolver.py`

**Interfaces:**
- Consumes: `Clinician.in_window(day)` from Task 2.
- Produces:
  - `works_on(clinician, day, part) -> bool` (module level, single clinician, queries) — now also checks `active` and the date window.
  - `AvailabilityResolver(pattern_rows, clinicians, leave_requests)` with:
    - `works_on(clinician_id, day, part) -> bool`
    - `leave_type(clinician_id, day) -> SessionType | None`
    - `on_leave(clinician_id, day, part) -> bool`
    - `available(clinician_id, day, part) -> bool`
    - `has_pattern(clinician_id) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_availability_resolver.py`:

```python
"""One answer to "can this clinician be given this session?".

Before this, the question was answered in the grid and in the fill engine
separately, and knew only about the working pattern. Clinician date windows
and approved leave both belong in it. Composing them in one place is what
stops `active` and the dates disagreeing.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot
from rota.services.availability import AvailabilityResolver
from tests.factories import make_clinician, make_session_type

MON = date(2026, 9, 7)
LONG_AGO = date(2025, 1, 1)


def _pattern(clinician, weekday, part, works=True, effective_from=LONG_AGO):
    return PatternSlot.objects.create(
        clinician=clinician, weekday=weekday, part=part,
        works=works, effective_from=effective_from)


def _resolver(clinicians, rows=(), leave=()):
    return AvailabilityResolver(list(rows), list(clinicians), list(leave))


@pytest.mark.django_db
def test_works_on_follows_the_pattern():
    c = make_clinician("Pat", initials="PA")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    assert r.works_on(c.id, MON, "AM") is True
    assert r.works_on(c.id, MON, "PM") is False


@pytest.mark.django_db
def test_an_inactive_clinician_never_works():
    c = make_clinician("Gone", initials="GO")
    rows = [_pattern(c, 0, "AM")]
    c.active = False
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_a_session_before_the_start_date_is_not_worked():
    c = make_clinician("Starts", initials="SS")
    rows = [_pattern(c, 0, "AM")]
    c.start_date = MON + timedelta(days=7)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False
    assert _resolver([c], rows).works_on(c.id, MON + timedelta(days=7), "AM") is True


@pytest.mark.django_db
def test_a_session_after_the_end_date_is_not_worked():
    c = make_clinician("Ends", initials="EN")
    rows = [_pattern(c, 0, "AM")]
    c.end_date = MON - timedelta(days=1)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_approved_leave_makes_a_worked_session_unavailable():
    c = make_clinician("Away", initials="AW")
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rows = [_pattern(c, 0, "AM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], rows, leave)
    assert r.works_on(c.id, MON, "AM") is True, "leave must not change works_on"
    assert r.on_leave(c.id, MON, "AM") is True
    assert r.available(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_pending_leave_is_ignored():
    """Out of scope by decision: pending leave stays invisible to scheduling."""
    c = make_clinician("Maybe", initials="MB")
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    rows = [_pattern(c, 0, "AM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.PENDING)]
    assert _resolver([c], rows, leave).available(c.id, MON, "AM") is True


@pytest.mark.django_db
def test_leave_is_whole_day_because_requests_store_dates_not_parts():
    c = make_clinician("Allday", initials="AD")
    al = make_session_type("Annual Leave", code="AL3", category="ABSENCE")
    rows = [_pattern(c, 0, "AM"), _pattern(c, 0, "PM")]
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], rows, leave)
    assert r.on_leave(c.id, MON, "AM") is True
    assert r.on_leave(c.id, MON, "PM") is True


@pytest.mark.django_db
def test_leave_type_returns_the_session_type_for_rendering():
    c = make_clinician("Chip", initials="CH")
    al = make_session_type("Study Leave", code="SL", category="ABSENCE")
    leave = [LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=MON, end_date=MON,
        status=LeaveRequest.Status.APPROVED)]
    r = _resolver([c], (), leave)
    assert r.leave_type(c.id, MON) == al
    assert r.leave_type(c.id, MON + timedelta(days=1)) is None


@pytest.mark.django_db
def test_has_pattern_distinguishes_no_rows_from_not_working():
    with_rows = make_clinician("Has", initials="HS")
    without = make_clinician("Hasnt", initials="HN")
    rows = [_pattern(with_rows, 0, "AM")]
    r = _resolver([with_rows, without], rows)
    assert r.has_pattern(with_rows.id) is True
    assert r.has_pattern(without.id) is False


@pytest.mark.django_db
def test_the_resolver_issues_no_queries_once_built():
    """Both callers ask it once per cell. A query here is a query per cell."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    c = make_clinician("Quiet", initials="QT")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    with CaptureQueriesContext(connection) as ctx:
        for _ in range(20):
            r.available(c.id, MON, "AM")
    assert len(ctx) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_availability_resolver.py -q`
Expected: FAIL with `ImportError: cannot import name 'AvailabilityResolver'`

- [ ] **Step 3: Make the module-level `works_on` window-aware**

In `rota/services/availability.py`, replace `works_on`:

```python
def works_on(clinician, day, part):
    """Single-clinician availability. Issues queries; use AvailabilityResolver
    for anything that asks repeatedly.

    Checks the same three things the resolver does — active, the contractual
    window, then the pattern — so `leave.sessions_affected()` cannot write
    leave outside a clinician's window while the grid hides it.
    """
    if not clinician.active or not clinician.in_window(day):
        return False
    slot = _current_slot(clinician, day.weekday(), part, day)
    return bool(slot and slot.works)
```

- [ ] **Step 4: Add the resolver**

First extend the import at the top of `rota/services/availability.py`:

```python
from rota.models import LeaveRequest, Part, PatternSlot
```

Then append:

```python
class AvailabilityResolver:
    """The one answer to "can this clinician be given this session?".

    Composes, cheapest check first: `active`, the contractual date window, the
    working pattern, then approved leave. All four are read at one moment by
    one call, so they cannot disagree — which is the risk in `active` and the
    date window being separate concepts.

    Built once per request or per fill from prefetched rows; every lookup is
    in memory.
    """

    def __init__(self, pattern_rows, clinicians, leave_requests):
        self._patterns = PatternResolver(pattern_rows)
        self._clinicians = {c.id: c for c in clinicians}
        self._with_pattern = {row.clinician_id for row in pattern_rows}

        # {clinician_id: [(start, end, session_type), ...]} for approved leave
        self._leave = {}
        for req in leave_requests:
            if req.status != LeaveRequest.Status.APPROVED:
                continue
            self._leave.setdefault(req.clinician_id, []).append(
                (req.start_date, req.end_date, req.session_type))

    def has_pattern(self, clinician_id):
        """Whether any pattern row exists at all. Distinct from "does not work
        this session" — Task 5's ghosting rule needs to tell them apart."""
        return clinician_id in self._with_pattern

    def works_on(self, clinician_id, day, part):
        clinician = self._clinicians.get(clinician_id)
        if clinician is None or not clinician.active:
            return False
        if not clinician.in_window(day):
            return False
        return self._patterns.works_on(clinician_id, day, part)

    def leave_type(self, clinician_id, day):
        """The SessionType of approved leave covering `day`, or None.

        Requests store dates, not parts, so leave is whole-day across its
        range and `part` does not enter into it.
        """
        for start, end, session_type in self._leave.get(clinician_id, ()):
            if start <= day <= end:
                return session_type
        return None

    def on_leave(self, clinician_id, day, part):
        return self.leave_type(clinician_id, day) is not None

    def available(self, clinician_id, day, part):
        return (self.works_on(clinician_id, day, part)
                and not self.on_leave(clinician_id, day, part))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_availability_resolver.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS. `leave.sessions_affected` now also respects `active` and the window; no existing test should depend on it not doing so.

- [ ] **Step 7: Commit**

```bash
git add rota/services/availability.py tests/test_availability_resolver.py
git commit -m "feat: AvailabilityResolver composes pattern, date window and leave"
```

---

## Task 4: The fill engine uses the resolver

**Files:**
- Modify: `rota/services/fill/context.py`
- Modify: `rota/services/fill/coverage.py:14`, `commitments.py:17`, `mentoring.py:22,28`, `trainees.py:122,155`, `scoring.py:9`, `__init__.py:34`
- Create: `tests/test_fill_availability.py`

**Interfaces:**
- Consumes: `AvailabilityResolver` from Task 3.
- Produces: `ctx.available(cid, day, part) -> bool` replaces `ctx.works_on` at every scheduling call site. `ctx.works_on` is removed so no caller can keep the old meaning by accident.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fill_availability.py`:

```python
"""The fill engine must not schedule someone who is unavailable.

Two new reasons to be unavailable: outside the contractual date window, and
on approved leave. The leave check is deliberately independent of rota
entries — entries only exist where the pattern said the clinician works, so a
pattern widened after approval would otherwise expose the leave to a re-run.
"""

from datetime import date, timedelta

import pytest

from rota.models import (CoverageRule, LeaveRequest, PatternSlot,
                         PracticeSettings, RotaEntry)
from rota.services.fill import run_fill
from tests.factories import make_clinician, make_session_type

MON = date(2026, 9, 7)
FRI = MON + timedelta(days=4)


def _full_pattern(clinician):
    for weekday in range(5):
        for part in ("AM", "PM"):
            PatternSlot.objects.create(
                clinician=clinician, weekday=weekday, part=part,
                works=True, effective_from=date(2025, 1, 1))


@pytest.fixture
def duty(db):
    PracticeSettings.load()
    st = make_session_type("Duty", code="DUTY")
    CoverageRule.objects.create(session_type=st, unit="SESSION",
                                parts="BOTH", weekdays="0-4", count=1)
    return st


@pytest.mark.django_db
def test_a_clinician_outside_their_window_is_not_scheduled(duty, admin_user):
    c = make_clinician("Leaver", initials="LV")
    _full_pattern(c)
    c.end_date = MON - timedelta(days=1)
    c.save()
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c).count() == 0


@pytest.mark.django_db
def test_a_clinician_on_approved_leave_is_not_scheduled(duty, admin_user):
    c = make_clinician("Away", initials="AW")
    _full_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=FRI,
                                status=LeaveRequest.Status.APPROVED)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c, session_type=duty).count() == 0


@pytest.mark.django_db
def test_leave_is_respected_even_when_approval_wrote_no_entries(duty, admin_user):
    """The case that made this necessary: leave approved while the clinician
    had no pattern, the pattern entered afterwards. No entries exist, so
    `is_free` sees nothing — only reading the request catches it."""
    c = make_clinician("Late Pattern", initials="LP")
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=FRI,
                                status=LeaveRequest.Status.APPROVED)
    assert RotaEntry.objects.filter(clinician=c).count() == 0
    _full_pattern(c)   # pattern arrives after the approval

    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c).count() == 0, (
        "the fill scheduled over approved leave that had no entries"
    )


@pytest.mark.django_db
def test_an_available_clinician_is_still_scheduled(duty, admin_user):
    """The control: none of the above should stop ordinary scheduling."""
    c = make_clinician("Normal", initials="NM")
    _full_pattern(c)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c, session_type=duty).count() > 0


def test_no_scheduling_call_site_still_uses_the_old_name():
    """`ctx.works_on` no longer exists. If a call site is reintroduced meaning
    "pattern only", it silently ignores the date window and leave."""
    from pathlib import Path
    import rota.services.fill as fill_pkg

    offenders = []
    for path in Path(fill_pkg.__file__).parent.glob("*.py"):
        for lineno, line in enumerate(path.read_text().split("\n"), 1):
            if "ctx.works_on" in line:
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "these call sites use ctx.works_on, which no longer accounts for the "
        f"date window or leave: {', '.join(offenders)}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fill_availability.py -q`
Expected: FAIL — the window and leave tests schedule anyway, and the call-site test lists offenders.

- [ ] **Step 3: Build the resolver in FillContext**

In `rota/services/fill/context.py`, add `LeaveRequest` to the model imports, then replace the pattern-resolver construction:

```python
        pattern_rows = list(PatternSlot.objects.filter(
            clinician__in=self.clinicians
        ).order_by("effective_from"))
        approved_leave = LeaveRequest.objects.filter(
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=end, end_date__gte=start,
        ).select_related("session_type")
        self._availability = availability.AvailabilityResolver(
            pattern_rows, self.clinicians, approved_leave)
```

Replace the `works_on` method with:

```python
    def available(self, cid, day, part):
        """Active, inside the date window, works this session, and not on
        approved leave. Every scheduling decision asks this one question."""
        return self._availability.available(cid, day, part)
```

- [ ] **Step 4: Update every call site**

Change `ctx.works_on(` to `ctx.available(` in all of:

- `rota/services/fill/coverage.py:14`
- `rota/services/fill/commitments.py:17`
- `rota/services/fill/mentoring.py:22` and `:28`
- `rota/services/fill/trainees.py:122` and `:155`
- `rota/services/fill/scoring.py:9`
- `rota/services/fill/__init__.py:34`

Verify none remain:

```bash
grep -rn "ctx.works_on" rota/services/fill/
```
Expected: no output.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_fill_availability.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add rota/services/fill/ tests/test_fill_availability.py
git commit -m "feat: the fill engine asks one availability question"
```

---

## Task 5: Grid rendering — colour reversal, ghosted leave, admin-only warnings

**Files:**
- Modify: `rota/views/grid.py`
- Modify: `templates/rota/grid.html`
- Modify: `static/css/components.css`
- Create: `tests/test_grid_rendering.py`

**Interfaces:**
- Consumes: `AvailabilityResolver` from Task 3.
- Produces: each grid cell dict gains `off: bool` (replacing `unavail`) and `ghost_leave: SessionType | None`. Template classes: `.off` replaces `.unavail`; `.chip.is-ghost` is new.

- [ ] **Step 1: Write the failing test**

Create `tests/test_grid_rendering.py`:

```python
"""What a grid cell shows, and why.

Cell precedence:
    entry exists                -> the entry
    on_leave and ghostable      -> a ghosted leave chip
    works_on                    -> grey: working, nothing allocated
    otherwise                   -> blank: not working

The colours are the reverse of what shipped: blank now means "not here", grey
means "here and unallocated" — the state that needs attention.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings
from tests.factories import make_clinician, make_entry, make_session_type

MON = date(2026, 9, 7)


def _pattern(c, weekday, part, works=True):
    PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                               works=works, effective_from=date(2025, 1, 1))


def _cells(client, day=MON):
    PracticeSettings.load()
    return client.get(f"/rota/?week={day.isoformat()}").content.decode()


@pytest.mark.django_db
def test_a_worked_but_unallocated_session_is_grey(admin_client):
    c = make_clinician("Grey", initials="GY")
    _pattern(c, 0, "AM")
    html = _cells(admin_client)
    assert "empty-slot" in html, (
        "a worked, unallocated session should carry the grey class"
    )


@pytest.mark.django_db
def test_a_non_working_session_is_blank(admin_client):
    c = make_clinician("Blank", initials="BL")
    _pattern(c, 0, "AM", works=False)
    html = _cells(admin_client)
    assert "unavail" not in html, (
        "the old class is gone; a non-working session is now unstyled"
    )


@pytest.mark.django_db
def test_approved_leave_ghosts_on_a_session_the_clinician_works(admin_client):
    """Approval should have written an entry here and did not — the ghost is
    the signal that something went wrong."""
    c = make_clinician("Ghosted", initials="GH")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html
    assert "AL" in html


@pytest.mark.django_db
def test_a_part_timer_gets_no_ghost_on_their_non_working_days(admin_client):
    """The noise case. Ghosting every session a leave request spans would put
    chips on every part-timer's days off, every time they took leave."""
    c = make_clinician("Parttime", initials="PT")
    _pattern(c, 0, "AM")            # works Monday AM only
    _pattern(c, 0, "PM", works=False)
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON + timedelta(days=4),
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert html.count("is-ghost") == 1, (
        f"expected one ghost (Monday AM), got {html.count('is-ghost')}"
    )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_at_all_gets_ghosts(admin_client):
    """The original complaint: leave approved, nothing anywhere."""
    c = make_clinician("Nopattern", initials="NP")
    al = make_session_type("Annual Leave", code="AL3", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html


@pytest.mark.django_db
def test_a_real_entry_beats_a_ghost(admin_client):
    c = make_clinician("Real", initials="RL")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL4", category="ABSENCE")
    make_entry(c, day=MON, part="AM", session_type=al, is_published=True)
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" not in html


@pytest.mark.django_db
def test_warnings_are_admin_only_but_day_notes_are_for_everyone(
    admin_client, gp_client
):
    from rota.models import DayNote
    PracticeSettings.load()
    DayNote.objects.create(day=MON, text="CQC visit")
    make_clinician("Someone", initials="SO")

    admin_html = _cells(admin_client)
    gp_html = _cells(gp_client)

    assert "CQC visit" in admin_html
    assert "CQC visit" in gp_html, "day notes are practice information"
    assert 'class="warn"' in admin_html, "an understaffed day warns an admin"
    assert 'class="warn"' not in gp_html, "warnings are staffing alerts, admin only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_grid_rendering.py -q`
Expected: FAIL — `empty-slot`, `is-ghost` and the warning gating do not exist yet.

- [ ] **Step 3: Build the resolver in the view and compute the new cell fields**

In `rota/views/grid.py`, add `LeaveRequest` to the model imports. Replace the `pattern_resolver` construction:

```python
    active = list(Clinician.objects.filter(active=True))
    pattern_rows = list(PatternSlot.objects.filter(
        clinician__in=active
    ).order_by("effective_from"))
    approved_leave = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=days[-1], end_date__gte=days[0],
    ).select_related("session_type")
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, approved_leave)
```

Replace the `day_headers` construction so warnings are not computed for non-admins:

```python
    day_headers = [
        {"day": d, "closed": d in closed, "note": notes.get(d),
         "warnings": day_warnings(d, include_drafts=is_admin) if is_admin else []}
        for d in days
    ]
```

Replace the cell dict inside the `for part, entry in ...` loop:

```python
                    works = resolver.works_on(clinician.id, d, part)
                    leave_type = (resolver.leave_type(clinician.id, d)
                                  if entry is None else None)
                    # Ghost only where it means something: on a session the
                    # clinician works (approval should have written an entry
                    # and did not), or for a clinician with no pattern at all
                    # (nothing would ever show for them otherwise). Ghosting
                    # every session leave spans would put chips on every
                    # part-timer's days off.
                    ghostable = works or not resolver.has_pattern(clinician.id)
                    cells.append({
                        "day": d, "day_str": d.isoformat(), "part": part,
                        "entry": entry, "merged": merged and part == "AM",
                        "off": entry is None and not works,
                        "ghost_leave": leave_type if ghostable else None,
                        "closed": d in closed,
                        "partner": companion_partner.get((clinician.id, d, part)),
                    })
```

- [ ] **Step 4: Render the new states**

In `templates/rota/grid.html`, replace the cell `<td>` class attribute and body:

```html
  <td {% if cell.merged %}colspan="2"{% endif %}
      class="{% if cell.entry and not cell.entry.is_published %}draft{% endif %}{% if cell.closed %} closed{% endif %}"
      {% if is_admin %}hx-get="/rota/cell/{{ row.clinician.id }}/{{ cell.day_str }}/{{ cell.part }}/"
      hx-target="#modal"{% endif %}
      title="{{ cell.entry.fill_reason|default:'' }} {{ cell.entry.note|default:'' }}{% if cell.partner %} with {{ cell.partner }}{% endif %}">
    {% if cell.entry %}
      <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}"
            style="--chip-bg: var(--tint-{{ cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.entry.session_type.tint.key }}-fg);">
        {{ cell.entry.session_type.code }}{% if cell.entry.site %}<span class="site-marker">{{ cell.entry.site.name|slice:":1" }}</span>{% endif %}
      </span>
    {% elif cell.ghost_leave %}
      <span class="chip is-ghost"
            title="Approved leave with no rota entry — check the clinician's pattern"
            style="--chip-bg: transparent; --chip-fg: var(--tint-{{ cell.ghost_leave.tint.key }}-fg); --chip-edge: var(--tint-{{ cell.ghost_leave.tint.key }}-fg);">
        {{ cell.ghost_leave.code }}
      </span>
    {% elif cell.off %}
      <span class="chip is-off">&nbsp;</span>
    {% else %}
      <span class="chip empty-slot">&nbsp;</span>
    {% endif %}
  </td>
```

- [ ] **Step 5: Reverse the two treatments in CSS**

In `static/css/components.css`, replace the `.chip.is-empty` rule (if present) and add, in the chips section:

```css
/* The two empty states, reversed from what shipped. Blank now means "not
   working"; grey means "working, nothing allocated" — the state that wants
   attention, so it is the one that carries weight. */
.chip.is-off {
  background: transparent;
}
.chip.empty-slot {
  background: var(--sunken);
}

/* Approved leave with no rota entry behind it: outlined rather than filled,
   so it cannot be mistaken for a real allocation. */
.chip.is-ghost {
  background: transparent;
  border: 1px dashed var(--chip-edge, var(--muted));
  color: var(--chip-fg, var(--muted));
}
```

Remove the now-unused `.unavail` rule from the legacy-compatibility block near the bottom of the file, and its mention in that block's comment.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_grid_rendering.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite and check for colour literals**

Run:
```bash
.venv/bin/pytest -q
grep -nE "#[0-9a-fA-F]{3,6}" static/css/components.css static/css/screens.css
```
Expected: tests PASS; grep returns nothing.

`tests/test_grid_view.py` asserts on grid markup. If a test there asserts the string `unavail`, that is a deliberate behaviour change — update that one assertion to `empty-slot` and note it in the commit message. Change nothing else in that file.

- [ ] **Step 8: Commit**

```bash
git add rota/views/grid.py templates/rota/grid.html static/css/components.css tests/
git commit -m "feat: reverse the grid empty states, ghost unmaterialised leave, gate warnings to admins"
```

---

## Task 6: Warn when approving leave would write nothing

**Files:**
- Modify: `templates/rota/inbox.html`
- Modify: `rota/views/requests.py` (`leave_approve`)
- Create: `tests/test_leave_preview.py`

**Interfaces:**
- Consumes: `item.n_sessions`, which `inbox` already computes via `leave_svc.sessions_affected`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_leave_preview.py`:

```python
"""Approving leave must not be able to do nothing silently.

`sessions_affected()` intersects the requested range with the clinician's
working pattern. No overlap means zero entries — but the request still flipped
to APPROVED with a success message, so leave "did not work" with no clue why.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings, RotaEntry
from tests.factories import make_clinician, make_session_type

MON = date(2026, 9, 7)


def _leave_request(clinician, session_type, days=4):
    return LeaveRequest.objects.create(
        clinician=clinician, session_type=session_type,
        start_date=MON, end_date=MON + timedelta(days=days))


@pytest.fixture
def absence(db):
    PracticeSettings.load()
    return make_session_type("Annual Leave", code="AL", category="ABSENCE")


@pytest.mark.django_db
def test_the_inbox_warns_when_approval_would_write_nothing(admin_client, absence):
    c = make_clinician("Nopattern", initials="NP")
    _leave_request(c, absence)
    html = admin_client.get("/requests/").content.decode()
    assert "no sessions" in html.lower()
    assert "no working pattern" in html.lower(), (
        "the warning must say why, not just that the count is zero"
    )


@pytest.mark.django_db
def test_a_normal_request_shows_a_count_without_alarm(admin_client, absence):
    c = make_clinician("Fulltime", initials="FT")
    for weekday in range(5):
        for part in ("AM", "PM"):
            PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                                       works=True, effective_from=date(2025, 1, 1))
    _leave_request(c, absence)
    html = admin_client.get("/requests/").content.decode()
    assert "10 session" in html
    assert "no working pattern" not in html.lower()


@pytest.mark.django_db
def test_approval_still_records_the_decision_when_it_writes_nothing(
    admin_client, absence
):
    """The admin has decided. Blocking them would be wrong; misleading them
    was the bug."""
    c = make_clinician("Nopattern2", initials="N2")
    req = _leave_request(c, absence)
    r = admin_client.post(f"/requests/leave/{req.pk}/approve/", follow=True)
    req.refresh_from_db()
    assert req.status == LeaveRequest.Status.APPROVED
    assert RotaEntry.objects.filter(clinician=c).count() == 0
    assert any("no rota sessions" in str(m).lower() for m in r.context["messages"]), (
        "approving with nothing to write reported plain success"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_leave_preview.py -q`
Expected: FAIL — no warning text exists.

- [ ] **Step 3: Make the zero case prominent in the inbox**

In `templates/rota/inbox.html`, immediately after the paragraph that renders `{{ item.n_sessions }} session(s)`, add:

```html
    {% if item.n_sessions == 0 %}
    <p class="warn">Writes <strong>no sessions</strong> —
      {{ item.req.clinician.name }} has no working pattern covering
      {{ item.req.start_date|date:"j M" }} – {{ item.req.end_date|date:"j M Y" }}.
      Approving records the decision, but the leave will not appear on the grid
      as an entry and will not count towards their entitlement.</p>
    {% endif %}
```

- [ ] **Step 4: Say the same thing after the fact**

In `rota/views/requests.py`, replace the body of `leave_approve`:

```python
def leave_approve(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk,
                            status=LeaveRequest.Status.PENDING)
    written = len(leave_svc.sessions_affected(req))
    leave_svc.approve(request.user, req, request.POST.get("comment", ""))
    if written:
        messages.success(request, f"Leave approved ({written} session(s)).")
    else:
        messages.warning(
            request,
            f"Leave approved, but no rota sessions were written — "
            f"{req.clinician.name} has no working pattern covering those dates. "
            f"It will not count towards their entitlement.")
    return redirect("/requests/")
```

Keep the existing decorators and any existing signature details; only the body changes.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_leave_preview.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add templates/rota/inbox.html rota/views/requests.py tests/test_leave_preview.py
git commit -m "fix: approving leave that writes nothing now says so"
```

---

## Task 7: The pattern editor becomes one form

**Files:**
- Modify: `templates/admin/rota/patternslot/bulk_form.html`
- Modify: `rota/admin.py` (`PatternSlotAdmin.bulk_view`)
- Create: `tests/test_pattern_editor.py`

**Interfaces:**
- Produces: the bulk view accepts `action=load` and `action=save` on POST; the context gains `history: list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pattern_editor.py`:

```python
"""The bulk pattern editor.

The service and the view were correct all along: posting a future
`effective_from` creates only the changed rows at that date. The bug was the
template — the date input lived in a `method="get"` form while the checkboxes
and a *hidden copy* of `effective_from` lived in a separate `method="post"`
form, with nothing keeping them in step. Changing the date and pressing Save
posted the stale value, normally today: the one value that overwrites the
live pattern.

These test at the form level, which is where the gap was.
"""

from datetime import date, timedelta

import pytest

from rota.models import PatternSlot
from tests.factories import make_clinician

URL = "/admin/rota/patternslot/bulk/"
LONG_AGO = date(2025, 1, 1)


@pytest.fixture
def clinician(db):
    c = make_clinician("Pat Tern", initials="PT")
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=0, part=part,
                                   works=True, effective_from=LONG_AGO)
    return c


@pytest.mark.django_db
def test_the_page_has_one_form_so_the_date_cannot_go_stale(staff_client, clinician):
    html = staff_client.get(URL, {"clinician_id": clinician.pk}).content.decode()
    assert html.count("<form") == 1, (
        "two forms means the date input and the checkboxes can disagree — "
        "which is the bug this replaced"
    )
    assert 'name="action" value="load"' in html
    assert 'name="action" value="save"' in html


@pytest.mark.django_db
def test_saving_with_a_future_date_does_not_touch_the_current_pattern(
    staff_client, clinician
):
    future = date.today() + timedelta(days=30)
    staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(),
        "d0_AM": "on", "d0_PM": "on", "d2_AM": "on",
    })
    old = PatternSlot.objects.filter(clinician=clinician, effective_from=LONG_AGO)
    assert old.count() == 2, "the existing pattern was modified"
    new = PatternSlot.objects.filter(clinician=clinician, effective_from=future)
    assert [(r.weekday, r.part, r.works) for r in new] == [(2, "AM", True)]


@pytest.mark.django_db
def test_load_does_not_write_anything(staff_client, clinician):
    before = set(PatternSlot.objects.values_list("pk", flat=True))
    staff_client.post(URL, {
        "action": "load", "clinician_id": clinician.pk,
        "effective_from": (date.today() + timedelta(days=30)).isoformat(),
        "d3_PM": "on",
    })
    assert set(PatternSlot.objects.values_list("pk", flat=True)) == before


@pytest.mark.django_db
def test_an_unparseable_date_is_refused_not_silently_treated_as_today(
    staff_client, clinician
):
    """Substituting today turned bad input into the most destructive valid
    value there is."""
    r = staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": "not-a-date", "d2_AM": "on",
    })
    assert PatternSlot.objects.filter(clinician=clinician).count() == 2, (
        "a malformed date still wrote rows"
    )
    assert b"date" in r.content.lower()


@pytest.mark.django_db
def test_the_page_shows_the_pattern_history(staff_client, clinician):
    """The editor showed one date's worth with no hint anything else existed,
    which is what made the damage invisible."""
    future = date.today() + timedelta(days=30)
    PatternSlot.objects.create(clinician=clinician, weekday=2, part="AM",
                               works=True, effective_from=future)
    html = staff_client.get(
        URL, {"clinician_id": clinician.pk}).content.decode()
    assert LONG_AGO.strftime("%Y") in html or LONG_AGO.strftime("%b") in html
    assert future.strftime("%Y") in html or future.strftime("%b") in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pattern_editor.py -q`
Expected: FAIL — two forms, no `action`, no history.

- [ ] **Step 3: Rewrite the view**

In `rota/admin.py`, replace `PatternSlotAdmin.bulk_view`:

```python
    def bulk_view(self, request):
        clinicians = Clinician.objects.filter(active=True).order_by("name")
        clinician = None
        clinician_id = (request.POST.get("clinician_id")
                        or request.GET.get("clinician_id"))
        if clinician_id:
            clinician = get_object_or_404(Clinician, pk=clinician_id)

        raw_date = (request.POST.get("effective_from")
                    or request.GET.get("effective_from") or "")
        date_error = ""
        if raw_date:
            try:
                effective_from = date.fromisoformat(raw_date)
            except ValueError:
                # Never fall back to today: today is the value that overwrites
                # the live pattern, so a typo would be destructive.
                effective_from = date.today()
                date_error = (f"{raw_date!r} is not a date (use YYYY-MM-DD). "
                              f"Nothing was saved.")
        else:
            effective_from = date.today()

        action = request.POST.get("action")
        if request.method == "POST" and action == "save" and clinician \
                and not date_error:
            desired = {
                (weekday, part): f"d{weekday}_{part}" in request.POST
                for weekday in range(7)
                for part in Part.values
            }
            changed = bulk_set_pattern(clinician, effective_from, desired)
            messages.success(
                request,
                f"Saved pattern for {clinician.name} effective "
                f"{effective_from} ({changed} slot(s) changed).",
            )
            return redirect(
                f"{request.path}?clinician_id={clinician.pk}"
                f"&effective_from={effective_from.isoformat()}"
            )

        grid = None
        history = []
        if clinician:
            prior = current_pattern(clinician, effective_from - timedelta(days=1))
            grid = [
                {
                    "weekday": weekday,
                    "label": WEEKDAY_LABELS[weekday],
                    "am_checked": prior.get((weekday, "AM"), False),
                    "pm_checked": prior.get((weekday, "PM"), False),
                }
                for weekday in range(7)
            ]
            history = self._pattern_history(clinician)

        context = {
            **self.admin_site.each_context(request),
            "title": "Bulk edit clinician pattern",
            "opts": self.model._meta,
            "clinicians": clinicians,
            "clinician": clinician,
            "effective_from": effective_from,
            "date_error": date_error,
            "grid": grid,
            "history": history,
        }
        return render(request, "admin/rota/patternslot/bulk_form.html", context)

    @staticmethod
    def _pattern_history(clinician):
        """Every effective_from and what it sets, so the editor stops hiding
        the fact that other dates exist."""
        by_date = {}
        for row in PatternSlot.objects.filter(clinician=clinician).order_by(
            "effective_from", "weekday", "part"
        ):
            by_date.setdefault(row.effective_from, []).append(
                f"{WEEKDAY_LABELS[row.weekday][:3]} {row.part}"
                f"{'' if row.works else ' off'}")
        return [{"effective_from": d, "sessions": ", ".join(v)}
                for d, v in sorted(by_date.items())]
```

- [ ] **Step 4: Rewrite the template as one form**

Replace the whole of `templates/admin/rota/patternslot/bulk_form.html`:

```html
{% extends "admin/base_site.html" %}

{% block content %}
<h1>Bulk edit clinician pattern</h1>

{% comment %}
  One form, deliberately. The date input used to live in a separate GET form
  while the checkboxes and a hidden copy of effective_from lived here, so
  changing the date and pressing Save posted the stale value — normally today,
  which overwrites the live pattern. The date you can see is now the date that
  posts.
{% endcomment %}
<form method="post">
  {% csrf_token %}
  <p>
    <label>Clinician
      <select name="clinician_id" onchange="this.form.action.value='load'; this.form.submit();">
        <option value="">— choose —</option>
        {% for c in clinicians %}
        <option value="{{ c.id }}" {% if clinician.id == c.id %}selected{% endif %}>
          {{ c.name }}
        </option>
        {% endfor %}
      </select>
    </label>
    <label>Effective from
      <input type="date" name="effective_from" value="{{ effective_from|date:'Y-m-d' }}">
    </label>
    <button type="submit" name="action" value="load">Load</button>
  </p>

  {% if date_error %}<p class="errornote">{{ date_error }}</p>{% endif %}

  {% if clinician %}
  <p>Ticked boxes are the sessions {{ clinician.name }} works, as of the day
     before {{ effective_from }}. Save writes only the cells you change,
     dated {{ effective_from }}.</p>
  <table>
    <thead>
      <tr><th>Day</th><th>AM</th><th>PM</th></tr>
    </thead>
    <tbody>
      {% for row in grid %}
      <tr>
        <th>{{ row.label }}</th>
        <td><input type="checkbox" name="d{{ row.weekday }}_AM"{% if row.am_checked %} checked{% endif %}></td>
        <td><input type="checkbox" name="d{{ row.weekday }}_PM"{% if row.pm_checked %} checked{% endif %}></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <p><button type="submit" name="action" value="save" class="default">Save pattern</button></p>
  {% endif %}
</form>

{% if history %}
<h2>Pattern history</h2>
<p>Every date this clinician's pattern changes on. Rows all sharing one date —
   especially today's — are the fingerprint of the overwrite bug.</p>
<table>
  <thead><tr><th>Effective from</th><th>Sets</th></tr></thead>
  <tbody>
    {% for h in history %}
    <tr><th>{{ h.effective_from }}</th><td>{{ h.sessions }}</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_pattern_editor.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add rota/admin.py templates/admin/rota/patternslot/bulk_form.html tests/test_pattern_editor.py
git commit -m "fix: the pattern editor posts the date you can see"
```

---

## Task 8: `pattern_report` management command

**Files:**
- Create: `rota/management/commands/pattern_report.py`
- Create: `rota/management/__init__.py` and `rota/management/commands/__init__.py` if they do not exist
- Create: `tests/test_pattern_report.py`

**Interfaces:**
- Produces: `manage.py pattern_report`, read-only.

- [ ] **Step 1: Check whether the management package exists**

Run: `ls rota/management/commands/ 2>/dev/null || echo "needs creating"`

If it needs creating:
```bash
mkdir -p rota/management/commands
touch rota/management/__init__.py rota/management/commands/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_pattern_report.py`:

```python
"""Read-only report on pattern damage.

The editor bug overwrote rows in place, so the original values are gone — there
is nothing to recover and any "repair" would be inventing data. This shows the
damage so it can be re-entered by hand through the fixed editor.
"""

from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command

from rota.models import PatternSlot
from tests.factories import make_clinician


def _run():
    out = StringIO()
    call_command("pattern_report", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_it_lists_each_clinician_and_their_effective_dates():
    c = make_clinician("Historied", initials="HI")
    for eff in (date(2025, 1, 1), date(2025, 6, 1)):
        PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                                   works=True, effective_from=eff)
    output = _run()
    assert "Historied" in output
    assert "2025-01-01" in output
    assert "2025-06-01" in output


@pytest.mark.django_db
def test_a_single_date_history_is_flagged():
    """Every row at one date is what the overwrite bug leaves behind."""
    c = make_clinician("Flat", initials="FL")
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=0, part=part,
                                   works=True, effective_from=date(2025, 1, 1))
    assert "single date" in _run().lower()


@pytest.mark.django_db
def test_rows_dated_today_are_flagged():
    c = make_clinician("Todayed", initials="TD")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date.today())
    assert "today" in _run().lower()


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_is_reported_not_skipped():
    """They cannot be scheduled and leave will not materialise for them —
    that is worth seeing."""
    make_clinician("Empty", initials="EM")
    assert "Empty" in _run()
    assert "no pattern" in _run().lower()


@pytest.mark.django_db
def test_it_changes_nothing():
    c = make_clinician("Untouched", initials="UT")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date(2025, 1, 1))
    before = list(PatternSlot.objects.values_list("pk", "works", "effective_from"))
    _run()
    assert list(
        PatternSlot.objects.values_list("pk", "works", "effective_from")) == before
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pattern_report.py -q`
Expected: FAIL with `CommandError: Unknown command: 'pattern_report'`

- [ ] **Step 4: Write the command**

Create `rota/management/commands/pattern_report.py`:

```python
"""Show each clinician's pattern history, and flag what looks like damage.

The bulk editor used to post a stale `effective_from` — normally today — so a
pattern meant for a future date overwrote the live one, and a second save at
the same date updated the first in place. The original values are gone; this
reports what is there so it can be re-entered through the fixed editor.

Read-only by design. A repair would be inventing data.
"""

from datetime import date

from django.core.management.base import BaseCommand

from rota.models import Clinician, PatternSlot

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Command(BaseCommand):
    help = "Report each clinician's pattern history and flag likely damage."

    def handle(self, *args, **options):
        today = date.today()
        flagged = 0

        for clinician in Clinician.objects.order_by("name"):
            rows = list(PatternSlot.objects.filter(
                clinician=clinician).order_by("effective_from", "weekday", "part"))

            self.stdout.write(f"\n{clinician.name} ({clinician.initials})")

            if not rows:
                flagged += 1
                self.stdout.write(self.style.WARNING(
                    "  no pattern rows — cannot be scheduled, and approving "
                    "leave will write nothing"))
                continue

            by_date = {}
            for row in rows:
                by_date.setdefault(row.effective_from, []).append(row)

            for eff, day_rows in sorted(by_date.items()):
                sessions = ", ".join(
                    f"{WEEKDAYS[r.weekday]} {r.part}{'' if r.works else ' off'}"
                    for r in day_rows)
                marker = "  <- today" if eff == today else ""
                self.stdout.write(f"  {eff}  {sessions}{marker}")

            notes = []
            if len(by_date) == 1:
                notes.append("entire history sits at a single date")
            if today in by_date:
                notes.append("has rows dated today")
            if notes:
                flagged += 1
                self.stdout.write(self.style.WARNING(
                    "  suspect: " + "; ".join(notes)))

        self.stdout.write(
            f"\n{flagged} clinician(s) flagged. Nothing has been changed."
        )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_pattern_report.py -q`
Expected: PASS

- [ ] **Step 6: Run it against the development database**

Run: `DEBUG=1 .venv/bin/python manage.py pattern_report`
Expected: a per-clinician listing, ending with a flagged count. Confirm nothing errors.

- [ ] **Step 7: Commit**

```bash
git add rota/management tests/test_pattern_report.py
git commit -m "feat: pattern_report shows pattern history and likely damage"
```

---

## Task 9: Clinician deletion guard and deactivate action

**Files:**
- Modify: `rota/admin.py` (`ClinicianAdmin`)
- Modify: `tests/test_clinician_lifecycle.py`

**Interfaces:**
- Consumes: `Clinician` from Task 2.
- Produces: `ClinicianAdmin.get_deleted_objects` and `delete_model` overrides; a `deactivate_clinicians` admin action.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_clinician_lifecycle.py`:

```python
@pytest.mark.django_db
def test_deleting_a_clinician_with_only_drafts_takes_the_drafts_with_them(
    staff_client
):
    from rota.models import Clinician, RotaEntry
    from tests.factories import make_entry, make_session_type

    c = make_clinician("Draftsonly", initials="DO")
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="R1"),
               is_published=False)
    assert RotaEntry.objects.filter(clinician=c).count() == 1

    staff_client.post(f"/admin/rota/clinician/{c.pk}/delete/", {"post": "yes"})

    assert not Clinician.objects.filter(pk=c.pk).exists()
    assert RotaEntry.objects.filter(clinician_id=c.pk).count() == 0


@pytest.mark.django_db
def test_a_published_entry_blocks_deletion_and_says_how_many(staff_client):
    from rota.models import Clinician
    from tests.factories import make_entry, make_session_type

    c = make_clinician("Published", initials="PB")
    st = make_session_type("Routine", code="R2")
    make_entry(c, part="AM", session_type=st, is_published=True)

    r = staff_client.get(f"/admin/rota/clinician/{c.pk}/delete/")
    body = r.content.decode()

    assert Clinician.objects.filter(pk=c.pk).exists()
    assert "1" in body and "published" in body.lower()
    assert "deactivat" in body.lower(), (
        "the refusal should point at the alternative, not just say no"
    )


@pytest.mark.django_db
def test_the_deactivate_action_exists_and_works(staff_client):
    from rota.models import Clinician

    c = make_clinician("Deactivateme", initials="DM")
    staff_client.post("/admin/rota/clinician/", {
        "action": "deactivate_clinicians",
        "_selected_action": [str(c.pk)],
    })
    c.refresh_from_db()
    assert c.active is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_clinician_lifecycle.py -q`
Expected: FAIL — `PROTECT` blocks even the drafts-only delete, and there is no action.

- [ ] **Step 3: Add the guard and the action**

In `rota/admin.py`, extend `ClinicianAdmin`:

```python
    actions = ["deactivate_clinicians"]

    @admin.action(description="Deactivate selected clinicians")
    def deactivate_clinicians(self, request, queryset):
        n = queryset.update(active=False)
        self.message_user(
            request,
            f"Deactivated {n} clinician(s). Their history is intact and they "
            f"no longer appear in any eligibility pool.")

    def get_deleted_objects(self, objs, request):
        """RotaEntry.clinician is PROTECT, and that fires while rendering the
        confirmation page — before any delete code runs. So the split between
        "deletable drafts" and "protected published entries" has to happen
        here, not in delete_model.
        """
        deletable, model_count, perms_needed, protected = \
            super().get_deleted_objects(objs, request)

        published = RotaEntry.objects.filter(
            clinician__in=objs, is_published=True)
        n_published = published.count()

        if n_published:
            protected = list(protected) + [
                f"{n_published} published rota entr"
                f"{'y' if n_published == 1 else 'ies'} — deletion would destroy "
                f"rota history. Deactivate this clinician instead: it keeps "
                f"their record and history, and removes them from every "
                f"eligibility pool."
            ]
            return deletable, model_count, perms_needed, protected

        n_drafts = RotaEntry.objects.filter(
            clinician__in=objs, is_published=False).count()
        if n_drafts:
            deletable = list(deletable) + [
                f"{n_drafts} unpublished rota entr"
                f"{'y' if n_drafts == 1 else 'ies'} (will be deleted)"
            ]
        # Everything else cascades: pattern slots, leave requests, recurring
        # commitments, the trainee profile, and swap requests — including ones
        # where this clinician was the *colleague*, which touches someone
        # else's history. Locum bookings survive with the name set to null.
        # The audit log is unaffected: it stores names as text, not a key.
        return deletable, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        RotaEntry.objects.filter(clinician=obj, is_published=False).delete()
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        RotaEntry.objects.filter(
            clinician__in=queryset, is_published=False).delete()
        super().delete_queryset(request, queryset)
```

Add `from django.contrib import admin` usage for `@admin.action` if not already imported (the file already imports `admin`).

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/pytest tests/test_clinician_lifecycle.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add rota/admin.py tests/test_clinician_lifecycle.py
git commit -m "feat: delete a clinician with only drafts, refuse when published"
```

---

## Task 10: Colour previews in the admin

**Files:**
- Create: `rota/admin_widgets.py`
- Modify: `rota/admin.py` (`SessionTypeAdmin`)
- Create: `tests/test_admin_colour.py`

**Interfaces:**
- Consumes: `rota.palette.TINTS` (each `Tint` has `.key`, `.label`, `.bg`, `.fg`).
- Produces: `TintSwatchSelect` widget; `SessionTypeAdmin.colour_swatch` list column.

- [ ] **Step 1: Write the failing test**

Create `tests/test_admin_colour.py`:

```python
"""Colour is the point of the field, so the admin should show it.

The dropdown listed 42 names with no colour, and the list view showed a key
like `teal-strong` — you had to know the palette by heart to use either.
"""

import pytest

from rota import palette
from tests.factories import make_session_type


@pytest.mark.django_db
def test_the_list_view_shows_a_swatch_in_the_tint_s_own_colours(staff_client):
    st = make_session_type("Duty", code="DUTY")
    st.colour = "teal-strong"
    st.save()
    html = staff_client.get("/admin/rota/sessiontype/").content.decode()
    tint = palette.TINTS["teal-strong"]
    assert tint.bg in html, "the swatch is not painted in the tint's background"
    assert tint.fg in html


@pytest.mark.django_db
def test_the_picker_renders_every_tint_as_a_choosable_swatch(staff_client):
    st = make_session_type("Duty2", code="DT2")
    html = staff_client.get(
        f"/admin/rota/sessiontype/{st.pk}/change/").content.decode()
    assert html.count('name="colour"') == len(palette.TINTS), (
        "expected one radio input per tint"
    )
    for key in ("neutral-soft", "red-strong", "azure-soft"):
        assert palette.TINTS[key].bg in html


@pytest.mark.django_db
def test_the_currently_chosen_tint_is_selected(staff_client):
    st = make_session_type("Duty3", code="DT3")
    st.colour = "amber-soft"
    st.save()
    html = staff_client.get(
        f"/admin/rota/sessiontype/{st.pk}/change/").content.decode()
    assert 'value="amber-soft" checked' in html.replace('checked=""', "checked")


def test_no_colour_is_hardcoded_in_the_widget():
    """Every colour must come from the palette, or the two drift apart."""
    import re
    from pathlib import Path
    import rota.admin_widgets as widgets

    source = Path(widgets.__file__).read_text()
    literals = re.findall(r"#[0-9a-fA-F]{3,6}\b", source)
    assert not literals, f"hardcoded colours in the widget: {literals}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_admin_colour.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rota.admin_widgets'`

- [ ] **Step 3: Write the widget**

Create `rota/admin_widgets.py`:

```python
"""A swatch picker for the 42 session tints.

A `<select>` of 42 names tells you nothing about the colours, and styling
`<option>` backgrounds is not reliable across browsers — so this renders the
palette as labelled radio swatches instead, which is also a better way to pick
from 42 than a long dropdown.

Every colour comes from `rota.palette`; nothing here hardcodes one.
"""

from django.forms.widgets import RadioSelect
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from rota import palette


class TintSwatchSelect(RadioSelect):
    """Radio inputs painted in the tint each one selects."""

    def render(self, name, value, attrs=None, renderer=None):
        rows = format_html_join(
            "\n",
            '<label style="display:inline-block; margin:2px; padding:4px 8px; '
            'border-radius:6px; cursor:pointer; font-size:12px; '
            'background:{}; color:{}; outline:{}">'
            '<input type="radio" name="{}" value="{}"{}> {}</label>',
            (
                (
                    tint.bg,
                    tint.fg,
                    "2px solid #000" if key == value else "none",
                    name,
                    key,
                    mark_safe(" checked") if key == value else "",
                    tint.label,
                )
                for key, tint in palette.TINTS.items()
            ),
        )
        return format_html(
            '<div style="max-width:52em; line-height:2">{}</div>', rows)
```

Note: the `2px solid #000` outline marks the current selection and is browser
chrome, not a palette colour — it is not a session tint and does not belong in
the palette. If the test in Step 1 flags it, change it to `2px solid currentColor`.

- [ ] **Step 4: Wire it into the admin**

In `rota/admin.py`, add the imports:

```python
from django.utils.html import format_html
from rota.admin_widgets import TintSwatchSelect
from rota import palette
```

Extend `SessionTypeAdmin`:

```python
    list_display = ("name", "code", "category", "colour_swatch",
                    "fairness_tracked", "counts_toward_entitlement")

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "colour":
            kwargs["widget"] = TintSwatchSelect
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description="Colour")
    def colour_swatch(self, obj):
        tint = obj.tint
        return format_html(
            '<span style="display:inline-block; padding:2px 10px; '
            'border-radius:6px; background:{}; color:{}">{}</span>',
            tint.bg, tint.fg, tint.label)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_admin_colour.py -q`
Expected: PASS. If `test_no_colour_is_hardcoded_in_the_widget` fails on the
selection outline, replace `#000` with `currentColor` as noted in Step 3.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add rota/admin_widgets.py rota/admin.py tests/test_admin_colour.py
git commit -m "feat: admin shows session tints as colours, not names"
```

---

## Task 11: Light / dark / system toggle

**Files:**
- Create: `static/js/theme.js`
- Modify: `templates/base.html`
- Modify: `static/css/components.css`
- Create: `tests/test_theme_toggle.py`

**Interfaces:**
- Produces: a nav control cycling `system → light → dark`, persisted in `localStorage` under the key `rota-theme`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_theme_toggle.py`:

```python
"""The theme toggle.

Frontend Phase 1 built all three CSS states — bare :root, the
prefers-color-scheme block, and [data-theme] — and deliberately left the
toggle for later. This is later.

Three states, not two: a two-way toggle would strand the prefers-color-scheme
path that currently works for everyone who has not chosen.
"""

from pathlib import Path

import pytest
from django.conf import settings


def _base():
    return (settings.BASE_DIR / "templates" / "base.html").read_text()


def _script():
    return (settings.BASE_DIR / "static" / "js" / "theme.js").read_text()


def test_the_theme_is_applied_before_first_paint():
    """Applying it after the body renders means every load flashes the wrong
    theme before correcting itself."""
    import re
    base = _base()
    head = base[base.index("<head>"):base.index("</head>")]
    tags = re.findall(r"<script[^>]*theme\.js[^>]*>", head)
    assert tags, "theme.js is not loaded in <head>"
    assert not any("defer" in t or "async" in t for t in tags), (
        f"a deferred or async script runs after parsing, which is exactly the "
        f"flash this avoids: {tags}"
    )


def test_all_three_states_are_handled():
    script = _script()
    for state in ("system", "light", "dark"):
        assert f'"{state}"' in script or f"'{state}'" in script


def test_the_choice_is_persisted_and_read_back():
    script = _script()
    assert "localStorage" in script
    assert "rota-theme" in script


def test_storage_failures_do_not_break_the_page():
    """Private windows and blocked site data throw on access."""
    script = _script()
    assert "try" in script and "catch" in script


@pytest.mark.django_db
def test_the_control_is_in_the_nav(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'id="theme-toggle"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_theme_toggle.py -q`
Expected: FAIL — `static/js/theme.js` does not exist.

- [ ] **Step 3: Write the script**

Create `static/js/theme.js`:

```javascript
/* Light / dark / system, persisted per browser.
 *
 * Three states rather than two on purpose. The CSS has a bare :root, a
 * prefers-color-scheme block and a [data-theme] block; a two-way toggle would
 * strand the middle one, so anyone who had never touched the control would
 * lose the OS-follows behaviour the moment they touched it once.
 *
 * This runs in <head>, before the body is parsed, because applying the theme
 * after first paint means every page load flashes the wrong colours.
 */
(function () {
  var KEY = "rota-theme";
  var ORDER = ["system", "light", "dark"];
  var LABEL = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return ORDER.indexOf(v) === -1 ? "system" : v;
    } catch (e) {
      return "system";   // private window, or site data blocked
    }
  }

  function apply(state) {
    var root = document.documentElement;
    if (state === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", state);
    }
  }

  apply(read());   // before paint

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) { return; }

    function show(state) {
      button.textContent = LABEL[state];
      button.setAttribute("aria-label", LABEL[state] + " (click to change)");
    }

    show(read());
    button.addEventListener("click", function () {
      var next = ORDER[(ORDER.indexOf(read()) + 1) % ORDER.length];
      try { localStorage.setItem(KEY, next); } catch (e) { /* not persisted */ }
      apply(next);
      show(next);
    });
  });
})();
```

- [ ] **Step 4: Load it and add the control**

In `templates/base.html`, inside `<head>` and **before** the stylesheets, add:

```html
<script src="{% static 'js/theme.js' %}"></script>
```

It must not carry `defer` — a deferred script runs after parsing, which is the
flash this avoids.

In the nav, immediately before the `nav-spacer` span, add:

```html
  <button type="button" id="theme-toggle" class="btn btn-quiet">Theme</button>
```

- [ ] **Step 5: Give the control room**

In `static/css/components.css`, in the nav section, add:

```css
/* The toggle is a nav control, not a page action — quiet by default so it
   does not compete with the links beside it. */
#theme-toggle {
  font-size: var(--fs-xs);
  white-space: nowrap;
}
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_theme_toggle.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite and the asset checks**

Run:
```bash
.venv/bin/pytest -q
```
Expected: PASS, including `tests/test_self_hosted_assets.py`, which requires
every asset to be local — `theme.js` is served from `static/`, so it complies.

- [ ] **Step 8: Commit**

```bash
git add static/js/theme.js templates/base.html static/css/components.css tests/test_theme_toggle.py
git commit -m "feat: light/dark/system theme toggle in the nav"
```

---

## Task 12: Assisted fill checkbox default and label

**Files:**
- Modify: `templates/rota/fill.html`
- Modify: `rota/views/fill.py`
- Create: `tests/test_fill_form.py`

**Interfaces:**
- Consumes: `PracticeSettings.default_fill_session_type`.
- Produces: the fill view's context gains `default_type: SessionType | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fill_form.py`:

```python
"""The assisted fill form.

The checkbox defaulted off and did not say what "the default session type"
was. Worse, when none is configured it does nothing at all, silently — which
gets more misleading now that it defaults on.
"""

import pytest

from rota.models import PracticeSettings
from tests.factories import make_session_type


@pytest.mark.django_db
def test_the_checkbox_is_ticked_and_names_the_type(admin_client):
    settings = PracticeSettings.load()
    settings.default_fill_session_type = make_session_type("Routine", code="ROUT")
    settings.save()

    html = admin_client.get("/rota/fill/").content.decode()
    assert "Routine" in html
    assert "checked" in html
    assert "disabled" not in html


@pytest.mark.django_db
def test_with_no_default_type_the_box_is_disabled_and_explains_itself(admin_client):
    settings = PracticeSettings.load()
    settings.default_fill_session_type = None
    settings.save()

    html = admin_client.get("/rota/fill/").content.decode()
    assert "disabled" in html
    assert "practice settings" in html.lower(), (
        "the explanation should say where to fix it"
    )
    assert "checked" not in html, "a disabled box must not look ticked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fill_form.py -q`
Expected: FAIL — the box is unchecked and the type is not named.

- [ ] **Step 3: Pass the type to the template**

In `rota/views/fill.py`, inside `fill`, add the default type to the render context. Find the `render(...)` call and add:

```python
        "default_type": PracticeSettings.load().default_fill_session_type,
```

Add `PracticeSettings` to the imports at the top of the file if it is not already there.

- [ ] **Step 4: Update the template**

In `templates/rota/fill.html`, replace the checkbox field:

```html
      <div class="field">
        {% if default_type %}
        <label><input type="checkbox" name="fill_default" value="1" checked>
          Fill remaining empty cells with <strong>{{ default_type.name }}</strong></label>
        {% else %}
        <label><input type="checkbox" name="fill_default" value="1" disabled>
          Fill remaining empty cells with the default session type</label>
        <p class="field-help">No default session type is set, so this would do
          nothing. Set one in Practice settings to enable it.</p>
        {% endif %}
      </div>
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_fill_form.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS. If a test in `tests/test_fill_view.py` posts the fill form
without `fill_default` and asserts nothing was default-filled, it still holds —
the default is a rendering default, not a server-side one.

- [ ] **Step 7: Commit**

```bash
git add rota/views/fill.py templates/rota/fill.html tests/test_fill_form.py
git commit -m "feat: fill checkbox defaults on and names the session type"
```

---

## Final verification (after all tasks)

- [ ] `.venv/bin/pytest -q` — all pass. Only two pre-existing tests may have
      changed: the grid's `unavail` assertion (Task 5) and any fill-form
      assertion about the checkbox default (Task 12). Confirm with
      `git diff <base>..HEAD --stat -- tests/` that nothing else under
      `tests/` was modified rather than added.
- [ ] `DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run` —
      no changes detected.
- [ ] `grep -nE "#[0-9a-fA-F]{3,6}" static/css/components.css static/css/screens.css`
      — returns nothing.
- [ ] `DEBUG=1 .venv/bin/python manage.py check --deploy` — no `rota.E*` errors
      beyond the static-manifest one, which only applies to a deployed tree.
- [ ] `grep -rn "ctx.works_on" rota/services/fill/` — returns nothing.
- [ ] Manual pass in a browser, both themes: the grid's reversed empty states,
      a ghosted leave chip, the theme toggle through all three states, and the
      admin colour picker. None of these can be verified from the test suite.
- [ ] Use superpowers:verification-before-completion, then
      superpowers:finishing-a-development-branch.
