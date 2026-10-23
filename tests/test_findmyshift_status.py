"""The FindMyShift sync status page, Refresh now, and the unlinked warning."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from rota.models import PracticeSettings, TimeOff, TimeOffMapping, TimeOffSyncRun
from tests.factories import make_clinician, make_group, make_session_type

pytestmark = pytest.mark.django_db

STATUS = "/admin/rota/timeoffsyncrun/status/"
REFRESH = "/admin/rota/timeoffsyncrun/refresh/"


def _run(ok=True, minutes_ago=30, **kw):
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return TimeOffSyncRun.objects.create(started=started, finished=started, ok=ok, **kw)


def test_the_status_page_shows_the_last_good_run_and_unlinked_clinicians(staff_client):
    _run(n_teams=1, n_records=14, n_approved=11, n_deduped=10, n_unlinked=3)
    make_clinician("Nobody Linked")
    html = staff_client.get(STATUS).content.decode()
    assert "10 absences from 14 time-off records (11 approved) across 1 team" in html
    assert "Last successful sync" in html
    assert "Nobody Linked" in html


def test_the_status_pages_not_linked_list_excludes_locums(staff_client):
    """The dashboard's count of clinicians not linked to FindMyShift is of
    active non-locums (locums genuinely are treated as always available,
    link or not) — the status page's "Not linked" list must name the same
    set, not every active unlinked clinician."""
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Loose Locum", group=locum_group)
    make_clinician("Nobody Linked")
    html = staff_client.get(STATUS).content.decode()
    assert "Nobody Linked" in html
    assert "Loose Locum" not in html


def test_the_status_page_shows_the_last_error(staff_client):
    _run(ok=True, minutes_ago=60)
    _run(ok=False, minutes_ago=5, error="FindMyShift returned 429 for time-off/list")
    html = staff_client.get(STATUS).content.decode()
    assert "429" in html


def test_refresh_now_runs_a_sync(staff_client):
    with mock.patch("rota.admin.fms_client.from_settings", return_value=object()), \
         mock.patch("rota.admin.findmyshift_sync.run") as run:
        run.return_value = TimeOffSyncRun(started=timezone.now(), ok=True, n_deduped=4)
        resp = staff_client.post(REFRESH)
    assert resp.status_code == 302
    run.assert_called_once()


def test_refresh_now_refuses_within_sixty_seconds_of_a_run(staff_client):
    TimeOffSyncRun.objects.create(started=timezone.now() - timedelta(seconds=20), ok=True)
    with mock.patch("rota.admin.findmyshift_sync.run") as run:
        staff_client.post(REFRESH, follow=True)
    run.assert_not_called()


def test_refresh_now_is_post_only_and_admin_only(client, gp_client):
    """302 is what a *successful* refresh returns too, so the status code
    alone cannot tell "blocked" from "ran and redirected". The sync itself is
    what must not happen."""
    with mock.patch("rota.admin.findmyshift_sync.run") as run:
        assert gp_client.post(REFRESH).status_code in (302, 403)
        run.assert_not_called()
        assert client.post(REFRESH).status_code in (302, 403)
        run.assert_not_called()


def test_refresh_now_says_so_when_unconfigured(staff_client):
    with mock.patch("rota.admin.fms_client.from_settings", return_value=None):
        resp = staff_client.post(REFRESH, follow=True)
    assert "not configured" in resp.content.decode().lower()


def test_admins_see_an_unlinked_warning_on_the_grid(admin_client):
    PracticeSettings.load()
    make_clinician("A"); make_clinician("B", findmyshift_staff_id="S1")
    # A locum books their own sessions and has no time off to read: an
    # unlinked locum is not someone to link, so neither the count nor the
    # list it offers has them.
    locums = make_group("Locum GPs", is_locum_group=True, display_order=99)
    make_clinician("Laura Locum", group=locums)
    html = admin_client.get("/rota/").content.decode()
    assert "1 clinician not linked to FindMyShift" in html
    # The count is of active non-locum clinicians, so the list it offers must be too.
    assert ("?findmyshift=unlinked&amp;active__exact=1&amp;group__is_locum_group__exact=0"
            in html)


def test_a_practice_whose_only_unlinked_clinicians_are_locums_gets_no_warning(admin_client):
    PracticeSettings.load()
    make_clinician("A", findmyshift_staff_id="S1")
    locums = make_group("Locum GPs", is_locum_group=True, display_order=99)
    make_clinician("Laura Locum", group=locums)
    assert "not linked to FindMyShift" not in admin_client.get("/rota/").content.decode()


def test_gps_do_not_see_the_unlinked_warning(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Me", user=gp_user); make_clinician("Other")
    assert "not linked to FindMyShift" not in gp_client.get("/rota/").content.decode()


def test_no_warning_when_everyone_is_linked(admin_client):
    PracticeSettings.load()
    make_clinician("A", findmyshift_staff_id="S1")
    assert "not linked to FindMyShift" not in admin_client.get("/rota/").content.decode()


# --- the mapping ---


def test_deleting_the_default_mapping_row_is_refused(staff_client):
    """The row with a blank reason is the default, seeded by migration
    0034_findmyshift. Deleting it is one click from every absence with no
    row of its own rendering an empty cell."""
    row = TimeOffMapping.objects.get(reason="")
    resp = staff_client.post(f"/admin/rota/timeoffmapping/{row.pk}/delete/",
                             data={"post": "yes"}, follow=True)
    assert resp.status_code == 403 or TimeOffMapping.objects.filter(pk=row.pk).exists()


def test_deleting_a_reason_specific_mapping_row_succeeds(staff_client):
    st = make_session_type("Maternity", code="MAT", category="ABSENCE")
    row = TimeOffMapping.objects.create(reason="Maternity", session_type=st)
    staff_client.post(f"/admin/rota/timeoffmapping/{row.pk}/delete/",
                      data={"post": "yes"}, follow=True)
    assert not TimeOffMapping.objects.filter(pk=row.pk).exists()


def test_status_page_names_reasons_with_no_row_of_their_own(staff_client):
    """A reason with no exact row renders as the default chip — which may
    be the wrong chip — and with the default gone renders as nothing. The
    status page names the reason either way, so the row to add is
    findable, and says which of the two is happening."""
    clinician = make_clinician("Unmapped Absentee")
    TimeOff.objects.create(clinician=clinician, start_date="2026-01-05",
                           end_date="2026-01-05", reason="Jury service")
    TimeOff.objects.create(clinician=clinician, start_date="2026-02-05",
                           end_date="2026-02-05", reason="Holiday")

    html = staff_client.get(STATUS).content.decode()
    assert "1 reason with no mapping of its own" in html
    assert "<em>Jury service</em>" in html and "<em>Holiday</em>" not in html
    assert "rendering as the default chip" in html

    TimeOffMapping.objects.get(reason="").delete()
    html = staff_client.get(STATUS).content.decode()
    assert "rendering as empty cells" in html

    make_session_type("Jury", code="JURY", category="ABSENCE")
    TimeOffMapping.objects.create(reason="Jury service",
                                  session_type=make_session_type("Jury2", code="JUR2", category="ABSENCE"))
    html = staff_client.get(STATUS).content.decode()
    assert "no mapping" not in html


def test_the_status_page_lists_recent_runs_and_the_changelist_is_plain(staff_client):
    TimeOffSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True,
                                  n_teams=1, n_records=3, n_approved=3,
                                  n_deduped=3, n_unlinked=0)
    html = staff_client.get(STATUS).content.decode()
    assert "Refresh now" in html and "Recent runs" in html
    card = html[html.index("Recent runs"):]
    assert "No runs yet." not in card
    assert '<td class="py-2">3</td>' in card
    assert '<td class="py-2">0</td>' in card
    plain = staff_client.get("/admin/rota/timeoffsyncrun/").content.decode()
    assert "Last successful sync" not in plain


def test_the_sidebar_links_the_status_page(staff_client):
    html = staff_client.get("/admin/").content.decode()
    assert STATUS in html
    assert "Time off from FindMyShift" in html
