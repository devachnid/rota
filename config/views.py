"""Views that belong to the site rather than to the rota.

The web app manifest lives here and not in `rota/views/` for one specific
reason: `tests/test_security.py::test_every_rota_view_declares_an_authorisation_decorator`
requires every view in that package to carry `@login_required` or
`@admin_required`, and it is right to. The manifest must be fetchable without a
session — a browser reads it before anyone has logged in, and on some platforms
before the app is installed at all — so putting it there would have meant
weakening a security invariant to accommodate a JSON file.
"""

from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static

# Kept in step with static/css/tokens.css by
# tests/test_pwa.py::test_the_manifest_colours_match_the_design_tokens.
#
# They are written out rather than read from the stylesheet at request time
# because a manifest is fetched on every cold start and neither value has
# changed since the palette was set. The test is what stops them drifting.
THEME_COLOR = "#2F5D50"       # --accent, light
BACKGROUND_COLOR = "#FCFCFD"  # --ground, light

# The manifest resolves these through static() at request time, which means
# rota/checks.py cannot find them the way it finds a template's {% static %}
# tag — so it imports this tuple instead. Adding an icon here is what puts it
# under the deploy check.
ICON_SOURCES = (
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/maskable-512.png",
)


def manifest(request):
    """The web app manifest, at /manifest.webmanifest.

    Built in Python rather than served as a static file because production
    runs CompressedManifestStaticFilesStorage: every icon's real URL carries a
    content hash that changes whenever the file does, and only `static()`
    knows it. A hand-written path here would 404 after the first deploy that
    touched an icon.
    """
    return JsonResponse(
        {
            # Chrome keys an installed app on this, falling back to
            # start_url; naming it lets start_url move without every phone
            # seeing a second app.
            "id": "/",
            "name": "Practice Rota",
            "short_name": "Rota",
            "description": "Who is on, and when you are.",
            "start_url": "/me/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "theme_color": THEME_COLOR,
            "background_color": BACKGROUND_COLOR,
            "icons": [
                {
                    "src": static(ICON_SOURCES[0]),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": static(ICON_SOURCES[1]),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": static(ICON_SOURCES[2]),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        },
        content_type="application/manifest+json",
    )


def service_worker(request):
    """The service worker, at /sw.js.

    Served by a view for the same reason as the manifest, plus one of its
    own: a worker can only control URLs at or below its script's path, so
    `/static/js/sw.js` could never control `/`. The source stays in
    static/js/ with the other scripts and is served byte for byte from there.

    no-cache, because a browser may otherwise keep a worker script for a day
    before checking for a new one.
    """
    source = Path(finders.find("js/sw.js")).read_bytes()
    resp = HttpResponse(source, content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    return resp


def offline(request):
    """What a navigation gets when the network is down.

    The worker stores this at install and serves nothing else from cache, so
    the page is self-contained: no `{% static %}` URL (they change hash on
    deploy) and no base.html (its stylesheets are those URLs).
    """
    return render(request, "offline.html")
