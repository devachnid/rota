import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

User = get_user_model()


def test_axes_installed():
    assert "axes" in settings.INSTALLED_APPS
    assert "axes.middleware.AxesMiddleware" in settings.MIDDLEWARE
    assert settings.AXES_FAILURE_LIMIT == 5


def test_login_still_works_with_axes(client, gp_user):
    resp = client.post("/accounts/login/", {
        "username": "gp@example.com", "password": "pw"})
    assert resp.status_code == 302


@pytest.mark.django_db(transaction=True)
def test_sqlite_transactions_begin_immediate():
    # Django's default DEFERRED transaction reads first and takes the write lock
    # later; if another writer (the Breathe sync, a second gunicorn worker) got
    # there in between, SQLite raises "database is locked" at once instead of
    # waiting out the busy timeout. IMMEDIATE takes the lock at BEGIN, so a
    # second writer queues behind the first.
    with CaptureQueriesContext(connection) as captured:
        with transaction.atomic():
            User.objects.filter(pk=-1).update(is_active=True)
    begins = [q["sql"] for q in captured.captured_queries if q["sql"].upper().startswith("BEGIN")]
    assert begins == ["BEGIN IMMEDIATE"]
