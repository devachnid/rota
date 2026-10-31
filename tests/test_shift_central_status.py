"""The Shift Central sync status page, Refresh now, and the no-email warning."""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from rota.models import PracticeSettings, TimeOff, TimeOffMapping, TimeOffSyncRun
from tests.factories import make_clinician, make_group, make_session_type

pytestmark = pytest.mark.django_db
STATUS = "/admin/rota/timeoffsyncrun/status/"
REFRESH = "/admin/rota/timeoffsyncrun/refresh/"
User = get_user_model()


def _run(ok=True, minutes_ago=30, **kw):
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return TimeOffSyncRun.objects.create(started=started, finished=started, ok=ok, **kw)


def test_the_status_page_shows_the_last_good_run_unmatched_emails_and_clinicians_without_email(staff_client):
    _run(n_records=14, n_matched=10, n_unmatched=2, n_outside=1, detail={"unmatched": ["x@example.org", "y@example.org"]})
    make_clinician("Nobody Linked")
    html = staff_client.get(STATUS).content.decode()
    assert "14 records" in html and "10 clinicians matched" in html and "x@example.org" in html and "Nobody Linked" in html
    assert "2 emails unmatched" in html and "1 outside the window" in html
    assert "FindMyShift" not in html


def test_locums_are_not_listed_as_missing_an_email(staff_client):
    make_clinician("Loose Locum", group=make_group("Locum", is_locum_group=True, display_order=99))
    make_clinician("Nobody Linked")
    html = staff_client.get(STATUS).content.decode()
    assert "Nobody Linked" in html and "Loose Locum" not in html


def test_a_clinician_with_a_login_email_is_not_listed_as_missing_one(staff_client):
    make_clinician("Has Email", user=User.objects.create_user(email="has@example.org", password="pw"))
    make_clinician("Blank Email", user=User.objects.create_user(email="", password="pw"))
    html = staff_client.get(STATUS).content.decode()
    assert "Blank Email" in html and "Has Email" not in html


def test_the_status_page_shows_the_last_error(staff_client):
    _run(ok=True, minutes_ago=60)
    _run(ok=False, minutes_ago=5, error="Shift Central returned 429 for leave")
    html = staff_client.get(STATUS).content.decode()
    assert "Most recent run failed" in html and "429" in html


def test_the_status_page_says_what_to_set_when_unconfigured(staff_client):
    html = staff_client.get(STATUS).content.decode()
    assert "Shift Central is not configured" in html
    assert "SHIFT_CENTRAL_URL" in html and "SHIFT_CENTRAL_TOKEN" in html


def test_refresh_now_runs_a_sync_when_configured(staff_client, settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "t"
    with mock.patch("rota.services.shift_central.sync.run") as run:
        run.return_value = TimeOffSyncRun(ok=True, n_records=1, n_matched=1, n_unmatched=0, n_outside=0, started=timezone.now())
        r = staff_client.post(REFRESH)
    assert r.status_code == 302 and run.called


def test_refresh_now_reports_the_counts(staff_client, settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "t"
    with mock.patch("rota.services.shift_central.sync.run") as run:
        run.return_value = TimeOffSyncRun(ok=True, n_records=5, n_matched=3, n_unmatched=2, n_outside=0, started=timezone.now())
        html = staff_client.post(REFRESH, follow=True).content.decode()
    assert "Synced: 3 clinicians matched, 2 emails unmatched." in html


def test_refresh_now_refuses_within_sixty_seconds_of_a_run(staff_client, settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "t"
    TimeOffSyncRun.objects.create(started=timezone.now() - timedelta(seconds=20), ok=True)
    with mock.patch("rota.services.shift_central.sync.run") as run:
        staff_client.post(REFRESH, follow=True)
    run.assert_not_called()


def test_refresh_now_is_post_only_and_admin_only(client, gp_client, settings):
    """302 is what a successful refresh returns too, so the status code alone
    cannot tell "blocked" from "ran and redirected". The sync itself is what
    must not happen."""
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "t"
    with mock.patch("rota.services.shift_central.sync.run") as run:
        assert gp_client.post(REFRESH).status_code in (302, 403)
        run.assert_not_called()
        assert client.post(REFRESH).status_code in (302, 403)
        run.assert_not_called()


def test_refresh_now_says_so_when_unconfigured(staff_client):
    r = staff_client.post(REFRESH, follow=True)
    assert "not configured" in r.content.decode()


def test_the_grid_warns_admins_about_clinicians_without_an_email(admin_client):
    make_clinician("Nobody Linked")
    html = admin_client.get("/rota/").content.decode()
    assert "without a login email" in html and "FindMyShift" not in html


def test_the_warning_counts_only_active_non_locums_without_an_email(admin_client):
    PracticeSettings.load()
    make_clinician("A")
    make_clinician("B", user=User.objects.create_user(email="b@example.org", password="pw"))
    make_clinician("Laura Locum", group=make_group("Locum GPs", is_locum_group=True, display_order=99))
    html = admin_client.get("/rota/").content.decode()
    assert "1 clinician without a login email" in html
    assert "?active__exact=1&amp;group__is_locum_group__exact=0&amp;user__isnull=True" in html


def test_a_practice_whose_only_clinicians_without_email_are_locums_gets_no_warning(admin_client):
    PracticeSettings.load()
    make_clinician("A", user=User.objects.create_user(email="a@example.org", password="pw"))
    make_clinician("Laura Locum", group=make_group("Locum GPs", is_locum_group=True, display_order=99))
    assert "without a login email" not in admin_client.get("/rota/").content.decode()


def test_gps_do_not_see_the_no_email_warning(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Me", user=gp_user)
    make_clinician("Other")
    assert "without a login email" not in gp_client.get("/rota/").content.decode()


def test_the_link_the_warning_offers_opens_the_clinician_list(admin_client):
    from rota.services.shift_central.links import without_email_changelist_url
    make_clinician("Nobody Linked")
    resp = admin_client.get(without_email_changelist_url())
    assert resp.status_code == 200 and "Nobody Linked" in resp.content.decode()


# --- the mapping ---


def test_deleting_the_default_mapping_row_is_refused(staff_client):
    """The row with a blank reason is the default, seeded by the
    time off migrations. Deleting it is one click from every absence with no
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
                                  n_records=3, n_matched=2, n_unmatched=1, n_outside=0)
    html = staff_client.get(STATUS).content.decode()
    assert "Refresh now" in html and "Recent runs" in html
    card = html[html.index("Recent runs"):]
    assert "No runs yet." not in card
    for heading in ("Started", "OK", "Matched", "Unmatched", "Error"):
        assert f">{heading}<" in card
    assert '<td class="py-2">2</td>' in card
    assert '<td class="py-2">1</td>' in card
    plain = staff_client.get("/admin/rota/timeoffsyncrun/").content.decode()
    assert "Last successful sync" not in plain


def test_the_sidebar_links_the_status_page_under_shift_central(staff_client):
    html = staff_client.get("/admin/").content.decode()
    assert "Time off from Shift Central" in html and STATUS in html
