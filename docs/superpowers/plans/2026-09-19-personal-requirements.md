# Personal Requirements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new rule kind, "each of these named clinicians does this session type once every N weeks", with a fill pass that places it when due, a staffing-report table of last done / due / overdue, and a dashboard count.

**Architecture:** A `PersonalRequirement` model beside `RecurringCommitment`; one service module, `rota/services/personal.py`, that is the only reader of "last done" and "due" so the fill, the report and the dashboard agree; a fill pass `rota/services/fill/personal.py` that runs straight after coverage rules and places one session per due clinician per week in the cheapest free candidate, reusing the SDL placer's scoring; a section on the staffing report and a line on the Health card.

**Tech Stack:** Python 3.13, Django 5.2, SQLite, django-unfold admin, pytest + pytest-django, ruff. `manage.py` commands need `DEBUG=1`.

**Spec:** `docs/superpowers/specs/2026-09-15-personal-requirements-design.md` — read it first.

## Global Constraints

- No new dependencies. One migration, `0031`, after `0030_rotaentry_entered`.
- Every placement goes through `rota.services.entries.assign` with `manually_set=False` and `fill_reason="personal requirement"`, so re-runs and Delete drafts treat it like every other pass.
- Availability never fails open: a placement needs `ctx.available` and `ctx.is_free`, exactly as SDL does.
- The new pass carries a no-N+1 query test in the shape of `tests/test_commitments.py::test_commitments_pass_has_no_n_plus_one`.
- No pre-existing test assertion is weakened.
- Due is rolling: N weeks after the clinician's most recent session of the type, however it got there; a clinician with none is due from `active_from`. Nothing is placed before it is due, at most one per clinician per week.
- The pass runs immediately after `coverage.run` in `run_fill`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Full-suite verification is CI's job: push the branch and open a PR; run only the covering test files locally. `ruff check .` and `DEBUG=1 python manage.py makemigrations --check` must be clean after every task.
- Work on a new branch `feature/personal-requirements` from `master`.

## How to run things

```bash
cd /root/rota && source .venv/bin/activate
git checkout -b feature/personal-requirements master   # once, before Task 1
pytest tests/test_personal_model.py -q                   # one file
DEBUG=1 python manage.py makemigrations rota -n personalrequirement
DEBUG=1 python manage.py makemigrations --check
ruff check .
```

Factories in `tests/factories.py`: `make_group`, `make_clinician(name, group=None, **fields)`, `make_session_type(name, code=None, **fields)` (get-or-create by name), `make_pattern(clinician, weekdays=(0..4), parts=("AM","PM"), works=True)`, `make_entry(clinician, day=MON, part="AM", session_type=None, **fields)` (published, manually set). `MON` is `date(2026, 7, 20)`. Fixtures: `admin_user`, `admin_client`, `gp_client`. Every fill test starts with `PracticeSettings.load()`.

Existing helpers the plan uses: `rota/services/fill/accrual.py::week_monday(day)`; `rota/services/fill/scoring.py::impact_score(ctx, day, part)`; `rota/services/fill/types.py::UnfilledSlot(day, part, session_type, reason)` and `site_for(session_type)`; `FillContext` in `rota/services/fill/context.py` with `available`, `is_free`, `eligible_ids(st)`, `blocked(cid, day, st)`, `record(entry)`, `weeks()`, `open_day_set`, `start`, `end`; `rota/services/ranges.py::parse_int_list`, `validate_int_list(value, low, high, label)`; `rota/admin_forms.py::IntListCheckboxField`, `WEEKDAYS`.

---

## File map

| File | Responsibility |
|---|---|
| `rota/models/commitments.py` | `PersonalRequirement` beside `RecurringCommitment` (Task 1) |
| `rota/models/__init__.py` | export (Task 1) |
| `rota/migrations/0031_personalrequirement.py` | generated (Task 1) |
| `rota/checks.py` | `rota.E006` also reads the new model's `weekdays` (Task 1) |
| `tests/factories.py` | `make_requirement` (Task 1) |
| `rota/admin_forms.py` | `PersonalRequirementForm` (Task 2) |
| `rota/admin.py` | `PersonalRequirementAdmin` (Task 2) |
| `rota/admin_site.py` | sidebar item under Sessions & rules (Task 2) |
| `rota/services/personal.py` | new: `last_done`, `due_monday`, `status_from`, `status`, `live_requirements`, `overdue_count` (Task 3) |
| `rota/services/fill/context.py` | `days_with_type(cid, st_id)` (Task 4) |
| `rota/services/fill/personal.py` | new: the pass (Task 4) |
| `rota/services/fill/__init__.py` | wire the pass after `coverage.run` (Task 4) |
| `rota/views/reports.py`, `templates/rota/report_staffing.html` | the Personal requirements table (Task 5) |
| `rota/admin_dashboard.py` | Health line (Task 5) |
| `docs/admin/coverage-rules.md`, `docs/admin/day-to-day.md`, `README.md`, `docs/backlog.md` | Task 6 |

---

### Task 1: The model, migration, factory and deploy check

**Files:**
- Modify: `rota/models/commitments.py` (append), `rota/models/__init__.py`, `rota/checks.py:170-205`
- Create: `rota/migrations/0031_personalrequirement.py` (generated)
- Modify: `tests/factories.py` (append)
- Test: `tests/test_personal_model.py` (new)

**Interfaces:**
- Produces: `PersonalRequirement` with fields `session_type` (FK SessionType, PROTECT, `related_name="personal_requirements"`), `clinicians` (M2M Clinician, `related_name="personal_requirements"`), `interval_weeks` (PositiveSmallIntegerField, default 6), `part` (`"AM"|"PM"|"EITHER"`, default `"EITHER"`), `weekdays` (CharField, blank), `active_from` (DateField), `active_until` (DateField, null); methods `live_on(day) -> bool`, `applies_on(day) -> bool`, `parts_for() -> list[str]`, `weekday_list() -> list[int]`, `clean()`, `__str__` = `"<type name> every <N> weeks"`. Factory `make_requirement(session_type=None, clinicians=(), interval_weeks=6, **fields)` with `active_from` defaulting to `date(2020, 1, 6)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_personal_model.py
"""A personal requirement: each named clinician does a session type once
every N weeks, on no fixed day. The model holds the who/what/how-often;
the clock lives in rota/services/personal.py."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from rota.models import PersonalRequirement
from tests.factories import MON, make_clinician, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def test_str_names_the_type_and_the_interval():
    req = make_requirement(make_session_type("Nursing home round", code="NH"), interval_weeks=6)
    assert str(req) == "Nursing home round every 6 weeks"


def test_defaults():
    req = make_requirement()
    assert req.interval_weeks == 6 and req.part == "EITHER" and req.weekdays == ""
    assert req.parts_for() == ["AM", "PM"] and req.weekday_list() == []


def test_clean_rejects_a_zero_interval():
    req = make_requirement()
    req.interval_weeks = 0
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "interval_weeks" in exc.value.message_dict


def test_clean_rejects_a_bad_weekday_list_and_a_backwards_window():
    req = make_requirement()
    req.weekdays = "1,,3"
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "weekdays" in exc.value.message_dict
    req.weekdays = "7"
    with pytest.raises(ValidationError):
        req.clean()
    req.weekdays = "1,3"
    req.active_until = req.active_from - timedelta(days=1)
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "active_until" in exc.value.message_dict


def test_live_on_and_applies_on():
    req = make_requirement(active_from=MON, active_until=MON + timedelta(days=13),
                           weekdays="1,3")
    assert not req.live_on(MON - timedelta(days=1))
    assert req.live_on(MON) and req.live_on(MON + timedelta(days=13))
    assert not req.live_on(MON + timedelta(days=14))
    assert not req.applies_on(MON)                       # Monday, not ticked
    assert req.applies_on(MON + timedelta(days=1))       # Tuesday
    assert not req.applies_on(MON + timedelta(days=15))  # Tuesday, but after the window
    blank = make_requirement(active_from=MON)
    assert blank.applies_on(MON) and blank.applies_on(MON + timedelta(days=6))


def test_parts_for_a_single_half():
    assert make_requirement(part="PM").parts_for() == ["PM"]


def test_a_stored_weekday_list_that_no_longer_parses_stops_at_deploy():
    from rota.checks import stored_ranges_parse
    req = make_requirement()
    PersonalRequirement.objects.filter(pk=req.pk).update(weekdays="1,,3")
    errors = stored_ranges_parse(None)
    assert len(errors) == 1 and errors[0].id == "rota.E006"
    assert "Personal requirement" in errors[0].msg


def test_clinicians_is_a_many_to_many_in_both_directions():
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    req = make_requirement(clinicians=[a, b])
    assert set(req.clinicians.all()) == {a, b}
    assert list(a.personal_requirements.all()) == [req]
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_personal_model.py -q`
Expected: `ImportError: cannot import name 'PersonalRequirement'`.

- [ ] **Step 3: The model**

Append to `rota/models/commitments.py` (add `from django.core.exceptions import ValidationError` and `from rota.services.ranges import parse_int_list, validate_int_list` to its imports — `catalog.py` already imports `ranges`, so there is no cycle):

```python
class PersonalRequirement(models.Model):
    """Each named clinician does this session type once every N weeks, on
    no fixed day: an aim to fit in, not a fixture. A coverage rule counts
    practice-wide, so one keen GP could satisfy six people's rounds; a
    recurring commitment pins a weekday and drops a missed occurrence.
    The clock — last done, due — lives in rota/services/personal.py, the
    one reader for the fill, the report and the dashboard."""

    PART_CHOICES = [("AM", "AM"), ("PM", "PM"), ("EITHER", "Either")]

    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT,
        related_name="personal_requirements",
        help_text="What each of them owes.")
    clinicians = models.ManyToManyField(
        "rota.Clinician", related_name="personal_requirements",
        help_text="Who owes it. Each must be eligible for the session type.")
    interval_weeks = models.PositiveSmallIntegerField(
        default=6, help_text="One every this many weeks, per clinician, "
                             "counted from their last one.")
    part = models.CharField(
        max_length=6, choices=PART_CHOICES, default="EITHER",
        help_text="Which half-day it may take.")
    weekdays = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Days it may fall on. Blank means every open day. Monday=0.")
    active_from = models.DateField(
        help_text="A clinician with none yet is due from this date.")
    active_until = models.DateField(
        null=True, blank=True, help_text="Inclusive. Blank means open-ended.")

    class Meta:
        ordering = ["session_type__name", "interval_weeks", "id"]
        verbose_name = "personal requirement"

    def __str__(self):
        return f"{self.session_type.name} every {self.interval_weeks} weeks"

    def clean(self):
        super().clean()
        if self.interval_weeks < 1:
            raise ValidationError({"interval_weeks": "At least one week."})
        validate_int_list(self.weekdays, 0, 6, "weekdays")
        if self.active_until and self.active_until < self.active_from:
            raise ValidationError(
                {"active_until": "Active until is before active from."})

    def live_on(self, day):
        return self.active_from <= day and (
            self.active_until is None or day <= self.active_until)

    def weekday_list(self):
        return parse_int_list(self.weekdays)

    def applies_on(self, day):
        """In force on `day` and on an allowed weekday. Blank weekdays is
        every day; callers restrict to open days."""
        if not self.live_on(day):
            return False
        return not self.weekdays or day.weekday() in self.weekday_list()

    def parts_for(self):
        return ["AM", "PM"] if self.part == "EITHER" else [self.part]
```

`rota/models/__init__.py`: `from .commitments import PersonalRequirement, RecurringCommitment` and add `"PersonalRequirement"` to `__all__`.

- [ ] **Step 4: Migration**

Run: `DEBUG=1 python manage.py makemigrations rota -n personalrequirement`
Expected: `rota/migrations/0031_personalrequirement.py` with one `CreateModel`, depending on `0030_rotaentry_entered`.

- [ ] **Step 5: Factory and deploy check**

Append to `tests/factories.py`:

```python
def make_requirement(session_type=None, clinicians=(), interval_weeks=6, **kw):
    """A personal requirement live since long before MON, so a clinician
    with no session of the type is due from the first week of any run."""
    from rota.models import PersonalRequirement
    kw.setdefault("active_from", date(2020, 1, 6))  # a Monday
    req = PersonalRequirement.objects.create(
        session_type=session_type or make_session_type("Nursing home round", code="NH"),
        interval_weeks=interval_weeks, **kw)
    req.clinicians.set(clinicians)
    return req
```

In `rota/checks.py`, `stored_ranges_parse`: import `PersonalRequirement` alongside `CoverageRule, PracticeSettings`, and after the coverage-rule loop, inside the same `try`:

```python
        for req in PersonalRequirement.objects.select_related("session_type"):
            msg = problem("weekdays", req.weekdays, 0, 6)
            if msg:
                found.append(f"Personal requirement “{req}” weekdays={req.weekdays!r}: {msg}")
```

- [ ] **Step 6: Run the tests and checks**

Run: `pytest tests/test_personal_model.py tests/test_deploy_checks.py tests/test_models_v2.py -q && ruff check . && DEBUG=1 python manage.py makemigrations --check`
Expected: pass, clean, "No changes detected".

- [ ] **Step 7: Commit**

```bash
git add rota/models/commitments.py rota/models/__init__.py rota/migrations/0031_personalrequirement.py rota/checks.py tests/factories.py tests/test_personal_model.py
git commit -m "feat: a personal requirement — each named clinician does a session type once every N weeks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Admin form, registration and sidebar

**Files:**
- Modify: `rota/admin_forms.py` (append `PersonalRequirementForm`; import `Clinician, PersonalRequirement`)
- Modify: `rota/admin.py` (register after `RecurringCommitmentAdmin`; import `PersonalRequirement` and `PersonalRequirementForm`)
- Modify: `rota/admin_site.py` (one `_item` after "Coverage rules")
- Modify: `tests/test_admin_render.py` (`rows` fixture gains `"personalrequirement"`)
- Test: `tests/test_personal_admin.py` (new)

**Interfaces:**
- Consumes: `PersonalRequirement`, `make_requirement` (Task 1); `SessionType.is_eligible(clinician)`.
- Produces: `PersonalRequirementForm` (a `ModelForm` with `weekdays` as `IntListCheckboxField` and a `clean()` that refuses clinicians not eligible for the type); the admin at `/admin/rota/personalrequirement/`; sidebar entry "Personal requirements".

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_personal_admin.py
"""The admin for personal requirements: weekdays as checkboxes like a
coverage rule, only active clinicians offered, and a clinician who is not
eligible for the session type refused by name."""

import pytest

from tests.factories import make_clinician, make_group, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def _data(nh, people, **extra):
    data = {"session_type": nh.id, "clinicians": [c.id for c in people],
            "interval_weeks": 6, "part": "EITHER", "weekdays": [],
            "active_from": "2026-01-05", "active_until": ""}
    data.update(extra)
    return data


def test_the_form_refuses_a_clinician_not_eligible_for_the_type():
    from rota.admin_forms import PersonalRequirementForm
    partners = make_group("Partner", display_order=1)
    ann = make_clinician("Ann Able", group=partners)
    bob = make_clinician("Bob Baker")
    nh = make_session_type("Nursing home round", code="NH")
    nh.allowed_groups.add(partners)
    form = PersonalRequirementForm(data=_data(nh, [ann, bob]))
    assert not form.is_valid()
    assert "Bob Baker" in str(form.errors["clinicians"])
    assert "Ann Able" not in str(form.errors["clinicians"])
    ok = PersonalRequirementForm(data=_data(nh, [ann]))
    assert ok.is_valid(), ok.errors


def test_the_form_offers_active_clinicians_only_and_stores_weekdays_as_a_list():
    from rota.admin_forms import PersonalRequirementForm
    ann = make_clinician("Ann Able")
    make_clinician("Gone Away", active=False)
    nh = make_session_type("Nursing home round", code="NH")
    form = PersonalRequirementForm(data=_data(nh, [ann], weekdays=["1", "3"]))
    assert [c.name for c in form.fields["clinicians"].queryset] == ["Ann Able"]
    assert form.is_valid(), form.errors
    req = form.save()
    assert req.weekdays == "1,3" and list(req.clinicians.all()) == [ann]


def test_the_changelist_and_form_render_and_the_sidebar_links_it(admin_client):
    ann = make_clinician("Ann Able")
    req = make_requirement(clinicians=[ann])
    html = admin_client.get("/admin/rota/personalrequirement/").content.decode()
    assert "Nursing home round" in html and "6 weeks" in html
    assert admin_client.get(f"/admin/rota/personalrequirement/{req.pk}/change/").status_code == 200
    index = admin_client.get("/admin/").content.decode()
    assert "Personal requirements" in index
    assert "/admin/rota/personalrequirement/" in index
```

In `tests/test_admin_render.py`, add `make_requirement` to the factories import and `"personalrequirement": make_requirement(st, [c]),` to the `rows` dict (after `"recurringcommitment"`).

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_personal_admin.py -q`
Expected: `ImportError: cannot import name 'PersonalRequirementForm'`.

- [ ] **Step 3: The form**

Append to `rota/admin_forms.py` (extend its model import to `from rota.models import Clinician, CoverageRule, PersonalRequirement, PracticeSettings`):

```python
class PersonalRequirementForm(forms.ModelForm):
    weekdays = IntListCheckboxField(choices=WEEKDAYS, label="Weekdays",
                                    help_text="None ticked means every open day.")

    class Meta:
        model = PersonalRequirement
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clinicians"].queryset = (
            Clinician.objects.filter(active=True).order_by("name"))

    def clean(self):
        # The model cannot see its M2M before save, so eligibility is
        # checked here: the fill would otherwise skip the person silently.
        cleaned = super().clean()
        st, people = cleaned.get("session_type"), cleaned.get("clinicians")
        if st and people:
            wrong = [c.name for c in people if not st.is_eligible(c)]
            if wrong:
                self.add_error("clinicians",
                               f"Not eligible for {st.name}: {', '.join(wrong)}. "
                               "Allow them on the session type first.")
        return cleaned
```

- [ ] **Step 4: The admin and the sidebar**

In `rota/admin.py`: add `PersonalRequirement` to the `.models` import and `PersonalRequirementForm` to the `.admin_forms` import; after `RecurringCommitmentAdmin`:

```python
@admin.register(PersonalRequirement)
class PersonalRequirementAdmin(ModelAdmin):
    form = PersonalRequirementForm
    list_display = ("session_type", "every", "part", "weekdays",
                    "active_from", "active_until", "people")
    list_filter = ("session_type",)
    filter_horizontal = ("clinicians",)
    fieldsets = (
        ("What", {
            "fields": ("session_type", "clinicians", "interval_weeks", "part"),
            "description": "Each named clinician does this session type once "
                           "every N weeks, counted from their last one, on any "
                           "allowed day they are free. An aim to fit in, not a "
                           "fixture: for a fixed weekday use a recurring "
                           "commitment; for a practice-wide count use a coverage "
                           "rule.",
        }),
        ("When", {"fields": ("weekdays", "active_from", "active_until")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("session_type") \
            .prefetch_related("clinicians")

    @admin.display(description="Every")
    def every(self, obj):
        return f"{obj.interval_weeks} weeks"

    @admin.display(description="Clinicians")
    def people(self, obj):
        return len(obj.clinicians.all())
```

In `rota/admin_site.py`, in the "Sessions & rules" group after the Coverage rules item:

```python
            _item("Personal requirements", "person_check", rl("admin:rota_personalrequirement_changelist")),
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_personal_admin.py tests/test_admin_render.py tests/test_admin_site.py -q && ruff check .`
Expected: pass. If `filter_horizontal` renders oddly under unfold, keep it — unfold ships its own styling for it; the render test only asserts 200 and no leaked template text.

- [ ] **Step 6: Commit**

```bash
git add rota/admin_forms.py rota/admin.py rota/admin_site.py tests/test_admin_render.py tests/test_personal_admin.py
git commit -m "feat: personal requirements in the admin, with eligibility checked on the form

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The clock — `rota/services/personal.py`

**Files:**
- Create: `rota/services/personal.py`
- Test: `tests/test_personal_service.py` (new)

**Interfaces:**
- Consumes: `PersonalRequirement` (Task 1); `week_monday` from `rota/services/fill/accrual.py`.
- Produces:
  - `last_done(requirement, clinician_ids, before, *, include_drafts=True) -> dict[int, date | None]` — most recent entry day of the type per clinician on `day < before`; one query.
  - `due_monday(requirement, last: date | None) -> date` — a Monday.
  - `Status(last, due, weeks_overdue, label)` frozen dataclass; `label` is `"on track"`, `"due this week"` or `"<n> week(s) overdue"`.
  - `status_from(requirement, last, today) -> Status` (pure); `status(requirement, clinician_id, today, *, include_drafts=True) -> Status` (queries).
  - `live_requirements(start, end=None)` — queryset of requirements live anywhere in `start..end` (`end` defaults to `start`, so one argument means "live on that day"), `select_related("session_type")`, clinicians prefetched active-only in `("display_order", "name")` order.
  - `overdue_count(today, *, include_drafts=True) -> int` — (requirement, clinician) pairs with `weeks_overdue > 0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_personal_service.py
"""The rolling clock: a clinician is due N weeks after their most recent
session of the type, however it got there; with none, from active_from.
Once due it stays due until one is placed."""

from datetime import date, timedelta

import pytest

from rota.services import personal
from tests.factories import MON, make_clinician, make_entry, make_requirement, make_session_type

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)


def _setup():
    nh = make_session_type("Nursing home round", code="NH")
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    return nh, a, b, make_requirement(nh, [a, b], interval_weeks=6, active_from=MON)


def test_last_done_is_per_clinician_and_respects_before_and_drafts():
    nh, a, b, req = _setup()
    make_entry(a, day=MON - timedelta(days=30), session_type=nh)
    make_entry(a, day=MON - timedelta(days=2), session_type=nh, is_published=False)
    make_entry(b, day=MON, session_type=nh)
    last = personal.last_done(req, [a.id, b.id], MON)
    assert last == {a.id: MON - timedelta(days=2), b.id: None}
    published = personal.last_done(req, [a.id, b.id], MON, include_drafts=False)
    assert published[a.id] == MON - timedelta(days=30)
    assert personal.last_done(req, [b.id], MON + timedelta(days=1))[b.id] == MON


def test_last_done_ignores_other_session_types():
    nh, a, b, req = _setup()
    make_entry(a, day=MON - timedelta(days=2), session_type=make_session_type("Routine"))
    assert personal.last_done(req, [a.id], MON)[a.id] is None


def test_due_from_the_last_one_or_from_active_from():
    nh, a, b, req = _setup()
    assert personal.due_monday(req, None) == MON
    assert personal.due_monday(req, TUE) == MON + timedelta(days=42)
    assert personal.due_monday(req, MON + timedelta(days=41)) == MON + timedelta(days=35 + 42)


def test_status_across_a_year_boundary():
    nh, a, b, req = _setup()
    today = date(2027, 1, 4)  # a Monday
    s = personal.status_from(req, date(2026, 11, 10), today)
    assert s.due == date(2026, 12, 21) and s.weeks_overdue == 2
    assert s.label == "2 weeks overdue"
    assert personal.status_from(req, date(2026, 11, 24), today).label == "due this week"
    assert personal.status_from(req, date(2026, 12, 1), today).label == "on track"
    assert personal.status_from(req, date(2026, 11, 17), today).label == "1 week overdue"


def test_status_queries_the_clinicians_last_including_today():
    nh, a, b, req = _setup()
    make_entry(a, day=MON, session_type=nh)
    s = personal.status(req, a.id, MON)
    assert s.last == MON and s.due == MON + timedelta(days=42) and s.label == "on track"
    assert personal.status(req, b.id, MON).label == "due this week"


def test_live_requirements_and_overdue_count():
    nh, a, b, req = _setup()
    make_requirement(make_session_type("Later", code="LT"), [a], active_from=MON + timedelta(days=7))
    make_clinician("Gone Away", active=False).personal_requirements.add(req)
    live = list(personal.live_requirements(MON))
    assert live == [req]
    assert [c.name for c in live[0].clinicians.all()] == ["Ann Able", "Bob Baker"]
    assert personal.overdue_count(MON) == 0             # both due this week, not overdue
    assert personal.overdue_count(MON + timedelta(days=7)) == 2
    make_entry(a, day=MON + timedelta(days=3), session_type=nh)
    assert personal.overdue_count(MON + timedelta(days=7)) == 1


def test_overdue_count_is_two_queries_per_requirement(django_assert_max_num_queries):
    nh, a, b, req = _setup()
    with django_assert_max_num_queries(3):
        personal.overdue_count(MON + timedelta(days=7))
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_personal_service.py -q`
Expected: `ModuleNotFoundError: No module named 'rota.services.personal'`.

- [ ] **Step 3: The service**

```python
# rota/services/personal.py
"""The clock for personal requirements — the one reader of "last done"
and "due", so the fill pass, the staffing report and the dashboard
cannot disagree.

Due is rolling: N weeks after the clinician's most recent session of the
type, however it got there (fill, hand, import). A clinician with none
yet is due from the requirement's active_from. Once due it stays due
until one is placed; a slip restarts the clock from when it actually
happened, so the aim is "never more than N weeks apart".
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Max, Prefetch, Q

from rota.models import Clinician, PersonalRequirement, RotaEntry
from rota.services.fill.accrual import week_monday


@dataclass(frozen=True)
class Status:
    last: date | None
    due: date            # the Monday of the week it is due
    weeks_overdue: int
    label: str           # "on track" | "due this week" | "<n> week(s) overdue"


def last_done(requirement, clinician_ids, before, *, include_drafts=True):
    """{clinician_id: most recent day of the type strictly before `before`,
    or None}. One query. Drafts count for admins: a planned round is
    still a round; a GP's view passes include_drafts=False."""
    ids = list(clinician_ids)
    qs = RotaEntry.objects.filter(
        session_type_id=requirement.session_type_id,
        clinician_id__in=ids, day__lt=before)
    if not include_drafts:
        qs = qs.filter(is_published=True)
    found = {row["clinician_id"]: row["last"]
             for row in qs.values("clinician_id").annotate(last=Max("day"))}
    return {cid: found.get(cid) for cid in ids}


def due_monday(requirement, last):
    if last is None:
        return week_monday(requirement.active_from)
    return week_monday(last) + timedelta(days=7 * requirement.interval_weeks)


def status_from(requirement, last, today):
    due = due_monday(requirement, last)
    this_week = week_monday(today)
    weeks_overdue = max((this_week - due).days // 7, 0)
    if weeks_overdue:
        label = f"{weeks_overdue} week{'' if weeks_overdue == 1 else 's'} overdue"
    elif due == this_week:
        label = "due this week"
    else:
        label = "on track"
    return Status(last, due, weeks_overdue, label)


def status(requirement, clinician_id, today, *, include_drafts=True):
    last = last_done(requirement, [clinician_id], today + timedelta(days=1),
                     include_drafts=include_drafts)[clinician_id]
    return status_from(requirement, last, today)


def live_requirements(start, end=None):
    """Requirements in force anywhere in `start..end` — active before the
    end, not finished before the start — with their active clinicians in
    grid order. One argument means live on that day. Two queries however
    many there are."""
    end = end or start
    return (PersonalRequirement.objects
            .filter(active_from__lte=end)
            .filter(Q(active_until__isnull=True) | Q(active_until__gte=start))
            .select_related("session_type")
            .prefetch_related(Prefetch(
                "clinicians",
                queryset=Clinician.objects.filter(active=True)
                .order_by("display_order", "name"))))


def overdue_count(today, *, include_drafts=True):
    """(requirement, clinician) pairs overdue today — the Health line."""
    n = 0
    for req in live_requirements(today):
        people = list(req.clinicians.all())
        last = last_done(req, [c.id for c in people], today + timedelta(days=1),
                         include_drafts=include_drafts)
        n += sum(1 for c in people
                 if status_from(req, last[c.id], today).weeks_overdue > 0)
    return n
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_personal_service.py -q && ruff check .`
Expected: pass. If the query-count test fails, count the queries `live_requirements` costs (one for requirements, one for the prefetch) plus one `last_done` per requirement; the cap of 3 is for one requirement — if the prefetch costs more, raise the cap to the real number and say why in the assertion message.

- [ ] **Step 5: Commit**

```bash
git add rota/services/personal.py tests/test_personal_service.py
git commit -m "feat: the personal-requirement clock — last done, due, status, overdue count

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The fill pass

**Files:**
- Modify: `rota/services/fill/context.py` (`_index_entry`, add `days_with_type`)
- Create: `rota/services/fill/personal.py`
- Modify: `rota/services/fill/__init__.py:5,22-26`
- Test: `tests/test_personal_fill.py` (new)

**Interfaces:**
- Consumes: `personal.last_done`, `personal.due_monday`, `personal.live_requirements(start, end)` (Task 3); `PersonalRequirement.applies_on`, `parts_for` (Task 1); `FillContext.available/is_free/eligible_ids/blocked/record/weeks/open_day_set/start/end`; `impact_score`; `entries.assign`; `UnfilledSlot`, `site_for`.
- Produces: `FillContext.days_with_type(clinician_id, session_type_id) -> set[date]`; `fill.personal.run(ctx, actor, result)`; `fill.personal.FILL_REASON = "personal requirement"`; `run_fill` calls it immediately after `coverage.run`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_personal_fill.py
"""The personal-requirement pass: when a clinician is due, one session of
the type in that week's cheapest free candidate; nothing before it is
due; at most one per clinician per week; a miss is reported and rolls
into the next week."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rota.models import CoverageRule, PracticeSettings, RotaEntry
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_requirement, make_session_type)

pytestmark = pytest.mark.django_db
TUE, WED, THU, FRI = (MON + timedelta(days=i) for i in range(1, 5))
NEXT = MON + timedelta(days=7)


def _gp(name="Ann Able", **pattern):
    c = make_clinician(name)
    make_pattern(c, **pattern)
    return c


def _placed(nh):
    return list(RotaEntry.objects.filter(session_type=nh, manually_set=False)
                .order_by("day", "part").values_list("day", "part"))


def test_a_clinician_with_none_yet_is_placed_in_the_first_live_week(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], active_from=MON)
    result = run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(MON, "AM")]
    e = RotaEntry.objects.get(session_type=nh)
    assert e.fill_reason == "personal requirement" and not e.manually_set and not e.is_published
    assert result.created == 1 and result.unfilled == []


def test_not_due_yet_means_nothing_placed(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=6)
    make_entry(c, day=MON - timedelta(days=21), session_type=nh)
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == []


def test_seven_weeks_since_the_last_one_is_placed_in_the_first_week(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=6)
    make_entry(c, day=MON - timedelta(days=49), session_type=nh)
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(MON, "AM")]


def test_a_hand_placed_session_in_the_window_resets_the_clock(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=2)
    make_entry(c, day=WED, session_type=nh)          # by hand, week 1
    run_fill(admin_user, MON, NEXT + timedelta(days=4))  # two weeks
    assert _placed(nh) == [], "week 1 is done by hand and week 2 is not yet due"


def test_no_free_session_is_reported_and_tried_again_next_week(admin_user):
    PracticeSettings.load()
    c = _gp(weekdays=(0,), parts=("AM",))          # Monday mornings only
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    make_entry(c, day=MON, part="AM", session_type=make_session_type("Routine"))
    result = run_fill(admin_user, MON, NEXT + timedelta(days=4))
    assert _placed(nh) == [(NEXT, "AM")]
    misses = [u for u in result.unfilled if u.session_type == nh.name]
    assert [(u.day, u.part, u.reason) for u in misses] == [(MON, None, "no free session")]


def test_part_and_weekdays_restrict_the_candidates(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], part="PM", weekdays="3")
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(THU, "PM")]


def test_the_cheapest_session_wins(admin_user):
    """Where the most other people are available and free — the session
    that can best spare one, as SDL already chooses."""
    PracticeSettings.load()
    c = _gp()
    for name in ("Bob Baker", "Cal Cole"):
        _gp(name, weekdays=(2,))                    # Wednesdays only
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(WED, "AM")]


def test_a_same_day_block_is_honoured(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    duty = make_session_type("Duty", code="DUTY")
    duty.blocks_same_day.add(nh)
    make_entry(c, day=MON, part="AM", session_type=duty)
    make_requirement(nh, [c])
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(TUE, "AM")]


def test_coverage_rules_take_people_first(admin_user):
    PracticeSettings.load()
    c = _gp(weekdays=(0,), parts=("AM",))
    duty = make_session_type("Duty", code="DUTY")
    CoverageRule.objects.create(session_type=duty, parts="AM", weekdays="0", priority=1)
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    result = run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(session_type=duty, day=MON, part="AM").exists()
    assert _placed(nh) == []
    assert any(u.session_type == nh.name and u.reason == "no free session"
               for u in result.unfilled)


def test_an_ineligible_clinician_is_skipped_not_placed(admin_user):
    from tests.factories import make_group
    PracticeSettings.load()
    partners = make_group("Partner", display_order=1)
    c = _gp()                                       # not a partner
    nh = make_session_type("Nursing home round", code="NH")
    nh.allowed_groups.add(partners)
    make_requirement(nh, [c])
    result = run_fill(admin_user, MON, FRI)
    assert _placed(nh) == []
    assert any(u.reason == "no free session" for u in result.unfilled)


def test_the_pass_has_no_n_plus_one(admin_user):
    PracticeSettings.load()
    nh = make_session_type("Nursing home round", code="NH")
    people = [_gp(n) for n in ("Ann Able", "Bob Baker", "Cal Cole", "Dan Dee")]
    make_requirement(nh, people)
    with CaptureQueriesContext(connection) as four:
        run_fill(admin_user, MON, FRI)
    RotaEntry.objects.all().delete()
    more = [_gp(n) for n in ("Eve East", "Fay Fern", "Gus Gale", "Hal Hart")]
    make_requirement(make_session_type("Coil clinic", code="COIL"), more)
    with CaptureQueriesContext(connection) as eight:
        run_fill(admin_user, MON, FRI)
    selects = lambda ctx: [q["sql"] for q in ctx.captured_queries  # noqa: E731
                           if q["sql"].lstrip().upper().startswith("SELECT")
                           and "rota_rotaentry" in q["sql"]
                           and "MAX(" in q["sql"].upper()]
    assert len(selects(eight)) == 2 and len(selects(four)) == 1, (
        "one last-done query per requirement, none per clinician or week")
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_personal_fill.py -q`
Expected: every test fails — the pass does not exist, so nothing of the type is placed.

- [ ] **Step 3: `days_with_type` on the context**

In `rota/services/fill/context.py`, in `__init__` alongside the other index dicts add `self._type_days = {}`, and in `_index_entry` after the `_clinician_type_count` update:

```python
        self._type_days.setdefault(
            (entry.clinician_id, entry.session_type_id), set()).add(entry.day)
```

and after `clinician_type_count`:

```python
    def days_with_type(self, cid, st_id):
        """The days in [start, end] on which this clinician already holds
        this session type — present at prefetch or recorded since. The
        personal-requirement pass reads it to fold a hand-placed session
        into a clinician's rolling clock."""
        return self._type_days.get((cid, st_id), set())
```

- [ ] **Step 4: The pass**

```python
# rota/services/fill/personal.py
"""Personal requirements: each named clinician does a session type once
every N weeks, on no fixed day.

Runs straight after coverage rules, so Duty and standing cover take
first pick of people, and before mentoring, SDL and default fill. For
each week in the run, each clinician who is due gets one session in that
week's cheapest free candidate — the session where the most other people
are available, as SDL chooses. A placement moves the clinician's "last
done" forward. No candidate means "no free session" for that week and
another try next week: due stays due.
"""

from datetime import timedelta

from rota.services import entries, personal

from .accrual import week_monday
from .scoring import impact_score
from .types import UnfilledSlot, site_for

FILL_REASON = "personal requirement"


def run(ctx, actor, result):
    # Live anywhere in the window; applies_on() gates each day inside it.
    for req in personal.live_requirements(ctx.start, ctx.end):
        st = req.session_type
        people = list(req.clinicians.all())
        if not people:
            continue
        last = personal.last_done(req, [c.id for c in people], ctx.start)
        for c in people:
            in_window = sorted(ctx.days_with_type(c.id, st.id))
            for wm in ctx.weeks():
                week_end = wm + timedelta(days=6)
                seen = [d for d in in_window
                        if d <= week_end and (last[c.id] is None or d > last[c.id])]
                if seen:
                    last[c.id] = max(seen)
                if wm < personal.due_monday(req, last[c.id]):
                    continue
                placed = _place(ctx, actor, result, req, c, wm)
                if placed is None:
                    result.unfilled.append(
                        UnfilledSlot(wm, None, st.name, "no free session"))
                else:
                    last[c.id] = placed


def _place(ctx, actor, result, req, clinician, wm):
    """One session for `clinician` in the week of `wm`, or None."""
    st = req.session_type
    candidates = []
    for i in range(7):
        day = wm + timedelta(days=i)
        if not (ctx.start <= day <= ctx.end and day in ctx.open_day_set
                and req.applies_on(day)):
            continue
        for part in req.parts_for():
            if (ctx.available(clinician.id, day, part)
                    and ctx.is_free(clinician.id, day, part)
                    and clinician.id in ctx.eligible_ids(st)
                    and not ctx.blocked(clinician.id, day, st)):
                candidates.append((day, part))
    if not candidates:
        return None
    candidates.sort(key=lambda dp: (-impact_score(ctx, dp[0], dp[1]), dp[0], dp[1]))
    day, part = candidates[0]
    entry = entries.assign(actor, clinician, day, part, st, site=site_for(st),
                           manually_set=False, fill_reason=FILL_REASON)
    ctx.record(entry)
    result.created += 1
    return day
```

`rota/services/fill/__init__.py`: `from . import commitments, coverage, mentoring, personal, trainees` and, after `coverage.run(ctx, actor, result)`:

```python
    personal.run(ctx, actor, result)
```

Check for an import cycle: `rota/services/personal.py` imports `rota.services.fill.accrual`, and `rota/services/fill/personal.py` imports `rota.services.personal`. `fill/__init__.py` importing `.personal` at module load pulls `rota.services.personal`, which pulls `rota.services.fill.accrual` — a submodule of a package already being initialised. Python resolves that because `accrual` has no dependency back on `fill/__init__`. If the import still fails, move `from rota.services.fill.accrual import week_monday` in `rota/services/personal.py` to a local import inside `due_monday` and `status_from` and say so in the report.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_personal_fill.py tests/test_commitments.py tests/test_coverage_v2.py tests/test_trainee_fill.py tests/test_fill.py tests/test_fill_integration.py -q && ruff check .`
Expected: pass. If `test_the_cheapest_session_wins` picks Monday, check `impact_score`: it counts clinicians `available` and `free` at (day, part) — the two Wednesday-only people must have patterns (they do, via `_gp`) and no entries.

- [ ] **Step 6: Commit**

```bash
git add rota/services/fill/context.py rota/services/fill/personal.py rota/services/fill/__init__.py tests/test_personal_fill.py
git commit -m "feat: the fill places a personal requirement when a clinician is due, after coverage rules

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The staffing report table and the Health line

**Files:**
- Modify: `rota/views/reports.py` (`report_staffing` context; add `_personal_rows`)
- Modify: `templates/rota/report_staffing.html` (a section after the accrual table)
- Modify: `rota/admin_dashboard.py` (`health()` gains a line)
- Test: `tests/test_personal_report.py` (new); `tests/test_admin_dashboard.py` (one assertion in `test_health_lines_count_and_link`)

**Interfaces:**
- Consumes: `personal.live_requirements`, `personal.last_done`, `personal.status_from`, `personal.overdue_count` (Task 3).
- Produces: context key `personal_rows`: list of `{"requirement": str, "clinician": Clinician, "last": date | None, "due": date, "label": str, "overdue": bool}` sorted overdue first, then due this week, then on track, then by clinician name; a `<h2 id="personal">` section; Health line `"Clinicians overdue a personal requirement"` linking to `reverse("report-staffing") + "#personal"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_personal_report.py
"""Where a personal requirement's state is seen: a table on the staffing
report — requirement, clinician, last done, due, status — sorted overdue
first, and a count on the dashboard's Health card."""

from datetime import date, timedelta

import pytest

from rota.models import PracticeSettings
from rota.services.fill.accrual import week_monday
from tests.factories import make_clinician, make_entry, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def _setup():
    """Offsets from this week's Monday, so the expected states do not
    depend on which weekday the suite runs on."""
    PracticeSettings.load()
    today = date.today()
    wm = week_monday(today)
    nh = make_session_type("Nursing home round", code="NH")
    ann, bob, cal = (make_clinician(n) for n in ("Ann Able", "Bob Baker", "Cal Cole"))
    req = make_requirement(nh, [ann, bob, cal], interval_weeks=6,
                           active_from=today - timedelta(days=200))
    make_entry(ann, day=wm - timedelta(days=7), session_type=nh)         # due in 5 weeks: on track
    make_entry(bob, day=wm - timedelta(days=42), session_type=nh)        # due this week
    make_entry(cal, day=wm - timedelta(days=56), session_type=nh,
               is_published=False)                                       # a draft: 2 weeks overdue
    return today, nh, req


def test_the_report_lists_each_clinician_overdue_first(admin_client):
    today, nh, req = _setup()
    html = admin_client.get("/reports/staffing/").content.decode()
    assert '<h2 id="personal">Personal requirements</h2>' in html
    section = html[html.index('id="personal"'):]
    assert "Nursing home round, every 6 weeks" in section
    assert section.index("Cal Cole") < section.index("Bob Baker") < section.index("Ann Able")
    assert "2 weeks overdue" in section and "due this week" in section and "on track" in section
    assert f"week of {week_monday(today):%-d %b}" in section
    assert 'class="warn">2 weeks overdue' in section


def test_a_gp_sees_the_table_without_drafts(gp_client):
    today, nh, req = _setup()
    section = gp_client.get("/reports/staffing/").content.decode()
    section = section[section.index('id="personal"'):]
    # Cal's only session is a draft, so to a GP Cal has never done one:
    # due from active_from, long overdue.
    cal = section[section.index("Cal Cole"):section.index("Cal Cole") + 300]
    assert "never" in cal and "overdue" in cal


def test_no_section_without_a_live_requirement(admin_client):
    PracticeSettings.load()
    make_requirement(active_from=date.today() + timedelta(days=30))
    html = admin_client.get("/reports/staffing/").content.decode()
    assert 'id="personal"' not in html


def test_the_dashboard_counts_the_overdue():
    from rota.admin_dashboard import health
    _setup()
    lines = {h["label"]: h for h in health()}
    line = lines["Clinicians overdue a personal requirement"]
    assert line["count"] == 1 and line["url"].endswith("/reports/staffing/#personal")
```

In `tests/test_admin_dashboard.py::test_health_lines_count_and_link`, add at the end:

```python
    assert lines["Clinicians overdue a personal requirement"]["count"] == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_personal_report.py tests/test_admin_dashboard.py -q`
Expected: the report tests fail on the missing section; the dashboard tests fail with `KeyError`.

- [ ] **Step 3: The view**

In `rota/views/reports.py`, add `from rota.services import personal as personal_svc` to the imports, and in `report_staffing` add `"personal_rows": _personal_rows(today, include_drafts=include_drafts)` to the render context. After `_accrual_targets`:

```python
_RANK = {"overdue": 0, "due": 1, "on track": 2}


def _personal_rows(today, include_drafts=True):
    """One row per (live requirement, clinician): last done, due, status.
    Overdue first, then due this week, then on track, then by name."""
    rows = []
    for req in personal_svc.live_requirements(today):
        people = list(req.clinicians.all())
        last = personal_svc.last_done(req, [c.id for c in people],
                                      today + timedelta(days=1),
                                      include_drafts=include_drafts)
        for c in people:
            s = personal_svc.status_from(req, last[c.id], today)
            rank = ("overdue" if s.weeks_overdue else
                    "due" if s.label == "due this week" else "on track")
            rows.append({
                "requirement": f"{req.session_type.name}, every {req.interval_weeks} weeks",
                "clinician": c, "last": s.last, "due": s.due,
                "label": s.label, "overdue": s.weeks_overdue > 0,
                "rank": _RANK[rank],
            })
    rows.sort(key=lambda r: (r["rank"], r["clinician"].name))
    return rows
```

- [ ] **Step 4: The template and the Health line**

In `templates/rota/report_staffing.html`, after the `{% if accrual_rows %} … {% endif %}` block and before the closing `</div>` of `.stack`:

```django
  {% if personal_rows %}
  <h2 id="personal">Personal requirements</h2>
  <div class="table-scroll">
    <table class="table">
      <thead>
        <tr>
          <th scope="col">Requirement</th>
          <th scope="col">Clinician</th>
          <th scope="col">Last done</th>
          <th scope="col">Due</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
      {% for r in personal_rows %}
      <tr>
        <td>{{ r.requirement }}</td>
        <td>{{ r.clinician.name }}</td>
        <td>{% if r.last %}{{ r.last|date:"D j M" }}{% else %}never{% endif %}</td>
        <td>week of {{ r.due|date:"j M" }}</td>
        <td{% if r.overdue %} class="warn"{% endif %}>{{ r.label }}</td>
      </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
```

In `rota/admin_dashboard.py`, add `from rota.services import personal as personal_svc` to the imports and, in `health()`'s returned list, after the "Days with staffing gaps this week" entry:

```python
        {"label": "Clinicians overdue a personal requirement",
         "count": personal_svc.overdue_count(today, include_drafts=True),
         "url": reverse("report-staffing") + "#personal", "level": "warn"},
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_personal_report.py tests/test_admin_dashboard.py tests/test_reports.py tests/test_reports_v2.py -q && ruff check .`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add rota/views/reports.py templates/rota/report_staffing.html rota/admin_dashboard.py tests/test_personal_report.py tests/test_admin_dashboard.py
git commit -m "feat: personal requirements on the staffing report and the dashboard's Health card

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/admin/coverage-rules.md` (a section after "## Coverage rules", before "## Trainee stage rules"), `docs/admin/day-to-day.md` (the pass list and the reasons table), `README.md` (spec list), `docs/backlog.md` (a Settled entry)

- [ ] **Step 1: coverage-rules.md**

Insert before `## Trainee stage rules`:

```markdown
## Personal requirements

`/admin/rota/personalrequirement/` — *each of these named clinicians does
this session type once every N weeks*. The example is a nursing home ward
round: a handful of GPs each owe one every six weeks, on no fixed day, as
an aim to fit in rather than a fixture.

It is not a coverage rule, which counts practice-wide (one keen GP could
satisfy six people's rounds), and not a recurring commitment, which pins
a weekday and silently drops a missed occurrence.

### Session type / Clinicians

What is owed, and who owes it. Each named clinician must be eligible for
the session type — the form refuses anyone who is not, by name. Only
active clinicians are offered.

### Every N weeks

**The clock is rolling.** A clinician is due N weeks after their most
recent session of the type, however it got there — assisted fill, placed
by hand, or imported. A clinician with none yet is due from **Active
from**. Once due they stay due until one is placed, and a slip restarts
the clock from when it actually happened, so the aim is "never more than
N weeks apart", not a fixed calendar cadence.

A worked example: six GPs, every six weeks. Dr A did one on 4 August, so
is due in the week of 15 September. The fill runs on 7 September for four
weeks and places Dr A's next round in that week, in the session where the
most other people are free. Dr B's slipped a fortnight — nobody was free —
so the fill reports "no free session" for that week and tries again the
next; when it lands on 29 September, Dr B's next is due six weeks after
that, not after the date it was originally due.

### Part / Weekdays

Which half-day it may take (AM, PM or either) and which days it may fall
on. Blank weekdays means every open day.

### Active from / until

Nothing is due or placed outside the window.

### Where it shows

The **Staffing report** lists every clinician on every live requirement:
last done, the week it is due, and on track / due this week / overdue by
n weeks, overdue first. The dashboard's **Health** card counts the
overdue. The fill screen's unfilled list says "no free session" for a
week where a due clinician could not be placed. Nothing appears in the
grid's day headers: a rolling aim has no per-day shortfall.
```

- [ ] **Step 2: day-to-day.md**

Change "**Then it runs six passes in order:**" to seven and insert after item 3:

```markdown
4. **Personal requirements** — one session for each clinician who is due
   (see [Personal requirements](coverage-rules.md#personal-requirements))
```

renumbering Mentoring, Trainee SDL and Default fill to 5, 6, 7. In the reasons table, change the "no free session" row's second column to: "The trainee had no free session left for SDL, or a clinician due a personal requirement had no free session that week — earlier passes took them all. Tried again the next week for a personal requirement."

- [ ] **Step 3: README and backlog**

`README.md`: after "clinician order and the OFF chip" add "; and personal requirements — one session per named clinician every N weeks, on no fixed day".

`docs/backlog.md`, under "## Settled", at the top:

```markdown
- **Personal requirements** (2026-09-19; spec
  `docs/superpowers/specs/2026-09-15-personal-requirements-design.md`).
  A new rule kind: each named clinician does a session type once every N
  weeks, on no fixed day. `PersonalRequirement` (migration 0031), admin
  under Sessions & rules with eligibility checked on the form, one clock
  in `rota/services/personal.py` (rolling from the last one done; due
  from active_from until then), a fill pass after coverage rules that
  places one session per due clinician per week in the cheapest free
  candidate and reports "no free session" otherwise, a table on the
  staffing report and a count on the Health card. Not done on purpose:
  full-day requirements, preferred weekdays, a site override, membership
  by group, placing early, a grid marker.
```

- [ ] **Step 4: Commit and open the PR**

```bash
git add docs/admin/coverage-rules.md docs/admin/day-to-day.md README.md docs/backlog.md
git commit -m "docs: personal requirements

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push -u origin feature/personal-requirements
gh pr create --base master --title "Personal requirements" --body "$(cat <<'BODY'
Spec: `docs/superpowers/specs/2026-09-15-personal-requirements-design.md`. Plan: `docs/superpowers/plans/2026-09-19-personal-requirements.md`.

A new rule kind: **each of these named clinicians does this session type once every N weeks**, on no fixed day — the nursing home ward round.

- **Model** `PersonalRequirement` (migration 0031): session type, named clinicians, interval, half-day, weekdays, active window. Admin under Sessions & rules; the form refuses a clinician not eligible for the type.
- **The clock** (`rota/services/personal.py`): due is rolling — N weeks after the clinician's most recent session of the type, however it got there; due from active_from until then; due stays due.
- **Fill pass** after coverage rules: one session per due clinician per week in the cheapest free candidate (SDL's scoring); "no free session" otherwise, tried again next week. No N+1: one last-done query per requirement.
- **Visibility**: a table on the staffing report (last done, due, on track / due this week / overdue), and a Health-card count of the overdue.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

CI runs the full suite on the PR; it must be green before merge, and the ruleset merges by rebase.
