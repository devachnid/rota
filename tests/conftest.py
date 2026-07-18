import pytest
from django.contrib.auth import get_user_model

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
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def gp_client(client, gp_user):
    client.force_login(gp_user)
    return client
