import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@example.com", password="pw", is_rota_admin=True
    )


@pytest.fixture
def gp_user(db):
    return User.objects.create_user(email="gp@example.com", password="pw")


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def gp_client(gp_user):
    client = Client()
    client.force_login(gp_user)
    return client
