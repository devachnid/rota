"""Who gets into the admin, and what the site is.

`is_rota_admin` is the one flag: a practice manager is a rota admin and
nothing else. Superusers are admitted regardless. Anyone else is turned
away at the door — to the app's own login if anonymous, with a 403 if
signed in as a GP.
"""

import pytest
from django.contrib import admin

from rota.admin_site import RotaAdminSite

pytestmark = pytest.mark.django_db


def test_the_admin_site_is_ours():
    assert isinstance(admin.site, RotaAdminSite)


def test_a_rota_admin_who_is_not_staff_reaches_the_admin(admin_client, admin_user):
    assert not admin_user.is_staff
    assert admin_client.get("/admin/").status_code == 200


def test_a_superuser_reaches_the_admin(staff_client):
    assert staff_client.get("/admin/").status_code == 200


def test_an_anonymous_visitor_lands_on_the_apps_login(client):
    resp = client.get("/admin/", follow=True)
    final_url = resp.redirect_chain[-1][0]
    assert final_url.startswith("/accounts/login/?next=")


def test_a_signed_in_gp_gets_403_not_a_login_loop(gp_client):
    resp = gp_client.get("/admin/", follow=True)
    assert resp.status_code == 403


def test_the_next_parameter_cannot_send_someone_off_site(client):
    resp = client.get("/admin/login/?next=https://evil.example/", follow=False)
    assert resp.status_code == 302
    assert "evil.example" not in resp["Location"]


def test_the_header_reads_practice_rota(admin_client):
    html = admin_client.get("/admin/").content.decode()
    assert "Practice Rota" in html


def test_logout_is_post_only_and_returns_to_the_app_login(admin_client):
    assert admin_client.get("/admin/logout/").status_code == 405
    resp = admin_client.post("/admin/logout/")
    assert resp.status_code == 302 and resp["Location"] == "/accounts/login/"


from datetime import date

from rota.models import ClosedDay


def test_a_rota_admin_can_open_and_change_rota_models(admin_client):
    assert admin_client.get("/admin/rota/clinician/").status_code == 200
    resp = admin_client.post("/admin/rota/closedday/add/",
                             {"day": "2026-12-25", "reason": "Christmas"})
    assert resp.status_code == 302
    assert ClosedDay.objects.filter(day=date(2026, 12, 25)).exists()


def test_a_rota_admin_can_open_login_accounts(admin_client):
    assert admin_client.get("/admin/accounts/user/").status_code == 200


@pytest.mark.parametrize("url", ["/admin/axes/accessattempt/", "/admin/auth/group/"])
def test_a_rota_admin_is_kept_out_of_system_tables(admin_client, staff_client, url):
    assert admin_client.get(url).status_code == 403
    assert staff_client.get(url).status_code == 200


def test_the_app_header_links_to_the_admin_for_rota_admins_only(admin_client, gp_client, gp_user):
    from rota.models import PracticeSettings
    from tests.factories import make_clinician
    PracticeSettings.load()
    make_clinician(user=gp_user)
    assert 'href="/admin/"' in admin_client.get("/rota/").content.decode()
    assert 'href="/admin/"' not in gp_client.get("/rota/").content.decode()


def test_the_login_page_response_is_never_cached(client):
    """RotaAdminSite.login overrides Django's login view, which loses the
    @never_cache and @login_not_required decorators unless we re-apply them."""
    resp = client.get("/admin/login/")
    assert resp.status_code == 302
    assert "no-cache" in resp["Cache-Control"]


def test_an_inactive_rota_admin_has_no_permission(rf):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.create_user(
        email="inactive-admin@example.com", password="pw",
        is_rota_admin=True, is_active=False,
    )
    request = rf.get("/admin/")
    request.user = user
    assert RotaAdminSite().has_permission(request) is False
