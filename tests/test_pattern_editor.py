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

import re
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
    # "date" alone would also match the page's own <input type="date">, on
    # every render, error or not -- assert on text only the error path emits.
    assert b"not a date" in r.content.lower()


@pytest.mark.django_db
def test_saving_with_a_blank_date_is_refused(staff_client, clinician):
    """The narrower door: today is the value that overwrites the live
    pattern, so falling back to it on an empty field is as destructive as
    parsing a typo into it."""
    r = staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": "", "d2_AM": "on",
    })
    assert PatternSlot.objects.filter(clinician=clinician).count() == 2
    assert b"required" in r.content.lower()


@pytest.mark.django_db
def test_saving_with_the_date_field_absent_entirely_is_refused(
    staff_client, clinician
):
    r = staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk, "d2_AM": "on",
    })
    assert PatternSlot.objects.filter(clinician=clinician).count() == 2


@pytest.mark.django_db
def test_a_stale_query_string_date_cannot_stand_in_for_a_blank_field(
    staff_client, clinician
):
    """The view's own post-save redirect leaves the admin on a URL carrying
    effective_from, and the form resubmits to it. A cleared date field must
    not silently fall back to whatever is still in the URL."""
    stale = (date.today() + timedelta(days=90)).isoformat()
    r = staff_client.post(
        f"{URL}?clinician_id={clinician.pk}&effective_from={stale}",
        {"action": "save", "clinician_id": clinician.pk,
         "effective_from": "", "d2_AM": "on"},
    )
    assert PatternSlot.objects.filter(clinician=clinician).count() == 2, (
        "a stale query-string date was used to write a pattern"
    )
    assert b"required" in r.content.lower()


@pytest.mark.django_db
def test_the_same_holds_when_the_field_is_absent_rather_than_blank(
    staff_client, clinician
):
    stale = (date.today() + timedelta(days=90)).isoformat()
    staff_client.post(
        f"{URL}?clinician_id={clinician.pk}&effective_from={stale}",
        {"action": "save", "clinician_id": clinician.pk, "d2_AM": "on"},
    )
    assert PatternSlot.objects.filter(clinician=clinician).count() == 2


@pytest.mark.django_db
def test_a_query_string_date_still_restores_context_on_a_load(
    staff_client, clinician
):
    """The GET fallback must survive for rendering — it is how the post-save
    redirect puts the admin back where they were."""
    when = (date.today() + timedelta(days=90)).isoformat()
    html = staff_client.get(
        URL, {"clinician_id": clinician.pk, "effective_from": when}
    ).content.decode()
    assert when in html


@pytest.mark.django_db
def test_the_page_shows_the_pattern_history(staff_client, clinician):
    """The editor showed one date's worth with no hint anything else existed,
    which is what made the damage invisible."""
    future = date.today() + timedelta(days=30)
    PatternSlot.objects.create(clinician=clinician, weekday=2, part="AM",
                               works=True, effective_from=future)
    html = staff_client.get(
        URL, {"clinician_id": clinician.pk}).content.decode()
    # Not the bare year: the visible effective_from input defaults to
    # today's date, whose year matches `future`'s regardless of whether the
    # history table rendered at all. Assert on the history rows' own
    # content instead -- the grouped "weekday part" summary for each date,
    # which only _pattern_history produces.
    assert "Mon AM, Mon PM" in html  # LONG_AGO: weekday 0, AM and PM
    assert "Wed AM" in html          # future: weekday 2, AM only


@pytest.mark.django_db
def test_loading_an_existing_date_shows_that_date_s_own_pattern(
    staff_client, clinician
):
    """The history table invites the admin to load a date that already has
    rows. It must show what that date sets, not what preceded it — otherwise
    the boxes render wrong and Save writes the wrong thing back."""
    future = date.today() + timedelta(days=30)
    PatternSlot.objects.create(clinician=clinician, weekday=2, part="AM",
                               works=True, effective_from=future)
    html = staff_client.post(URL, {
        "action": "load", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(),
    }).content.decode()
    assert 'name="d2_AM" checked' in html.replace('checked=""', "checked"), (
        "a row set at this very date rendered unticked"
    )


@pytest.mark.django_db
def test_round_tripping_an_existing_date_changes_nothing(staff_client, clinician):
    """Load a date, save it back untouched, and the rows must be identical."""
    future = date.today() + timedelta(days=30)
    PatternSlot.objects.create(clinician=clinician, weekday=2, part="AM",
                               works=True, effective_from=future)
    before = {(r.weekday, r.part, r.works)
              for r in PatternSlot.objects.filter(clinician=clinician)}
    staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(),
        "d0_AM": "on", "d0_PM": "on", "d2_AM": "on",
    })
    after = {(r.weekday, r.part, r.works)
             for r in PatternSlot.objects.filter(clinician=clinician)}
    assert after == before


@pytest.mark.django_db
def test_loading_a_fresh_date_still_shows_the_pattern_that_precedes_it(
    staff_client, clinician
):
    """The add-a-future-change flow must not regress."""
    future = date.today() + timedelta(days=60)
    html = staff_client.post(URL, {
        "action": "load", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(),
    }).content.decode().replace('checked=""', "checked")
    assert 'name="d0_AM" checked' in html


@pytest.mark.django_db
def test_the_post_save_redirect_lands_on_a_page_that_re_saves_identically(
    staff_client, clinician
):
    """The same hazard by its other route. Save a future change, follow the
    redirect the view itself issues, and press Save again on exactly what it
    renders: the second save must be a no-op. Before the fix the redirect
    landed on the day-before view, so the editor's own round trip reverted
    the change it had just written."""
    future = date.today() + timedelta(days=30)
    staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(),
        "d0_AM": "on", "d0_PM": "on", "d2_AM": "on",
    })
    after_first = {(r.weekday, r.part, r.works)
                   for r in PatternSlot.objects.filter(clinician=clinician)}
    assert (2, "AM", True) in after_first

    html = staff_client.get(
        URL, {"clinician_id": clinician.pk, "effective_from": future.isoformat()}
    ).content.decode().replace('checked=""', "checked")
    posted = {f"d{w}_{p}": "on"
              for w in range(7) for p in ("AM", "PM")
              if f'name="d{w}_{p}" checked' in html}
    staff_client.post(URL, {
        "action": "save", "clinician_id": clinician.pk,
        "effective_from": future.isoformat(), **posted,
    })
    assert {(r.weekday, r.part, r.works)
            for r in PatternSlot.objects.filter(clinician=clinician)} == after_first


@pytest.mark.django_db
def test_missing_preselects_the_first_clinician_without_a_pattern_and_lists_the_rest(staff_client):
    from tests.factories import make_clinician, make_group, make_pattern
    done = make_clinician("Done Already")
    make_pattern(done)
    a = make_clinician("Alan Empty")
    b = make_clinician("Beth Empty")
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Idle Locum", group=locums)   # locums are never "missing"
    html = staff_client.get(URL, {"missing": "1"}).content.decode()
    assert f'<option value="{a.pk}" selected' in html
    # The first "<form" in the document is unfold's sidebar logout form,
    # rendered before {% block content %} — slicing on it says nothing about
    # the page. Anchor on the missing-clinicians card itself instead.
    card = html[html.index("Clinicians without a pattern"):]
    card = card[:card.index("</ul>")]
    assert "Beth Empty" in card
    assert "Idle Locum" not in card
    assert "Done Already" not in card


@pytest.mark.django_db
def test_saving_with_missing_set_offers_the_next_clinician(staff_client):
    from tests.factories import make_clinician
    a = make_clinician("Alan Empty")
    make_clinician("Beth Empty")
    resp = staff_client.post(URL + "?missing=1", {
        "action": "save", "clinician_id": a.pk, "effective_from": "2026-01-05",
        "d0_AM": "on"}, follow=True)
    html = resp.content.decode()
    assert "Next: Beth Empty" in html
    assert "missing=1" in resp.redirect_chain[-1][0]


@pytest.mark.django_db
def test_the_editor_wears_the_admin_chrome(staff_client, clinician):
    html = staff_client.get(URL, {"clinician_id": clinician.pk}).content.decode()
    assert "Practice Rota" in html and "Pattern editor" in html
    # Load and Save must not look identical: Save is the primary action.
    load = re.search(r'<button[^>]*name="action" value="load"[^>]*class="([^"]*)"', html)
    save = re.search(r'<button[^>]*name="action" value="save"[^>]*class="([^"]*)"', html)
    assert load and save
    assert load.group(1) != save.group(1)
