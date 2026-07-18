import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


def test_login_page_renders(client, db):
    resp = client.get("/accounts/login/")
    assert resp.status_code == 200
    assert b"Log in" in resp.content


def test_email_login(client, gp_user):
    assert client.login(username="gp@example.com", password="pw")


def test_superuser_gets_rota_admin_flag(db):
    u = User.objects.create_superuser(email="boss@example.com", password="pw")
    assert u.is_rota_admin and u.is_staff and u.is_superuser
