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
