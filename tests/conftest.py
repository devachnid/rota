import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture(autouse=True)
def _breathe_off(settings):
    """The suite never talks to Breathe. Tests that need a configured client
    set the key themselves, always with an injected opener or a patched
    from_settings."""
    settings.BREATHE_API_KEY = ""


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


@pytest.fixture
def staff_user(db):
    return User.objects.create_superuser(email="staff@example.com", password="pw")


@pytest.fixture
def staff_client(staff_user):
    client = Client()
    client.force_login(staff_user)
    return client


@pytest.fixture
def configured(settings):
    """A relay is named, so sends go to the locmem outbox instead of
    coming back as links to copy."""
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "Practice Rota <rota@example.org>"
