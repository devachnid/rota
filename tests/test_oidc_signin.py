import pytest
from django.contrib.auth import get_user_model

from accounts.oidc import PracticeAccountBackend

User = get_user_model()


@pytest.fixture
def oidc_on(settings):
    settings.PRACTICE_HR_URL = "https://hr.example"
    settings.OIDC_RP_CLIENT_ID = "abc"


def test_login_page_offers_practice_account_when_configured(client, oidc_on):
    body = client.get("/accounts/login/").content.decode()
    assert "Sign in with the practice account" in body
    assert "/oidc/authenticate/" in body


def test_login_page_silent_when_not_configured(client, settings):
    settings.PRACTICE_HR_URL = ""
    assert "practice account" not in client.get("/accounts/login/").content.decode()


def test_existing_user_matched_by_case_insensitive_email(db):
    u = User.objects.create_user(email="Tom@Example.org", password="pw")
    found = PracticeAccountBackend().filter_users_by_claims({"email": "tom@example.org"})
    assert list(found) == [u]


def test_new_user_created_without_password_and_not_admin(db):
    b = PracticeAccountBackend()
    u = b.create_user({"email": "new@example.org", "employee_id": 7})
    assert not u.has_usable_password() and not u.is_rota_admin and u.is_active


def test_no_email_claim_matches_nobody(db):
    assert list(PracticeAccountBackend().filter_users_by_claims({})) == []
