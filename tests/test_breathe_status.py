"""The Breathe sync status page, Refresh now, and the unlinked warning."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from rota.models import (BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun,
                         PracticeSettings)
from tests.factories import make_clinician, make_session_type

pytestmark = pytest.mark.django_db


def _run(ok=True, minutes_ago=30, **kw):
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return BreatheSyncRun.objects.create(started=started, finished=started, ok=ok, **kw)


def test_the_status_page_shows_the_last_good_run_and_unlinked_clinicians(staff_client):
    _run(n_deduped=12, n_unlinked=3)
    make_clinician("Nobody Linked")
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "12" in html and "Last successful sync" in html
    assert "Nobody Linked" in html


def test_the_status_page_shows_the_last_error(staff_client):
    _run(ok=True, minutes_ago=60)
    _run(ok=False, minutes_ago=5, error="Breathe returned 429 for /absences")
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "429" in html


def test_refresh_now_runs_a_sync(staff_client):
    with mock.patch("rota.admin.breathe_client.from_settings", return_value=object()), \
         mock.patch("rota.admin.breathe_sync.run") as run:
        run.return_value = BreatheSyncRun(started=timezone.now(), ok=True, n_deduped=4)
        resp = staff_client.post("/admin/rota/breathesyncrun/refresh/")
    assert resp.status_code == 302
    run.assert_called_once()


def test_refresh_now_refuses_within_sixty_seconds_of_a_run(staff_client):
    BreatheSyncRun.objects.create(started=timezone.now() - timedelta(seconds=20), ok=True)
    with mock.patch("rota.admin.breathe_sync.run") as run:
        staff_client.post("/admin/rota/breathesyncrun/refresh/", follow=True)
    run.assert_not_called()


def test_refresh_now_is_post_only_and_admin_only(client, gp_client):
    """302 is what a *successful* refresh returns too, so the status code
    alone cannot tell "blocked" from "ran and redirected". The sync itself is
    what must not happen."""
    with mock.patch("rota.admin.breathe_sync.run") as run:
        assert gp_client.post("/admin/rota/breathesyncrun/refresh/").status_code in (302, 403)
        run.assert_not_called()
        assert client.post("/admin/rota/breathesyncrun/refresh/").status_code in (302, 403)
        run.assert_not_called()


def test_refresh_now_says_so_when_unconfigured(staff_client):
    with mock.patch("rota.admin.breathe_client.from_settings", return_value=None):
        resp = staff_client.post("/admin/rota/breathesyncrun/refresh/", follow=True)
    assert "not configured" in resp.content.decode().lower()


def test_admins_see_an_unlinked_warning_on_the_grid(admin_client):
    PracticeSettings.load()
    make_clinician("A"); make_clinician("B", breathe_employee_id=1)
    html = admin_client.get("/rota/").content.decode()
    assert "1 clinician not linked to Breathe" in html
    # The count is of active clinicians, so the list it offers must be too.
    assert "?breathe=unlinked&amp;active__exact=1" in html


def test_gps_do_not_see_the_unlinked_warning(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Me", user=gp_user); make_clinician("Other")
    assert "not linked to Breathe" not in gp_client.get("/rota/").content.decode()


def test_no_warning_when_everyone_is_linked(admin_client):
    PracticeSettings.load()
    make_clinician("A", breathe_employee_id=1)
    assert "not linked to Breathe" not in admin_client.get("/rota/").content.decode()


# --- Carried rulings from Task 5 ---


def test_deleting_a_default_mapping_row_is_refused(staff_client):
    """A row with reason == '' is a kind's default, seeded by migration
    0022_breathe. Deleting it is one click from every absence of that kind
    rendering an empty cell."""
    row = BreatheLeaveMapping.objects.get(kind="holiday", reason="")
    resp = staff_client.post(f"/admin/rota/breatheleavemapping/{row.pk}/delete/",
                             data={"post": "yes"}, follow=True)
    assert resp.status_code == 403 or BreatheLeaveMapping.objects.filter(pk=row.pk).exists()


def test_deleting_a_reason_specific_mapping_row_succeeds(staff_client):
    st = make_session_type("Maternity", code="MAT", category="ABSENCE")
    row = BreatheLeaveMapping.objects.create(kind="other", reason="Maternity", session_type=st)
    staff_client.post(f"/admin/rota/breatheleavemapping/{row.pk}/delete/",
                      data={"post": "yes"}, follow=True)
    assert not BreatheLeaveMapping.objects.filter(pk=row.pk).exists()


def test_status_page_shows_unmapped_absence_count(staff_client):
    """An absence whose (kind, reason) has no row, and whose (kind, '')
    default also has no row, renders no chip. The status page must surface
    it as findable, not silent."""
    default = BreatheLeaveMapping.objects.get(kind="other", reason="")
    default_session_type = default.session_type
    clinician = make_clinician("Unmapped Absentee")
    BreatheAbsence.objects.create(
        clinician=clinician, start_date="2026-01-05", end_date="2026-01-05",
        kind="other", reason="X")

    default.delete()
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "1 absence" in html and "no mapping" in html

    BreatheLeaveMapping.objects.create(kind="other", reason="", session_type=default_session_type)
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "no mapping" not in html


def test_the_status_page_lists_recent_runs_and_the_changelist_is_plain(staff_client):
    from django.utils import timezone
    from rota.models import BreatheSyncRun
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True,
                                  n_requests=1, n_absences=2, n_sicknesses=0,
                                  n_deduped=3, n_unlinked=0)
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "Refresh now" in html and "Recent runs" in html
    plain = staff_client.get("/admin/rota/breathesyncrun/").content.decode()
    assert "Last successful sync" not in plain


def test_the_sidebar_links_the_status_page(staff_client):
    html = staff_client.get("/admin/").content.decode()
    assert "/admin/rota/breathesyncrun/status/" in html
