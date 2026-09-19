"""An email address is the login name, and nobody types one the same way
twice: a phone capitalises it, an admin invites "Tom.Hodges@…", the owner
signs in as "tom.hodges@…". Every place the app matches an address to an
account must do so without regard to case, and two accounts can never
differ by case alone."""

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError
from django.test import Client, override_settings

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_login_ignores_the_case_of_the_address(client):
    User.objects.create_user(email="Tom.Hodges@Example.org", password="pw")
    assert client.login(username="tom.hodges@example.org", password="pw")
    assert client.login(username="TOM.HODGES@EXAMPLE.ORG", password="pw")


def test_get_by_natural_key_is_case_insensitive():
    user = User.objects.create_user(email="gp@example.com", password="pw")
    assert User.objects.get_by_natural_key("GP@Example.COM") == user


def test_the_wrong_password_still_fails():
    User.objects.create_user(email="gp@example.com", password="pw")
    assert authenticate(username="GP@example.com", password="nope") is None


def test_two_accounts_cannot_differ_by_case_alone():
    User.objects.create_user(email="gp@example.com", password="pw")
    with pytest.raises(IntegrityError):
        User.objects.create_user(email="GP@example.com", password="pw")


def test_the_invite_form_refuses_a_case_variant_of_an_existing_address(staff_client):
    """The admin's add form validates against the constraint, so the answer
    is a form error naming the field, not a 500."""
    User.objects.create_user(email="gp@example.com", password="pw")
    resp = staff_client.post("/admin/accounts/user/add/",
                             {"email": "GP@example.com", "is_rota_admin": ""})
    assert resp.status_code == 200
    assert User.objects.count() == 2  # staff + gp: nothing was added
    assert "already exists" in resp.content.decode().lower()


def test_a_saved_address_keeps_its_local_part_but_not_a_shouted_domain():
    """Django's own normalisation: the domain is lower-cased (it is never
    case-sensitive), the local part is kept as given."""
    user = User(email="Tom.Hodges@EXAMPLE.ORG")
    user.set_password("pw")
    user.save()
    user.refresh_from_db()
    assert user.email == "Tom.Hodges@example.org"


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_lockout_attempts_share_one_counter_across_case_variants():
    """A spray of "Tom@", "tom@", "TOM@" is one account under attack, and
    axes must count it as one — or the limit is five times the number of
    spellings."""
    from axes.models import AccessAttempt
    User.objects.create_user(email="gp@example.com", password="pw")
    for spelling in ("gp@example.com", "GP@example.com", "Gp@Example.com"):
        Client().post("/accounts/login/", {"username": spelling, "password": "wrong"},
                      REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.9")
    rows = list(AccessAttempt.objects.values_list("username", "failures_since_start"))
    assert rows == [("gp@example.com", 3)]


def test_the_migration_names_any_pair_it_refuses_to_constrain():
    """The constraint cannot be added over two accounts that differ only by
    case; the migration says which, rather than a bare UNIQUE failure."""
    from importlib import import_module
    guard = import_module("accounts.migrations.0006_user_email_case_insensitive").refuse_case_collisions

    class Users:
        def __init__(self, emails): self._emails = emails
        def values_list(self, *a, **k): return list(self._emails)

    class Apps:
        def __init__(self, emails): self.model = type("U", (), {"objects": Users(emails)})
        def get_model(self, app, name): return self.model

    guard(Apps(["a@x.org", "b@x.org"]), None)  # distinct: fine
    with pytest.raises(RuntimeError) as err:
        guard(Apps(["Tom@x.org", "tom@x.org", "c@x.org"]), None)
    assert "Tom@x.org, tom@x.org" in str(err.value)
