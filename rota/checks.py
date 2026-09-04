"""Deploy-time checks for things that otherwise fail on every page view.

A deployment can be configured correctly, start cleanly, pass `check --deploy`,
and still return 500 for every request. That happened: with DEBUG off the
static files are served through a manifest built by `collectstatic`, and a
deployment that pulled new code without re-running it had no manifest entry for
a font `base.html` references — so `{% static %}` raised ValueError while
rendering, on every page, with the traceback going only to the journal.

The failure belongs at deploy time, where someone is watching.
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning as CheckWarning, register

# {% static 'x' %} / {% static "x" %}, literal paths only. A tag whose argument
# is a variable cannot be resolved without rendering, and is skipped rather
# than guessed at.
_STATIC_TAG = re.compile(r"""\{%\s*static\s+["']([^"']+)["']\s*%\}""")


def _uses_manifest_storage() -> bool:
    backend = settings.STORAGES.get("staticfiles", {}).get("BACKEND", "")
    return "Manifest" in backend


def _template_static_refs() -> dict[str, set[str]]:
    """Every static path that must resolve, mapped to who asks for it.

    Mostly `{% static %}` tags in templates, which is what the name says and
    what it started as. It also carries the web app manifest's icons: those
    are resolved by `static()` in Python (config/views.py), so they have no
    tag for the scan to find, and a missing one would 500 the manifest on
    every cold start of an installed app — exactly the failure this module
    exists to move to deploy time.

    The name is kept because tests/test_deploy_checks.py builds its fixture
    manifest from this function, and that file is not ours to rename against.
    """
    refs: dict[str, set[str]] = {}
    for root in settings.TEMPLATES[0]["DIRS"]:
        for path in Path(root).rglob("*.html"):
            for m in _STATIC_TAG.finditer(path.read_text()):
                refs.setdefault(m.group(1), set()).add(
                    str(path.relative_to(settings.BASE_DIR))
                )


    from config.views import ICON_SOURCES
    for path in ICON_SOURCES:
        refs.setdefault(path, set()).add("config/views.py (web app manifest)")
    return refs


# A DEPLOY check, deliberately, and not tagged "staticfiles".
#
# Both of those are load-bearing and were got wrong first time round:
#
#   - `collectstatic` runs `requires_system_checks = [Tags.staticfiles]`, so
#     tagging this "staticfiles" made it run before collectstatic did anything
#     — blocking the one command that fixes the problem, with a hint telling
#     you to run the command it had just blocked.
#   - `migrate` runs "__all__" checks, so even an untagged non-deploy check
#     breaks a first deployment, where no manifest exists yet and none should.
#
# Deploy checks are skipped by ordinary management commands and run only for
# `manage.py check --deploy`, which is precisely the "is this safe to serve"
# question this is asking. That is the same reason Django files its own HSTS
# and cookie checks there.
@register(deploy=True)
def static_manifest_covers_templates(app_configs, **kwargs):
    """Every literal {% static %} path must be in the manifest."""
    if not _uses_manifest_storage():
        return []  # dev and tests serve straight off disk

    from django.contrib.staticfiles.storage import staticfiles_storage

    refs = _template_static_refs()
    if not refs:
        return []

    try:
        manifest = staticfiles_storage.hashed_files
    except Exception as exc:  # unreadable manifest is the same class of problem
        return [Error(
            f"The static files manifest could not be read ({exc}).",
            hint="Run: python manage.py collectstatic --noinput",
            id="rota.E001",
        )]

    if not manifest:
        return [Error(
            "Static files are served through a manifest, but the manifest is "
            "empty or missing, so every page that uses {% static %} will "
            "raise ValueError while rendering.",
            hint="Run: python manage.py collectstatic --noinput",
            id="rota.E002",
        )]

    missing = sorted(p for p in refs if p not in manifest)
    if missing:
        detail = "; ".join(f"{p} (in {', '.join(sorted(refs[p]))})" for p in missing)
        return [Error(
            f"{len(missing)} static file(s) referenced by templates are not in "
            f"the manifest, so those pages will return 500: {detail}",
            hint="An asset was added or renamed since the last collectstatic. "
                 "Run: python manage.py collectstatic --noinput",
            id="rota.E003",
        )]
    return []


# Email is optional — without a relay every invitation and reset becomes a
# link for the admin to copy, and the dashboard says so — but a deployment
# that meant to send and cannot should hear about it here, not from a GP
# whose invitation never came. Quiet in DEBUG, where nobody is deploying and
# the admin gets each link on screen anyway.
@register(deploy=True)
def outgoing_email_is_configured(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    if not settings.EMAIL_HOST:
        return [CheckWarning(
            "EMAIL_HOST is not set, so invitations and password resets will "
            "show as links for the admin to copy rather than being emailed.",
            hint="Set EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD and "
                 "DEFAULT_FROM_EMAIL in /etc/rota.env — see README › Deploy › "
                 "Outgoing email.",
            id="rota.W001",
        )]
    if settings.DEFAULT_FROM_EMAIL == "webmaster@localhost":
        return [Error(
            "EMAIL_HOST is set but DEFAULT_FROM_EMAIL is Django's placeholder "
            "webmaster@localhost, which the relay will refuse to send as.",
            hint="Set DEFAULT_FROM_EMAIL in /etc/rota.env to a sender the relay "
                 "has validated.",
            id="rota.E004",
        )]
    return []
