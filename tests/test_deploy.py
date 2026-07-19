from django.conf import settings


def test_axes_installed():
    assert "axes" in settings.INSTALLED_APPS
    assert "axes.middleware.AxesMiddleware" in settings.MIDDLEWARE
    assert settings.AXES_FAILURE_LIMIT == 5


def test_login_still_works_with_axes(client, gp_user):
    resp = client.post("/accounts/login/", {
        "username": "gp@example.com", "password": "pw"})
    assert resp.status_code == 302
