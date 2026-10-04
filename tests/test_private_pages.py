"""Signed-in pages are not kept by the browser, and signing out clears what
it kept (config/middleware.py) — for the shared surgery PC, where the next
person presses Back."""

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("url", ["/me/", "/rota/", "/accounts/account/", "/rota/week/"])
def test_signed_in_pages_are_not_stored(gp_client, url):
    resp = gp_client.get(url)
    assert resp.status_code == 200
    policy = resp["Cache-Control"]
    assert "no-store" in policy and "private" in policy


def test_a_view_that_sets_its_own_policy_keeps_it(gp_client):
    """sw.js must be revalidated, not refused a cache: the browser keeps the
    worker script to run it."""
    assert gp_client.get("/sw.js")["Cache-Control"] == "no-cache"


def test_signing_out_clears_the_browsers_copy(gp_client):
    resp = gp_client.post("/accounts/logout/")
    assert resp["Clear-Site-Data"] == '"cache"'


def test_signing_out_of_the_admin_does_too(admin_client):
    resp = admin_client.post("/admin/logout/")
    assert resp["Clear-Site-Data"] == '"cache"'


def test_anonymous_requests_are_left_alone(client):
    resp = client.get("/offline/")
    assert "Clear-Site-Data" not in resp
    assert "no-store" not in resp.get("Cache-Control", "")
