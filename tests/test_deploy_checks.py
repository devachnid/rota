"""The static-manifest deploy check.

A deployment can be configured correctly, start cleanly, pass `check --deploy`,
and still 500 on every request: with DEBUG off, `{% static %}` resolves through
a manifest that `collectstatic` writes, and a deployment that pulled new code
without re-running it has no entry for any newly added asset. base.html gained
a font reference, staging did not re-run collectstatic, and every page raised
ValueError with the traceback going only to the journal.

These pin the check that turns that into a deploy-time error.
"""

import pytest
from django.core.checks import Error

from rota import checks


class _FakeStorage:
    def __init__(self, hashed_files):
        self.hashed_files = hashed_files


@pytest.fixture
def manifest_mode(monkeypatch):
    """Pretend we are running the production storage — tests and dev serve
    straight off disk, so the check is otherwise a no-op."""
    monkeypatch.setattr(checks, "_uses_manifest_storage", lambda: True)


def _run():
    return checks.static_manifest_covers_templates(None)


def test_no_op_when_not_using_manifest_storage():
    """Dev and the test suite must not be nagged about a manifest they do not
    use."""
    assert checks.static_manifest_covers_templates(None) == []


def test_missing_manifest_is_an_error(manifest_mode, monkeypatch):
    monkeypatch.setattr(
        "django.contrib.staticfiles.storage.staticfiles_storage",
        _FakeStorage({}),
    )
    errors = _run()
    assert [e.id for e in errors] == ["rota.E002"]
    assert "collectstatic" in errors[0].hint


def test_a_stale_manifest_names_the_missing_asset_and_its_template(
    manifest_mode, monkeypatch
):
    """The message has to say which file and which template, or whoever reads
    it at 8am still has to go looking."""
    refs = checks._template_static_refs()
    assert refs, "no {% static %} literals found in the templates"

    complete = {path: path for path in refs}
    dropped = sorted(refs)[0]
    stale = {k: v for k, v in complete.items() if k != dropped}

    monkeypatch.setattr(
        "django.contrib.staticfiles.storage.staticfiles_storage",
        _FakeStorage(stale),
    )
    errors = _run()
    assert [e.id for e in errors] == ["rota.E003"]
    assert dropped in errors[0].msg
    assert any(t in errors[0].msg for t in refs[dropped])


def test_a_complete_manifest_passes(manifest_mode, monkeypatch):
    refs = checks._template_static_refs()
    monkeypatch.setattr(
        "django.contrib.staticfiles.storage.staticfiles_storage",
        _FakeStorage({path: path for path in refs}),
    )
    assert _run() == []


def test_the_font_base_html_needs_is_among_the_references():
    """The specific asset whose absence took staging down. If base.html stops
    referencing it the test should be updated deliberately, not silently."""
    refs = checks._template_static_refs()
    assert "fonts/plus-jakarta-sans-latin.woff2" in refs
    assert "templates/base.html" in refs["fonts/plus-jakarta-sans-latin.woff2"]


def test_the_check_never_blocks_the_command_that_fixes_it():
    """The first version of this check ran before `collectstatic` and told you
    to run `collectstatic`.

    Two mistakes, both worth pinning. Tagging it "staticfiles" made
    `collectstatic` run it, because that command restricts system checks to
    exactly that tag. And an untagged non-deploy check still breaks `migrate`,
    which runs "__all__" — so a first deployment, where no manifest exists yet
    and none should, could not get off the ground.

    A deploy check is skipped by ordinary management commands and runs for
    `manage.py check --deploy`, which is the question being asked: is this
    safe to serve.
    """
    from django.core.checks.registry import registry
    from django.contrib.staticfiles.apps import StaticFilesConfig  # noqa: F401

    fn = checks.static_manifest_covers_templates

    assert fn not in registry.get_checks(include_deployment_checks=False), (
        "the manifest check runs during ordinary management commands — it will "
        "block collectstatic and migrate before a manifest can exist"
    )
    assert fn in registry.get_checks(include_deployment_checks=True), (
        "the manifest check is not registered as a deploy check, so nothing "
        "runs it at all"
    )
    assert "staticfiles" not in getattr(fn, "tags", ()), (
        "tagged 'staticfiles', which is the exact tag collectstatic runs — "
        "the check would block the command it tells you to run"
    )


# --------------------------------------------------------------------------
# Outgoing email. Optional — without a relay every invitation becomes a
# link for the admin to copy — but a deployment that meant to send and
# cannot should hear it here, not from a GP whose invitation never came.
# --------------------------------------------------------------------------

from django.core.checks import Warning as CheckWarning


def _email():
    return checks.outgoing_email_is_configured(None)


def test_the_email_check_is_quiet_in_debug(settings):
    settings.DEBUG = True
    settings.EMAIL_HOST = ""
    assert _email() == []


def test_no_relay_is_a_warning_naming_the_keys(settings):
    settings.DEBUG = False
    settings.EMAIL_HOST = ""
    found = _email()
    assert [f.id for f in found] == ["rota.W001"]
    assert isinstance(found[0], CheckWarning)
    assert "EMAIL_HOST" in found[0].hint and "/etc/rota.env" in found[0].hint


def test_a_relay_with_the_placeholder_sender_is_an_error(settings):
    settings.DEBUG = False
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "webmaster@localhost"
    found = _email()
    assert [f.id for f in found] == ["rota.E004"] and isinstance(found[0], Error)


def test_a_relay_and_a_real_sender_pass(settings):
    settings.DEBUG = False
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "Practice Rota <rota@example.org>"
    assert _email() == []
