"""Who gets into the admin, and what the site is.

`is_rota_admin` is the one flag: a practice manager is a rota admin and
nothing else. Superusers are admitted regardless. Anyone else is turned
away at the door — to the app's own login if anonymous, with a 403 if
signed in as a GP.
"""

import re

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
    html = admin_client.get("/rota/").content.decode()
    assert html.count('class="nav-link">Admin</a>') == 1 and html.count('class="tabbar-link">Admin</a>') == 1
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


def test_a_malformed_perm_string_is_never_granted(admin_user):
    assert not admin_user.has_perm("rota")


def test_a_rota_admin_cannot_make_anyone_a_superuser(admin_client, gp_user):
    url = f"/admin/accounts/user/{gp_user.pk}/change/"
    resp = admin_client.post(url, {
        "email": gp_user.email,
        "is_superuser": "on",
        "is_staff": "on",
        "is_rota_admin": "on",
        "is_active": "on",
    })
    assert resp.status_code in (200, 302), resp.content.decode()
    gp_user.refresh_from_db()
    assert not gp_user.is_superuser and not gp_user.is_staff
    assert 'name="is_superuser"' not in admin_client.get(url).content.decode()


def test_a_rota_admin_cannot_touch_a_superusers_account(admin_client, staff_user):
    assert admin_client.get(f"/admin/accounts/user/{staff_user.pk}/change/").status_code == 403
    assert admin_client.get(f"/admin/accounts/user/{staff_user.pk}/delete/").status_code == 403
    assert admin_client.get(f"/admin/accounts/user/{staff_user.pk}/password/").status_code == 403


def test_a_superuser_still_sees_the_permissions_fieldset(staff_client, gp_user):
    html = staff_client.get(f"/admin/accounts/user/{gp_user.pk}/change/").content.decode()
    assert 'name="is_superuser"' in html


def test_a_rota_admin_can_create_a_login_account(admin_client):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    get_resp = admin_client.get("/admin/accounts/user/add/")
    html = get_resp.content.decode()
    assert get_resp.status_code == 200
    assert 'name="password1"' in html
    assert 'name="is_superuser"' not in html

    resp = admin_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com",
        "password1": "correct-horse-battery",
        "password2": "correct-horse-battery",
        "usable_password": "true",
        "is_rota_admin": "on",
    })
    assert resp.status_code == 302, resp.content.decode()
    user = User.objects.get(email="new@example.com")
    assert user.is_rota_admin is True
    assert user.is_superuser is False


def test_a_superuser_can_create_a_login_account(staff_client):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    resp = staff_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com",
        "password1": "correct-horse-battery",
        "password2": "correct-horse-battery",
        "usable_password": "true",
        "is_rota_admin": "on",
    })
    assert resp.status_code == 302, resp.content.decode()
    assert User.objects.filter(email="new@example.com").exists()


def test_a_rota_admin_can_deactivate_a_login_but_not_promote_it(admin_client, gp_user):
    url = f"/admin/accounts/user/{gp_user.pk}/change/"
    html = admin_client.get(url).content.decode()
    assert 'name="is_active"' in html
    assert 'name="is_superuser"' not in html

    resp = admin_client.post(url, {
        "email": gp_user.email,
        "is_active": "",
        "is_rota_admin": "on" if gp_user.is_rota_admin else "",
    })
    assert resp.status_code == 302, resp.content.decode()
    gp_user.refresh_from_db()
    assert gp_user.is_active is False
    assert gp_user.is_superuser is False


GROUPS = ["People", "Working patterns", "Calendar", "Sessions & rules",
          "Leave from Breathe", "Practice settings", "Records"]


SYSTEM_HEADING = re.compile(r"<h2[^>]*>\s*System\s*<")


def test_a_rota_admin_sees_the_eight_groups_and_not_system(admin_client):
    from django.utils.html import escape
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    for group in GROUPS:
        # Django auto-escapes the rendered title, so "Sessions & rules"
        # comes back as "Sessions &amp; rules" — check for what the
        # template actually emits, not the raw group name.
        assert escape(group) in html, group
    assert "Login accounts" in html and "Audit log" in html
    # A bare "System" also names unfold's light/dark/system theme option,
    # present on every page regardless of permission — so check for the
    # sidebar group's own heading, not just the substring.
    assert not SYSTEM_HEADING.search(html) and "Access attempts" not in html


def test_a_superuser_sees_system_too(staff_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = staff_client.get("/admin/").content.decode()
    assert "System" in html and "Access attempts" in html and "Auth groups" in html


def test_every_sidebar_link_resolves(staff_client, rf, staff_user):
    from rota.admin_site import navigation
    from rota.models import PracticeSettings
    PracticeSettings.load()
    request = rf.get("/admin/")
    request.user = staff_user
    for group in navigation(request):
        for item in group["items"]:
            link = item["link"]
            url = link(request) if callable(link) else str(link)
            assert staff_client.get(url).status_code == 200, (group["title"], item["title"], url)
