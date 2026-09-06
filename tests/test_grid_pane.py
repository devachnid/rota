"""The week page is the one page whose body is locked to the viewport so the
grid pane can take exactly the room under the toolbar (screens.css). The
class that switches that on must be on the week page and nowhere else."""

import pytest

pytestmark = pytest.mark.django_db


def test_only_the_week_page_locks_the_body_to_the_viewport(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    week = admin_client.get("/rota/").content.decode()
    assert '<body class="page-grid" hx-headers=' in week
    for url in ("/rota/day/", "/me/", "/requests/", "/reports/fairness/"):
        html = admin_client.get(url).content.decode()
        assert "page-grid" not in html, url
        assert "<body hx-headers=" in html, url
