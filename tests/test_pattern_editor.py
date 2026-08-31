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
    # Count the field, not the <form> tags: Django admin's own base template
    # renders a logout form, so the page never has exactly one. effective_from
    # appeared TWICE — the visible date input in the GET form and a hidden copy
    # in the POST form — and their drifting apart was the entire bug.
    assert html.count('name="effective_from"') == 1, (
        "effective_from appears more than once, so a visible date input and a "
        "hidden copy can disagree again"
    )
    assert 'method="get"' not in html, (
        "the editor should be one POST form; a second GET form is what let the "
        "date and the checkboxes drift apart"
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
