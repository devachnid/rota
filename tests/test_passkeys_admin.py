"""A rota admin revokes a lost phone from the login-account page. The
inline shows and deletes, never adds, and follows the account page's own
guards."""

import json

import pytest

from accounts.models import Passkey
from tests.soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db


def _enrol(client, name):
    options = client.post("/accounts/passkeys/register/options/",
                          data="{}", content_type="application/json").json()
    payload = {"credential": SoftAuthenticator().create(options), "name": name}
    assert client.post("/accounts/passkeys/register/", data=json.dumps(payload),
                       content_type="application/json").status_code == 200


def _change(user):
    return f"/admin/accounts/user/{user.pk}/change/"


def _revoke(client, user, passkey):
    return client.post(_change(user), {
        "email": user.email, "is_rota_admin": "", "is_active": "on",
        "passkeys-TOTAL_FORMS": "1", "passkeys-INITIAL_FORMS": "1",
        "passkeys-MIN_NUM_FORMS": "0", "passkeys-MAX_NUM_FORMS": "1000",
        "passkeys-0-id": str(passkey.pk), "passkeys-0-user": str(user.pk),
        "passkeys-0-DELETE": "on",
    })


def test_the_change_page_lists_passkeys_read_only_with_a_delete_box(admin_client, gp_client, gp_user):
    _enrol(gp_client, "lost phone")
    html = admin_client.get(_change(gp_user)).content.decode()
    assert "lost phone" in html and 'name="passkeys-TOTAL_FORMS"' in html
    assert 'name="passkeys-0-DELETE"' in html
    assert 'name="passkeys-0-name"' not in html          # read-only: no editable field
    assert 'name="passkeys-1-name"' not in html          # and no blank row to add one


def test_a_rota_admin_revokes_a_passkey(admin_client, gp_client, gp_user):
    _enrol(gp_client, "lost phone")
    passkey = Passkey.objects.get()
    assert _revoke(admin_client, gp_user, passkey).status_code == 302
    assert not Passkey.objects.exists()


def test_a_rota_admin_cannot_touch_a_superusers_passkeys(admin_client, staff_client, staff_user):
    _enrol(staff_client, "root phone")
    passkey = Passkey.objects.get()
    assert _revoke(admin_client, staff_user, passkey).status_code == 403
    assert Passkey.objects.filter(pk=passkey.pk).exists()


def test_the_add_page_has_no_passkey_inline(admin_client):
    assert "passkeys-TOTAL_FORMS" not in admin_client.get("/admin/accounts/user/add/").content.decode()
