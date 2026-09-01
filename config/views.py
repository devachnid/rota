"""Views that belong to the site rather than to the rota.

The web app manifest lives here and not in `rota/views/` for one specific
reason: `tests/test_security.py::test_every_rota_view_declares_an_authorisation_decorator`
requires every view in that package to carry `@login_required` or
`@admin_required`, and it is right to. The manifest must be fetchable without a
session — a browser reads it before anyone has logged in, and on some platforms
before the app is installed at all — so putting it there would have meant
weakening a security invariant to accommodate a JSON file.
"""

from django.http import JsonResponse
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
