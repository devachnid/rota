# Account Invites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin creates a login account with no password; the person sets their own from an emailed link, can reset or change it themselves, and the whole thing works — as links to copy — before any mail relay exists.

**Architecture:** One function, `accounts/mail.py::send_password_link`, mints Django's reset token and emails it (or returns it to copy). The admin's add form, two change-page buttons and a bulk action call it; the public *Forgotten your password?* form calls it with a throttle. Django's own `PasswordResetConfirmView` sets the password and signs the person in. Every page is a template in the app's design system; every email is plain text. Settings read the standard `EMAIL_*` keys from the environment; `EMAIL_HOST` being set is what "configured" means, and a deploy check plus a dashboard step say when it is not.

**Tech Stack:** Django 5.2 (`django.contrib.auth` tokens, views and forms — nothing new), django-unfold 0.104.1 submit-line actions, pytest-django's locmem outbox.

**Spec:** `docs/superpowers/specs/2026-09-04-account-access-design.md` — §1–§4, §6–§8. §5 (passkeys) is a later plan on its own branch.

## Global Constraints

- No build step, no node, **no new dependency** on this branch.
- Secrets live in `/etc/rota.env` and nowhere else. `EMAIL_HOST_PASSWORD` never appears in a repo file, fixture, test, log or ledger.
- Every colour from `static/css/tokens.css`; no CSS colour literals. New pages reuse `.auth-wrap`/`.auth-card` (login) and `.stack`/`.page-head`/`.card` (app pages). This plan adds **no CSS**.
- No pre-existing test assertion is weakened. The two add-form tests in `tests/test_admin_site.py` change shape because the spec removes the password fields; their `is_rota_admin`/`is_superuser` assertions stay.
- `rota/services/*`, `cell_state()` and every rota screen are untouched. The app's chrome changes in exactly two places: the login page gains a link; the signed-in email in the header and tab-bar sheet becomes a link to `/accounts/account/`.
- Exact values: `PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7`; `EMAIL_TIMEOUT = 10`; `EMAIL_PORT` default `587`; `EMAIL_USE_TLS` default on; throttle `RESEND_WAIT = timedelta(minutes=5)`; headers `X-Mailjet-TrackClick: 0` and `X-Mailjet-TrackOpen: 0` on every message; the placeholder sender is `webmaster@localhost`; check ids `rota.W001` and `rota.E004`.
- Copy, verbatim: subjects `Set up your Practice Rota login` / `Reset your Practice Rota password`; admin messages `Invitation sent to {email}.` / `Password-reset link sent to {email}.` / `Email isn't set up — copy this link and send it to {email} yourself:` / `Sending to {email} failed ({reason}) — copy this link and send it yourself:`; state field `Set up` / `Not yet invited` / `Invited {d Mon}, link expires {d Mon}` / `Invitation expired — send another`; buttons `Send invitation again` / `Send password-reset link`; bulk action `Send invitation or reset link`; dashboard step `Outgoing email`; login link `Forgotten your password?`.

## Pre-flight for executors

- `manage.py` on this box needs a secret or `DEBUG=1`. Use `DEBUG=1 .venv/bin/python manage.py …` for `makemigrations`/`check`; never edit `/etc/rota.env`.
- Run pytest as `.venv/bin/python -m pytest …` **without piping to `tail`** — a pipe returns tail's exit status, not pytest's.
- Fixtures (`tests/conftest.py`): `admin_user`/`admin_client` (rota admin, `admin@example.com`, not staff), `gp_user`/`gp_client` (`gp@example.com`), `staff_user`/`staff_client` (superuser, `staff@example.com`); all passwords `pw`. `User.objects.create_user(email=…)` with no password yields an **unusable** password — that is an "invited, not set up" account.
- Under pytest, `EMAIL_BACKEND` is locmem and `django.core.mail.outbox` collects sends. `DEBUG` is `False` under pytest.
- Unfold's submit-line actions: `actions_submit_line = ("method_name", …)`; the button's `name` is `accounts_user_<method_name>`; unfold's `ActionModelAdminMixin.save_model` calls `method(request, obj)` after saving when that name is in `request.POST`; `get_actions_submit_line(request, object_id)` decides which buttons render.

## File structure

| File | Responsibility |
|---|---|
| `config/settings.py` | reads the `EMAIL_*` keys; `PASSWORD_RESET_TIMEOUT`; console backend in DEBUG with no host |
| `accounts/models.py` (+ migration `0003`) | `User.password_link_sent_at` |
| `accounts/mail.py` | **new** — `email_is_configured`, `link_expires`, `password_link`, `LinkToCopy`, `send_password_link` |
| `templates/registration/invitation_*.txt`, `password_reset_*.txt` | **new** — the two emails |
| `rota/checks.py` | deploy check `outgoing_email_is_configured` |
| `rota/admin_dashboard.py`, `templates/admin/index.html` | the ninth setup step; a step without a URL renders as text |
| `accounts/admin.py` | invite add form, state field, `Set up?` column, two submit-line buttons, bulk action, superuser-only password view |
| `accounts/urls.py` | **new** — replaces the `django.contrib.auth.urls` include |
| `accounts/views.py` | `RequestPasswordLinkForm/View`, `SetPasswordFromLinkView`, `ChangePasswordView`, `account` |
| `templates/registration/password_reset_form.html`, `password_reset_done.html`, `password_reset_confirm.html`, `password_change_form.html`, `login.html` | the public pages |
| `templates/accounts/account.html`, `templates/base.html` | the Account page and the two links to it |
| `docs/admin/people.md`, `README.md` | the invite flow; the six keys and Mailjet setup |
| `tests/test_account_mail.py`, `test_invitations.py`, `test_password_links.py` | **new**; plus additions to `test_deploy_checks.py`, `test_admin_dashboard.py`, `test_admin_site.py`, `test_security.py`, `test_template_hygiene.py` |

---

### Task 1: Outgoing email — settings, the field, the send function, the two emails

**Files:**
- Modify: `config/settings.py` (after the `BREATHE_API_URL` line, ~191)
- Modify: `accounts/models.py`
- Create: `accounts/migrations/0003_user_password_link_sent_at.py` (generated)
- Create: `accounts/mail.py`
- Create: `templates/registration/invitation_subject.txt`, `invitation_email.txt`, `password_reset_subject.txt`, `password_reset_email.txt`
- Test: `tests/test_account_mail.py`

**Interfaces:**
- Consumes: `password_reset_confirm` URL name — it exists today via `django.contrib.auth.urls` and Task 4 keeps the name.
- Produces: `accounts.mail.email_is_configured() -> bool`; `link_expires(sent_at: datetime) -> datetime`; `password_link(request, user) -> str`; `LinkToCopy(link: str, reason: str)` (NamedTuple; `reason == ""` means email is not configured); `send_password_link(request, user, *, invite: bool, throttle: bool = False) -> LinkToCopy | None`; `RESEND_WAIT`; `User.password_link_sent_at`.

- [ ] **Step 1: Write the failing tests**

`tests/test_account_mail.py`:

```python
"""Every email leaves through accounts/mail.py. These pin the link it mints,
the headers it sets, what it returns when it cannot send, and the throttle."""

import smtplib
from datetime import timedelta

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode

from accounts.mail import (LinkToCopy, email_is_configured, link_expires,
                           send_password_link)

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def configured(settings):
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "Practice Rota <rota@example.org>"


def _request(rf, user=None):
    request = rf.get("/admin/accounts/user/")
    request.user = user or AnonymousUser()
    return request


def _uid_and_token(link):
    # http://testserver/accounts/reset/<uidb64>/<token>/
    parts = link.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _link_in(message):
    return next(w for w in message.body.split() if w.startswith("http"))


def test_the_settings_this_module_relies_on():
    assert dj_settings.EMAIL_TIMEOUT == 10
    assert dj_settings.PASSWORD_RESET_TIMEOUT == 7 * 24 * 3600
    assert dj_settings.EMAIL_PORT == 587 and dj_settings.EMAIL_USE_TLS is True


def test_email_is_configured_means_a_host_is_named(settings):
    settings.EMAIL_HOST = ""
    assert not email_is_configured()
    settings.EMAIL_HOST = "smtp.example"
    assert email_is_configured()


def test_an_invitation_goes_to_the_person_with_a_working_link(rf, configured, admin_user):
    user = User.objects.create_user(email="new@example.com")
    assert not user.has_usable_password()

    assert send_password_link(_request(rf, admin_user), user, invite=True) is None

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["new@example.com"]
    assert sent.subject == "Set up your Practice Rota login"
    assert sent.from_email == "Practice Rota <rota@example.org>"
    assert sent.extra_headers["X-Mailjet-TrackClick"] == "0"
    assert sent.extra_headers["X-Mailjet-TrackOpen"] == "0"
    link = _link_in(sent)
    assert link.startswith("http://testserver/accounts/reset/")
    uidb64, token = _uid_and_token(link)
    assert urlsafe_base64_decode(uidb64).decode() == str(user.pk)
    assert default_token_generator.check_token(user, token)
    assert "ask admin@example.com" in sent.body      # who sent it is who to ask
    assert "&#" not in sent.body                      # plain text, not HTML-escaped
    user.refresh_from_db()
    assert user.password_link_sent_at is not None


def test_a_reset_reads_as_a_reset(rf, configured, gp_user):
    send_password_link(_request(rf), gp_user, invite=False)
    sent = mail.outbox[0]
    assert sent.subject == "Reset your Practice Rota password"
    assert "ask a rota admin" in sent.body            # anonymous request: no named contact
    assert "ignore this" in sent.body


def test_the_body_names_the_expiry_date(rf, configured, gp_user):
    send_password_link(_request(rf), gp_user, invite=False)
    expires = timezone.localtime(link_expires(timezone.now()))
    assert f"{expires:%-d %B}" in mail.outbox[0].body


def test_without_a_relay_the_link_comes_back_to_copy(rf, settings, admin_user, gp_user):
    settings.EMAIL_HOST = ""
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy) and result.reason == ""
    assert mail.outbox == []
    _, token = _uid_and_token(result.link)
    assert default_token_generator.check_token(gp_user, token)
    gp_user.refresh_from_db()
    assert gp_user.password_link_sent_at is not None


def test_a_refusing_relay_returns_the_link_and_the_reason(rf, configured, monkeypatch,
                                                          admin_user, gp_user):
    def refuse(self, fail_silently=False):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
    monkeypatch.setattr(EmailMessage, "send", refuse)
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy)
    assert "535" in result.reason and "bad credentials" in result.reason
    _, token = _uid_and_token(result.link)
    assert default_token_generator.check_token(gp_user, token)


def test_a_connection_failure_is_a_reason_too(rf, configured, monkeypatch, admin_user, gp_user):
    def refuse(self, fail_silently=False):
        raise ConnectionRefusedError(111, "Connection refused")
    monkeypatch.setattr(EmailMessage, "send", refuse)
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy) and "Connection refused" in result.reason


def test_the_throttle_only_applies_when_asked(rf, configured, gp_user):
    gp_user.password_link_sent_at = timezone.now() - timedelta(minutes=1)
    gp_user.save()
    assert send_password_link(_request(rf), gp_user, invite=False, throttle=True) is None
    assert mail.outbox == []                       # quiet: nothing sent, nothing returned
    assert send_password_link(_request(rf), gp_user, invite=False) is None
    assert len(mail.outbox) == 1                   # an admin's send is never throttled


def test_the_throttle_lifts_after_five_minutes(rf, configured, gp_user):
    gp_user.password_link_sent_at = timezone.now() - timedelta(minutes=6)
    gp_user.save()
    assert send_password_link(_request(rf), gp_user, invite=False, throttle=True) is None
    assert len(mail.outbox) == 1


def test_link_expiry_follows_the_setting(settings):
    settings.PASSWORD_RESET_TIMEOUT = 3600
    now = timezone.now()
    assert link_expires(now) == now + timedelta(hours=1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_account_mail.py -q`
Expected: FAIL — `ImportError: cannot import name 'LinkToCopy' from 'accounts.mail'` (module missing).

- [ ] **Step 3: Settings**

In `config/settings.py`, directly after the `BREATHE_API_URL = …` line, add:

```python
# Outgoing mail: invitations and password-reset links, and nothing else.
# Standard Django keys, every one from /etc/rota.env. EMAIL_HOST being set
# is what "email is configured" means (accounts/mail.py): without it every
# send becomes a link for the admin to copy, the dashboard says so, and
# `check --deploy` warns. Mailjet is plain authenticated SMTP, so nothing
# here names it. EMAIL_TIMEOUT keeps a stalled relay from holding an
# admin's save past gunicorn's worker timeout.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")
if DEBUG and not EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Links are minted ahead of a start date, so a week rather than Django's
# three days. One setting covers invitations and resets alike.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7
```

- [ ] **Step 4: The field and its migration**

In `accounts/models.py`, inside `class User`, after `is_rota_admin`:

```python
    # When the last invitation or password-reset link was handed out — sent,
    # or shown to an admin to copy. For an account with no usable password
    # this is its invitation date; for any account it throttles the public
    # reset form (accounts/mail.py). Null until the first link.
    password_link_sent_at = models.DateTimeField(null=True, blank=True)
```

Run: `DEBUG=1 .venv/bin/python manage.py makemigrations accounts -n user_password_link_sent_at`
Expected: `accounts/migrations/0003_user_password_link_sent_at.py` with one `AddField`.

- [ ] **Step 5: The send function**

`accounts/mail.py`:

```python
"""Every email the app sends leaves through here: an invitation to set a
password, or a link to reset one. Both carry the same link — Django's reset
token, single-use and expiring — with different words around it.

Mailjet is the relay on staging, and it rewrites links for click-tracking
unless told not to: a password link that arrives as an mjt.lu redirect
looks like phishing and hands a third party the click. The two headers
below turn that off per message; they are inert on any other relay.
"""

import smtplib
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

RESEND_WAIT = timedelta(minutes=5)
TRACKING_OFF = {"X-Mailjet-TrackClick": "0", "X-Mailjet-TrackOpen": "0"}


class LinkToCopy(NamedTuple):
    """What send_password_link returns when the email did not go: the link
    for an admin to pass on by hand, and why — "" when email is not
    configured, the relay's own error otherwise."""
    link: str
    reason: str


def email_is_configured():
    """The one test the app uses. EMAIL_HOST is "" unless /etc/rota.env
    names a relay (config/settings.py)."""
    return bool(settings.EMAIL_HOST)


def link_expires(sent_at):
    return sent_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)


def password_link(request, user):
    """Absolute, from the request — right behind the tunnel (https, via
    SECURE_PROXY_SSL_HEADER) and on a dev box (http) alike."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    return request.build_absolute_uri(path)


def send_password_link(request, user, *, invite, throttle=False):
    """Mint a link for `user` and email it.

    Returns None when the email went. Returns a LinkToCopy when it could not
    go — email not configured, or the relay refused — so an admin can pass
    the link on by hand. With throttle=True (the public reset form), a link
    handed out in the last RESEND_WAIT means this call does nothing and
    returns None: the page says the same thing either way.

    password_link_sent_at is stamped whenever a link is handed out, sent or
    shown; the admin's state field and the throttle read it. The token does
    not depend on the stamp, so stamping never invalidates a link.
    """
    if (throttle and user.password_link_sent_at is not None
            and timezone.now() - user.password_link_sent_at < RESEND_WAIT):
        return None
    now = timezone.now()
    link = password_link(request, user)
    context = {
        "link": link,
        "expires": link_expires(now),
        "email": user.email,
        "contact": request.user.email if request.user.is_authenticated else None,
    }
    kind = "invitation" if invite else "password_reset"
    subject = "".join(render_to_string(f"registration/{kind}_subject.txt", context).splitlines())
    body = render_to_string(f"registration/{kind}_email.txt", context)
    user.password_link_sent_at = now
    user.save(update_fields=["password_link_sent_at"])
    if not email_is_configured():
        return LinkToCopy(link, "")
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email],
                           headers=TRACKING_OFF)
    try:
        message.send(fail_silently=False)
    except (smtplib.SMTPException, OSError) as exc:
        return LinkToCopy(link, str(exc) or exc.__class__.__name__)
    return None
```

- [ ] **Step 6: The four email templates**

`templates/registration/invitation_subject.txt` (one line, no trailing newline needed):

```
Set up your Practice Rota login
```

`templates/registration/invitation_email.txt`:

```
{% autoescape off %}Hello,

A Practice Rota login has been created for {{ email }}. Choose your password here:

{{ link }}

The link works until {{ expires|date:"j F" }} and can only be used once. If it has expired, you can ask {% if contact %}{{ contact }}{% else %}a rota admin{% endif %} to send another, or use "Forgotten your password?" on the login page.

If you weren't expecting this, ignore it — nothing happens until the link is used.
{% endautoescape %}
```

`templates/registration/password_reset_subject.txt`:

```
Reset your Practice Rota password
```

`templates/registration/password_reset_email.txt`:

```
{% autoescape off %}Hello,

Someone asked to reset the password for the Practice Rota login {{ email }}. Choose a new one here:

{{ link }}

The link works until {{ expires|date:"j F" }} and can only be used once. If it has expired, you can ask {% if contact %}{{ contact }}{% else %}a rota admin{% endif %} to send another.

If that wasn't you, ignore this — your password stays as it is.
{% endautoescape %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_account_mail.py -q`
Expected: 11 passed.

Then: `DEBUG=1 .venv/bin/python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/python -m pytest -q -x`
Expected: everything passes — nothing yet calls the new module.

- [ ] **Step 9: Commit**

```bash
git add config/settings.py accounts/models.py accounts/migrations/0003_user_password_link_sent_at.py accounts/mail.py templates/registration/invitation_subject.txt templates/registration/invitation_email.txt templates/registration/password_reset_subject.txt templates/registration/password_reset_email.txt tests/test_account_mail.py
git commit -m "feat: outgoing email — settings, the send function, and the two emails"
```

---

### Task 2: The deploy check and the dashboard step

**Files:**
- Modify: `rota/checks.py` (append; change the import line)
- Modify: `rota/admin_dashboard.py:31-86`
- Modify: `templates/admin/index.html:20`
- Test: `tests/test_deploy_checks.py` (append), `tests/test_admin_dashboard.py` (one assertion changes, one test added)

**Interfaces:**
- Consumes: `accounts.mail.email_is_configured()` (Task 1).
- Produces: `rota.checks.outgoing_email_is_configured(app_configs, **kwargs)`; a ninth step titled `Outgoing email` whose `url` is `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deploy_checks.py`:

```python
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
```

In `tests/test_admin_dashboard.py`, change `test_the_headline_counts_and_names_the_next_step` so its first line pins the environment and the total is nine:

```python
def test_the_headline_counts_and_names_the_next_step(settings):
    settings.EMAIL_HOST = ""
    Site.objects.create(name="Main")
    steps = setup_steps()
    assert steps["done"] == 1 and steps["total"] == 9
    assert steps["next"]["title"] == "Practice settings"
    assert not steps["complete"]
```

and append:

```python
def test_the_email_step_follows_email_host(settings, admin_client):
    settings.EMAIL_HOST = ""
    step = _step("Outgoing email")
    assert not step["done"] and "EMAIL_HOST" in step["detail"] and step["url"] is None
    html = admin_client.get("/admin/").content.decode()
    assert "Outgoing email" in html
    settings.EMAIL_HOST = "smtp.example"
    assert _step("Outgoing email")["done"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_deploy_checks.py tests/test_admin_dashboard.py -q`
Expected: FAIL — `AttributeError: module 'rota.checks' has no attribute 'outgoing_email_is_configured'`; `total == 8`; `StopIteration` from `_step("Outgoing email")`.

- [ ] **Step 3: The check**

In `rota/checks.py`, change the import to `from django.core.checks import Error, Warning as CheckWarning, register` and append:

```python
# Email is optional — without a relay every invitation and reset becomes a
# link for the admin to copy, and the dashboard says so — but a deployment
# that meant to send and cannot should hear about it here, not from a GP
# whose invitation never came. Quiet in DEBUG, where the console backend
# prints the mail instead.
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
```

- [ ] **Step 4: The step**

In `rota/admin_dashboard.py`, add `from accounts.mail import email_is_configured` to the imports, and inside `setup_steps()` add after the `synced = …` line:

```python
    email_ok = email_is_configured()
```

and as the last entry of the `steps` list (after the Breathe step):

```python
        # Server configuration, not a database row, so nothing to link to.
        {"title": "Outgoing email", "done": email_ok,
         "detail": ("invitations and password resets go by email" if email_ok
                    else "EMAIL_HOST is not set — invitations show as links to copy"),
         "url": None},
```

In `templates/admin/index.html`, replace line 20:

```html
          <a href="{{ step.url }}" class="underline">{{ step.title }}</a>
```

with:

```html
          {% if step.url %}<a href="{{ step.url }}" class="underline">{{ step.title }}</a>{% else %}{{ step.title }}{% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deploy_checks.py tests/test_admin_dashboard.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add rota/checks.py rota/admin_dashboard.py templates/admin/index.html tests/test_deploy_checks.py tests/test_admin_dashboard.py
git commit -m "feat: a deploy check and a dashboard step for outgoing email"
```

---

### Task 3: The admin — invite on add, state, send buttons, bulk action, superuser-only password form

**Files:**
- Modify: `accounts/admin.py` (whole file replaced below)
- Modify: `tests/test_admin_site.py:166-201` (the two add-form tests)
- Test: `tests/test_invitations.py`

**Interfaces:**
- Consumes: `send_password_link`, `LinkToCopy`, `link_expires` (Task 1).
- Produces: `CustomUserAdmin.account_state(obj) -> str`, `is_set_up(obj) -> bool`; submit-line buttons named `accounts_user_send_invitation` / `accounts_user_send_reset_link`; changelist action `send_links`.

- [ ] **Step 1: Write the failing tests**

`tests/test_invitations.py`:

```python
"""An admin creates the account; the person sets the password from an
emailed link. These pin the add form, the state the change page shows, the
send buttons, the bulk action, and that a rota admin can no longer set
anyone's password directly — only a superuser keeps that form."""

import smtplib
from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMessage
from django.utils import timezone

pytestmark = pytest.mark.django_db
User = get_user_model()
ADD = "/admin/accounts/user/add/"
LIST = "/admin/accounts/user/"


@pytest.fixture
def configured(settings):
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "rota@example.org"


def _change(user):
    return f"/admin/accounts/user/{user.pk}/change/"


def _form(user, **extra):
    """A change-form POST that leaves the account as it is. The System
    flags are only on a superuser's form; a rota admin's form ignores the
    extra keys (test_admin_site proves that)."""
    data = {"email": user.email,
            "is_rota_admin": "on" if user.is_rota_admin else "",
            "is_active": "on",
            "is_staff": "on" if user.is_staff else "",
            "is_superuser": "on" if user.is_superuser else ""}
    data.update(extra)
    return data


def _user_admin():
    return admin.site._registry[User]


# --- adding -----------------------------------------------------------------

def test_the_add_form_asks_for_email_and_role_only(admin_client):
    html = admin_client.get(ADD).content.decode()
    assert 'name="email"' in html and 'name="is_rota_admin"' in html
    assert 'name="password1"' not in html and 'name="usable_password"' not in html


def test_adding_an_account_sends_an_invitation(admin_client, configured):
    resp = admin_client.post(ADD, {"email": "new@example.com", "is_rota_admin": "on"},
                             follow=True)
    user = User.objects.get(email="new@example.com")
    assert not user.has_usable_password() and user.is_rota_admin and not user.is_superuser
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["new@example.com"]
    assert mail.outbox[0].subject == "Set up your Practice Rota login"
    html = resp.content.decode()
    assert "Invitation sent to new@example.com" in html
    assert "Invited" in html and "link expires" in html   # landed on the change page


def test_without_a_relay_the_admin_gets_the_link_to_copy(admin_client, settings):
    settings.EMAIL_HOST = ""
    html = admin_client.post(ADD, {"email": "new@example.com"}, follow=True).content.decode()
    assert mail.outbox == []
    assert "copy this link and send it to new@example.com yourself" in html
    assert 'href="http://testserver/accounts/reset/' in html


def test_a_refusing_relay_shows_the_reason_and_the_link(admin_client, configured, monkeypatch):
    def refuse(self, fail_silently=False):
        raise smtplib.SMTPRecipientsRefused({"new@example.com": (550, b"no such user")})
    monkeypatch.setattr(EmailMessage, "send", refuse)
    html = admin_client.post(ADD, {"email": "new@example.com"}, follow=True).content.decode()
    assert "Sending to new@example.com failed" in html and "550" in html
    assert 'href="http://testserver/accounts/reset/' in html


# --- the state field ---------------------------------------------------------

def test_the_state_field_reads_the_account(settings, gp_user):
    settings.PASSWORD_RESET_TIMEOUT = 7 * 24 * 3600
    state = _user_admin().account_state
    assert state(gp_user) == "Set up"
    invited = User.objects.create_user(email="invited@example.com")
    assert state(invited) == "Not yet invited"
    invited.password_link_sent_at = timezone.now()
    sent = timezone.localtime(invited.password_link_sent_at)
    expires = timezone.localtime(invited.password_link_sent_at + timedelta(days=7))
    assert state(invited) == f"Invited {sent:%-d %b}, link expires {expires:%-d %b}"
    invited.password_link_sent_at = timezone.now() - timedelta(days=8)
    assert state(invited) == "Invitation expired — send another"


def test_the_change_page_shows_the_state(admin_client, gp_user):
    html = admin_client.get(_change(gp_user)).content.decode()
    assert "Set up" in html and "Invited" not in html


def test_the_changelist_says_who_is_set_up(admin_client, gp_user):
    invited = User.objects.create_user(email="invited@example.com")
    is_set_up = _user_admin().is_set_up
    assert is_set_up(gp_user) is True and is_set_up(invited) is False
    assert "Set up?" in admin_client.get(LIST).content.decode()


# --- the buttons -------------------------------------------------------------

def test_the_submit_line_offers_the_right_button(admin_client, gp_user):
    html = admin_client.get(_change(gp_user)).content.decode()
    assert 'name="accounts_user_send_reset_link"' in html
    assert 'name="accounts_user_send_invitation"' not in html
    assert "Send password-reset link" in html
    invited = User.objects.create_user(email="invited@example.com")
    html = admin_client.get(_change(invited)).content.decode()
    assert 'name="accounts_user_send_invitation"' in html
    assert 'name="accounts_user_send_reset_link"' not in html
    assert "Send invitation again" in html


def test_pressing_the_button_sends(admin_client, configured, gp_user):
    resp = admin_client.post(_change(gp_user), _form(gp_user, accounts_user_send_reset_link="1"),
                             follow=True)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Reset your Practice Rota password"
    assert "Password-reset link sent to gp@example.com" in resp.content.decode()

    invited = User.objects.create_user(email="invited@example.com")
    admin_client.post(_change(invited), _form(invited, accounts_user_send_invitation="1"))
    assert len(mail.outbox) == 2
    assert mail.outbox[1].subject == "Set up your Practice Rota login"


def test_saving_without_a_button_sends_nothing(admin_client, configured, gp_user):
    assert admin_client.post(_change(gp_user), _form(gp_user)).status_code == 302
    assert mail.outbox == []


def test_a_rota_admin_cannot_send_to_a_superuser(admin_client, configured, staff_user):
    resp = admin_client.post(_change(staff_user),
                             _form(staff_user, accounts_user_send_reset_link="1"))
    assert resp.status_code == 403 and mail.outbox == []


def test_a_superuser_can_send_to_anyone(staff_client, configured, admin_user, staff_user):
    staff_client.post(_change(admin_user), _form(admin_user, accounts_user_send_reset_link="1"))
    staff_client.post(_change(staff_user), _form(staff_user, accounts_user_send_reset_link="1"))
    assert sorted(m.to[0] for m in mail.outbox) == ["admin@example.com", "staff@example.com"]


# --- the bulk action ---------------------------------------------------------

def test_the_bulk_action_sends_to_everyone_the_requester_may_change(
        admin_client, staff_client, configured, gp_user, staff_user):
    invited = User.objects.create_user(email="invited@example.com")
    data = {"action": "send_links",
            "_selected_action": [gp_user.pk, invited.pk, staff_user.pk]}

    resp = admin_client.post(LIST, data, follow=True)
    assert sorted(m.to[0] for m in mail.outbox) == ["gp@example.com", "invited@example.com"]
    assert mail.outbox[0].subject != mail.outbox[1].subject   # one reset, one invitation
    assert "2 sent" in resp.content.decode()

    mail.outbox.clear()
    staff_client.post(LIST, data)
    assert len(mail.outbox) == 3


def test_the_bulk_action_hands_over_links_when_it_cannot_send(admin_client, settings, gp_user):
    settings.EMAIL_HOST = ""
    resp = admin_client.post(LIST, {"action": "send_links", "_selected_action": [gp_user.pk]},
                             follow=True)
    html = resp.content.decode()
    assert "0 sent, 1 to copy" in html
    assert 'href="http://testserver/accounts/reset/' in html


# --- direct password setting is a superuser's tool now -----------------------

def test_only_a_superuser_reaches_the_direct_set_password_form(admin_client, staff_client, gp_user):
    url = f"/admin/accounts/user/{gp_user.pk}/password/"
    assert admin_client.get(url).status_code == 403
    assert admin_client.post(url, {"password1": "orchard-lantern-quiet-42",
                                   "password2": "orchard-lantern-quiet-42"}).status_code == 403
    gp_user.refresh_from_db()
    assert gp_user.check_password("pw")
    assert staff_client.get(url).status_code == 200


def test_a_rota_admins_change_page_has_no_password_link(admin_client, staff_client, gp_user):
    assert "password/" not in admin_client.get(_change(gp_user)).content.decode()
    assert f"{gp_user.pk}/password/" in staff_client.get(_change(gp_user)).content.decode()
```

Replace the two add-form tests in `tests/test_admin_site.py` (lines 166–201) with:

```python
def test_a_rota_admin_can_create_a_login_account(admin_client):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    get_resp = admin_client.get("/admin/accounts/user/add/")
    html = get_resp.content.decode()
    assert get_resp.status_code == 200
    assert 'name="password1"' not in html        # the person chooses their own, from the link
    assert 'name="is_superuser"' not in html

    resp = admin_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com",
        "is_rota_admin": "on",
    })
    assert resp.status_code == 302, resp.content.decode()
    user = User.objects.get(email="new@example.com")
    assert user.is_rota_admin is True
    assert user.is_superuser is False
    assert not user.has_usable_password()


def test_a_superuser_can_create_a_login_account(staff_client):
    from django.contrib.auth import get_user_model
    User = get_user_model()

    resp = staff_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com",
        "is_rota_admin": "on",
    })
    assert resp.status_code == 302, resp.content.decode()
    assert User.objects.filter(email="new@example.com").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_invitations.py tests/test_admin_site.py -q`
Expected: FAIL — the add form still has `password1`; `account_state` missing; buttons absent; `password/` returns 200 for a rota admin.

- [ ] **Step 3: Replace `accounts/admin.py`**

```python
from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.forms import AdminPasswordChangeForm, UserChangeForm

from .mail import link_expires, send_password_link
from .models import User


class InviteForm(forms.ModelForm):
    """The add form: who, and whether they run the rota. No password — the
    person chooses their own from the emailed link (save_model below)."""

    class Meta:
        model = User
        fields = ("email", "is_rota_admin")


def _report(request, user, result, *, invite):
    """The three outcomes of a send, as the message the admin reads. A link
    is shown here, once, and nowhere else."""
    what = "Invitation" if invite else "Password-reset link"
    if result is None:
        messages.success(request, f"{what} sent to {user.email}.")
    elif not result.reason:
        messages.warning(request, format_html(
            "Email isn't set up — copy this link and send it to {} yourself: "
            '<a href="{}">{}</a>', user.email, result.link, result.link))
    else:
        messages.error(request, format_html(
            "Sending to {} failed ({}) — copy this link and send it yourself: "
            '<a href="{}">{}</a>', user.email, result.reason, result.link, result.link))


@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    """A rota admin (not a superuser) can open this changelist through
    RotaAdminBackend's blanket accounts.* grant. Without the guards below,
    that grant would let them edit is_staff/is_superuser on any account —
    including their own — through the ordinary change form, and reach a
    superuser's delete/password views. Only a superuser requester sees or
    can touch those fields or accounts; the guards defer to Django's normal
    checks for everyone else.

    Passwords: an admin never types one. Adding an account sends an
    invitation; the change page offers one send button, chosen by state;
    the direct set-password form stays for superusers only."""

    form = UserChangeForm
    add_form = InviteForm
    change_password_form = AdminPasswordChangeForm
    ordering = ("email",)
    list_display = ("email", "is_rota_admin", "is_active", "is_set_up", "clinician_name")
    list_filter = ("is_rota_admin", "is_active")
    search_fields = ("email",)
    readonly_fields = ("clinician_name", "account_state")
    list_select_related = ("clinician",)
    add_fieldsets = (
        (None, {"fields": ("email", "is_rota_admin")}),
    )
    actions = ("send_links",)
    actions_submit_line = ("send_invitation", "send_reset_link")

    def get_queryset(self, request):
        """The changelist a rota admin sees excludes superuser rows
        entirely — see the docstring above. get_object() below does NOT
        go through this filtered queryset: a pk lookup (change/delete/
        password views) must still find a superuser's row so has_view_
        permission/has_change_permission/has_delete_permission can turn
        it away with their own 403, rather than this filter making
        Django treat the row as not existing (a redirect instead)."""
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        return qs

    def get_object(self, request, object_id, from_field=None):
        queryset = admin.ModelAdmin.get_queryset(self, request)
        model = queryset.model
        field = model._meta.pk if from_field is None else model._meta.get_field(from_field)
        try:
            object_id = field.to_python(object_id)
            return queryset.get(**{field.name: object_id})
        except (model.DoesNotExist, ValidationError, ValueError):
            return None

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        # `password` is Django's hash field with the link to the direct
        # set-password form — a superuser's tool, so only they see it.
        account = (("email", "password", "account_state") if request.user.is_superuser
                   else ("email", "account_state"))
        sets = [
            ("Account", {"fields": account}),
            ("Rota", {
                "fields": ("is_rota_admin", "clinician_name"),
                "description": "A rota admin can publish weeks, run the fill, and "
                               "use this admin. Link a clinician on their record "
                               "under People › Clinicians.",
            }),
        ]
        if request.user.is_superuser:
            sets.append(("System", {"fields": ("is_active", "is_staff", "is_superuser")}))
        else:
            sets.append(("Status", {"fields": ("is_active",)}))
        return sets

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields = tuple(fields) + ("is_staff", "is_superuser")
        return fields

    def has_view_permission(self, request, obj=None):
        # Django's changeform_view checks has_view_OR_change_permission on a
        # GET, so has_change_permission alone would still hand a rota admin
        # a read-only look at (and, per the check below, a working change
        # form URL for) a superuser's account. Blocking view too closes that.
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    # --- invitations ---------------------------------------------------------

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_unusable_password()
        # unfold's save_model runs whichever submit-line button was pressed,
        # after the save — so the two send_* methods below fire from here.
        super().save_model(request, obj, form, change)
        if not change:
            _report(request, obj, send_password_link(request, obj, invite=True), invite=True)

    def get_actions_submit_line(self, request, object_id):
        """One button, chosen by state: an account with no usable password
        can be invited again; one with a password can be sent a reset."""
        obj = self.get_object(request, object_id)
        want = ("send_reset_link" if obj is not None and obj.has_usable_password()
                else "send_invitation")
        return [a for a in super().get_actions_submit_line(request, object_id)
                if a.action_name.endswith(want)]

    @action(description="Send invitation again")
    def send_invitation(self, request, obj):
        _report(request, obj, send_password_link(request, obj, invite=True), invite=True)

    @action(description="Send password-reset link")
    def send_reset_link(self, request, obj):
        _report(request, obj, send_password_link(request, obj, invite=False), invite=False)

    @admin.action(description="Send invitation or reset link")
    def send_links(self, request, queryset):
        """Onboard a practice at once. Each row gets whichever it needs;
        rows the requester may not change (a superuser's, for a rota
        admin) are skipped — the changelist filter hides them anyway."""
        sent = copies = 0
        for user in queryset:
            if not self.has_change_permission(request, user):
                continue
            invite = not user.has_usable_password()
            result = send_password_link(request, user, invite=invite)
            if result is None:
                sent += 1
            else:
                copies += 1
                _report(request, user, result, invite=invite)
        messages.info(request, f"{sent} sent, {copies} to copy.")

    @admin.display(description="Set up?", boolean=True)
    def is_set_up(self, obj):
        return obj.has_usable_password()

    @admin.display(description="State")
    def account_state(self, obj):
        if obj.has_usable_password():
            return "Set up"
        sent = obj.password_link_sent_at
        if sent is None:
            return "Not yet invited"
        expires = link_expires(sent)
        if timezone.now() < expires:
            return (f"Invited {timezone.localtime(sent):%-d %b}, "
                    f"link expires {timezone.localtime(expires):%-d %b}")
        return "Invitation expired — send another"

    def user_change_password(self, request, id, form_url=""):
        """Django's direct set-password form. A rota admin sends links
        instead — so this is a superuser's tool, whatever has_change_
        permission says about the account."""
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    @admin.display(description="Clinician")
    def clinician_name(self, obj):
        clinician = getattr(obj, "clinician", None)
        if clinician is None:
            return "—"
        url = reverse("admin:rota_clinician_change", args=[clinician.pk])
        return format_html('<a href="{}">{}</a>', url, clinician.name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_invitations.py tests/test_admin_site.py -q`
Expected: all pass. If `test_without_a_relay_the_admin_gets_the_link_to_copy` fails on the `href` assertion while the message text is present, unfold's message include is escaping the HTML: read `.venv/lib/python3.13/site-packages/unfold/templates/unfold/helpers/messages/warning.html` (and `error.html`), copy it to `templates/unfold/helpers/messages/warning.html` (same path under the project's `templates/`) and render `{{ message }}` without any escaping filter. Say so in your report.

- [ ] **Step 5: Bite check**

Comment out the `raise PermissionDenied` line in `user_change_password`; run `.venv/bin/python -m pytest tests/test_invitations.py::test_only_a_superuser_reaches_the_direct_set_password_form -q` and confirm it FAILS; restore the line and confirm it passes.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (the admin render tripwire and the sidebar-link test fetch these pages too).

- [ ] **Step 7: Commit**

```bash
git add accounts/admin.py tests/test_invitations.py tests/test_admin_site.py
git commit -m "feat: accounts are invited, not given a password — state, send buttons, bulk action"
```

---

### Task 4: The public side — Forgotten your password?, and setting a password from a link

**Files:**
- Create: `accounts/urls.py`
- Modify: `config/urls.py:12`
- Modify: `accounts/views.py` (whole file replaced)
- Create: `templates/registration/password_reset_form.html`, `password_reset_done.html`, `password_reset_confirm.html`
- Modify: `templates/registration/login.html`
- Test: `tests/test_password_links.py`

**Interfaces:**
- Consumes: `send_password_link`, `email_is_configured` (Task 1).
- Produces: URL names `login`, `logout`, `password_change`, `password_change_done`, `password_reset`, `password_reset_done`, `password_reset_confirm` (the last three now the app's views); `accounts.views.RequestPasswordLinkForm`, `RequestPasswordLinkView`, `SetPasswordFromLinkView`. Task 5 adds `account` and replaces the password-change pair.

- [ ] **Step 1: Write the failing tests**

`tests/test_password_links.py`:

```python
"""Anyone can ask for a link; the link sets a password and signs them in.
These pin the public form (what it sends, what it never reveals), the
throttle, and the set-password page in both its voices."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

pytestmark = pytest.mark.django_db
User = get_user_model()
RESET = "/accounts/password_reset/"
DONE = "/accounts/password_reset/done/"
STRONG = "orchard-lantern-quiet-42"


@pytest.fixture
def configured(settings):
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "rota@example.org"


def _link_for(client, user):
    """Ask the public form for a link and read it out of the outbox — the
    same path a real person takes."""
    client.post(RESET, {"email": user.email})
    link = next(w for w in mail.outbox[-1].body.split() if w.startswith("http"))
    return link.replace("http://testserver", "")


def _form_url(client, link):
    """GET the emailed link: Django moves the token into the session and
    redirects to a URL without it. That URL is where the form lives."""
    resp = client.get(link, follow=True)
    return resp, resp.redirect_chain[-1][0]


# --- asking ------------------------------------------------------------------

def test_the_login_page_offers_the_way_back_in(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'href="/accounts/password_reset/"' in html
    assert "Forgotten your password?" in html


def test_the_request_page_is_the_apps_own(client):
    resp = client.get(RESET)
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "auth-card" in html and "Forgotten your password?" in html
    assert 'name="email"' in html
    assert "admin/base" not in [t.name for t in resp.templates]


def test_a_known_address_gets_a_reset_link(client, configured, gp_user):
    resp = client.post(RESET, {"email": "GP@example.com"})       # case-insensitive
    assert resp.status_code == 302 and resp["Location"] == DONE
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Reset your Practice Rota password"
    assert "ask a rota admin" in mail.outbox[0].body


def test_an_unset_account_gets_an_invitation_instead(client, configured):
    User.objects.create_user(email="invited@example.com")
    client.post(RESET, {"email": "invited@example.com"})
    assert mail.outbox[0].subject == "Set up your Practice Rota login"


@pytest.mark.parametrize("email", ["nobody@example.com", "inactive@example.com"])
def test_unknown_and_inactive_addresses_send_nothing_and_look_the_same(client, configured, email):
    User.objects.create_user(email="inactive@example.com", password="pw", is_active=False)
    resp = client.post(RESET, {"email": email})
    assert resp.status_code == 302 and resp["Location"] == DONE
    assert mail.outbox == []


def test_the_done_page_promises_nothing_specific(client):
    html = client.get(DONE).content.decode()
    assert "Check your email" in html and "auth-card" in html


def test_a_second_request_within_five_minutes_is_quiet(client, configured, gp_user):
    client.post(RESET, {"email": gp_user.email})
    client.post(RESET, {"email": gp_user.email})
    assert len(mail.outbox) == 1
    gp_user.refresh_from_db()
    gp_user.password_link_sent_at -= timedelta(minutes=6)
    gp_user.save()
    client.post(RESET, {"email": gp_user.email})
    assert len(mail.outbox) == 2


def test_without_a_relay_the_public_form_never_shows_a_link(client, settings, gp_user):
    """The admin's fallback — the link on screen — must never happen here:
    this page is public, and the link is the password."""
    settings.EMAIL_HOST = ""
    resp = client.post(RESET, {"email": gp_user.email}, follow=True)
    assert mail.outbox == []
    assert "/accounts/reset/" not in resp.content.decode()
    gp_user.refresh_from_db()
    assert gp_user.password_link_sent_at is None


# --- the link ----------------------------------------------------------------

def test_an_invitation_link_welcomes_sets_the_password_and_signs_in(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    link = _link_for(client, user)
    resp, form_url = _form_url(client, link)
    html = resp.content.decode()
    assert form_url.endswith("/set-password/")
    assert "Welcome" in html and "choose a password" in html
    assert 'name="new_password1"' in html and "auth-card" in html

    resp = client.post(form_url, {"new_password1": STRONG, "new_password2": STRONG})
    assert resp.status_code == 302 and resp["Location"] == "/rota/"
    assert client.session["_auth_user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.check_password(STRONG)


def test_a_reset_link_speaks_of_a_new_password(client, configured, gp_user):
    resp, _ = _form_url(client, _link_for(client, gp_user))
    html = resp.content.decode()
    assert "Choose a new password" in html and "Welcome" not in html


def test_a_used_link_is_refused(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    link = _link_for(client, user)
    _, form_url = _form_url(client, link)
    client.post(form_url, {"new_password1": STRONG, "new_password2": STRONG})
    client.logout()
    resp, _ = _form_url(client, link)
    html = resp.content.decode()
    assert "no longer valid" in html and 'href="/accounts/password_reset/"' in html
    assert 'name="new_password1"' not in html


def test_an_expired_link_is_refused(client, configured, settings, gp_user):
    link = _link_for(client, gp_user)
    settings.PASSWORD_RESET_TIMEOUT = -1
    resp, _ = _form_url(client, link)
    assert "no longer valid" in resp.content.decode()


def test_a_deactivated_accounts_link_is_refused(client, configured, gp_user):
    link = _link_for(client, gp_user)
    gp_user.is_active = False
    gp_user.save()
    resp, _ = _form_url(client, link)
    assert "no longer valid" in resp.content.decode()
    assert "_auth_user_id" not in client.session


def test_a_garbage_link_is_refused_not_crashed(client):
    resp = client.get("/accounts/reset/not-a-uid/not-a-token/")
    assert resp.status_code == 200 and "no longer valid" in resp.content.decode()


def test_the_password_rules_apply(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    _, form_url = _form_url(client, _link_for(client, user))
    resp = client.post(form_url, {"new_password1": "password", "new_password2": "password"})
    assert resp.status_code == 200 and "too common" in resp.content.decode()
    user.refresh_from_db()
    assert not user.has_usable_password()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_password_links.py -q`
Expected: FAIL — the login page has no link; the request page renders `admin/base.html`; sends do not happen / the confirm page has no "Welcome".

- [ ] **Step 3: Routes**

`accounts/urls.py`:

```python
"""The app's own routes under /accounts/. This replaces the
django.contrib.auth.urls include: same names, same paths, but the reset
views are ours (accounts/views.py) and every page is a template in the
app's design system. Django's reset/done page is dropped — setting a
password signs the person in and lands on the rota."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password_change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("password_change/done/", auth_views.PasswordChangeDoneView.as_view(),
         name="password_change_done"),
    path("password_reset/", views.RequestPasswordLinkView.as_view(), name="password_reset"),
    path("password_reset/done/", auth_views.PasswordResetDoneView.as_view(),
         name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.SetPasswordFromLinkView.as_view(),
         name="password_reset_confirm"),
]
```

In `config/urls.py`, replace `path("accounts/", include("django.contrib.auth.urls")),` with `path("accounts/", include("accounts.urls")),`.

- [ ] **Step 4: Views**

Replace `accounts/views.py`:

```python
"""Getting a password without an admin typing one.

RequestPasswordLinkView is "Forgotten your password?" — public, and so the
one place a link must never be shown on screen. SetPasswordFromLinkView is
where every emailed link lands, invitation or reset: it sets the password
and signs the person in.
"""

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.http import urlsafe_base64_decode

from .mail import email_is_configured, send_password_link
from .models import User


class RequestPasswordLinkForm(PasswordResetForm):
    """Django's form, with two changes: an account that has never set a
    password (an expired invitation) is included, so it self-heals without
    an admin; and the send goes through send_password_link, throttled.
    Without a relay it does nothing at all — the page reads the same, and
    the link never reaches a public screen."""

    def get_users(self, email):
        return User._default_manager.filter(email__iexact=email, is_active=True)

    def save(self, request=None, **kwargs):
        if not email_is_configured():
            return
        for user in self.get_users(self.cleaned_data["email"]):
            send_password_link(request, user, invite=not user.has_usable_password(),
                               throttle=True)


class RequestPasswordLinkView(PasswordResetView):
    form_class = RequestPasswordLinkForm
    template_name = "registration/password_reset_form.html"
    success_url = reverse_lazy("password_reset_done")


class SetPasswordFromLinkView(PasswordResetConfirmView):
    """Django moves the token from the URL into the session before showing
    the form (reset_url_token), so it never sits in browser history. Only
    active accounts resolve — Django's own get_user does not check — and a
    good link signs the person straight in."""

    template_name = "registration/password_reset_confirm.html"
    post_reset_login = True
    post_reset_login_backend = "django.contrib.auth.backends.ModelBackend"
    success_url = settings.LOGIN_REDIRECT_URL

    def get_user(self, uidb64):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            return User._default_manager.get(pk=uid, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist, ValidationError):
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_invitation"] = self.user is not None and not self.user.has_usable_password()
        return context
```

- [ ] **Step 5: Templates**

`templates/registration/password_reset_form.html`:

```html
{% extends "base.html" %}
{% block title %}Forgotten password{% endblock %}
{% block content %}
<div class="auth-wrap">
  <p class="auth-brand">Rota</p>
  <div class="auth-card">
    <h1>Forgotten your password?</h1>
    <p class="field-help">Enter your login email and we'll send you a link to choose a new one.</p>
    <form method="post">
      {% csrf_token %}
      {{ form.as_p }}
      <button type="submit" class="btn btn-primary">Send me a link</button>
    </form>
    <p class="field-help"><a href="{% url 'login' %}">Back to log in</a></p>
  </div>
</div>
{% endblock %}
```

`templates/registration/password_reset_done.html`:

```html
{% extends "base.html" %}
{% block title %}Check your email{% endblock %}
{% block content %}
<div class="auth-wrap">
  <p class="auth-brand">Rota</p>
  <div class="auth-card">
    <h1>Check your email</h1>
    <p class="field-help">If there's a login for that address, a link to choose a new password is on its way. It works for seven days.</p>
    <p class="field-help">Nothing arrived? Check your spam folder, or ask a rota admin to send one.</p>
    <p class="field-help"><a href="{% url 'login' %}">Back to log in</a></p>
  </div>
</div>
{% endblock %}
```

`templates/registration/password_reset_confirm.html`:

```html
{% extends "base.html" %}
{% block title %}{% if not validlink %}Link no longer valid{% elif is_invitation %}Welcome{% else %}Choose a new password{% endif %}{% endblock %}
{% block content %}
<div class="auth-wrap">
  <p class="auth-brand">Rota</p>
  <div class="auth-card">
    {% if validlink %}
      <h1>{% if is_invitation %}Welcome — choose a password{% else %}Choose a new password{% endif %}</h1>
      <p class="field-help">{% if is_invitation %}This sets the password for {{ form.user.email }}. You'll be signed in straight after.{% else %}For {{ form.user.email }}. You'll be signed in straight after.{% endif %}</p>
      <form method="post">
        {% csrf_token %}
        {{ form.as_p }}
        <button type="submit" class="btn btn-primary">{% if is_invitation %}Set password and sign in{% else %}Change password and sign in{% endif %}</button>
      </form>
    {% else %}
      <h1>This link is no longer valid</h1>
      <p class="field-help">It may have expired or already been used. <a href="{% url 'password_reset' %}">Request another</a>, or ask a rota admin to send one.</p>
    {% endif %}
  </div>
</div>
{% endblock %}
```

In `templates/registration/login.html`, after the `</form>` line and before the closing `</div>` of `.auth-card`, add:

```html
    <p class="field-help"><a href="{% url 'password_reset' %}">Forgotten your password?</a></p>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_password_links.py tests/test_account_mail.py tests/test_invitations.py -q`
Expected: all pass.

- [ ] **Step 7: Bite check**

In `RequestPasswordLinkForm.save`, delete the `if not email_is_configured(): return` guard; run `.venv/bin/python -m pytest tests/test_password_links.py::test_without_a_relay_the_public_form_never_shows_a_link -q` — it must FAIL on `password_link_sent_at is None` (the stamp proves a link was minted for a public request). Restore the guard; it passes.

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass — `tests/test_axes_lockout.py`, `test_security.py` and `test_admin_site.py` exercise `/accounts/login/` and `/accounts/logout/` by path and by name, which the new `accounts/urls.py` keeps.

- [ ] **Step 9: Commit**

```bash
git add accounts/urls.py config/urls.py accounts/views.py templates/registration/password_reset_form.html templates/registration/password_reset_done.html templates/registration/password_reset_confirm.html templates/registration/login.html tests/test_password_links.py
git commit -m "feat: forgotten-password form and the set-password page, in the app's own design"
```

---

### Task 5: The Account page, change password, and the links to them

**Files:**
- Modify: `accounts/urls.py` (two lines change, one added)
- Modify: `accounts/views.py` (append)
- Create: `templates/accounts/account.html`, `templates/registration/password_change_form.html`
- Modify: `templates/base.html:40` and `:65`
- Modify: `tests/test_security.py` (`PROTECTED` list), `tests/test_template_hygiene.py` (URL list)
- Test: `tests/test_password_links.py` (append)

**Interfaces:**
- Consumes: Task 4's `accounts/urls.py` and views.
- Produces: URL names `account` (`/accounts/account/`) and `password_change` (now `accounts.views.ChangePasswordView`); `password_change_done` is removed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_password_links.py`:

```python
# --- the Account page and changing a password while signed in ----------------

def test_the_account_page_needs_a_login(client):
    resp = client.get("/accounts/account/")
    assert resp.status_code == 302 and resp["Location"].startswith("/accounts/login/?next=")


def test_the_account_page_shows_the_email_and_the_way_to_change_the_password(gp_client):
    html = gp_client.get("/accounts/account/").content.decode()
    assert "gp@example.com" in html and 'href="/accounts/password_change/"' in html


def test_the_signed_in_email_links_to_the_account_page(gp_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = gp_client.get("/rota/").content.decode()
    assert html.count('href="/accounts/account/"') == 2   # header, and the tab bar's More sheet


def test_the_change_form_is_the_apps_own(gp_client):
    html = gp_client.get("/accounts/password_change/").content.decode()
    assert "auth-card" in html and 'name="old_password"' in html


def test_changing_the_password_keeps_you_signed_in_and_says_so(gp_client, gp_user):
    resp = gp_client.post("/accounts/password_change/", {
        "old_password": "pw", "new_password1": STRONG, "new_password2": STRONG}, follow=True)
    assert resp.redirect_chain[-1][0] == "/accounts/account/"
    html = resp.content.decode()
    assert "Password changed." in html
    assert resp.wsgi_request.user.is_authenticated
    gp_user.refresh_from_db()
    assert gp_user.check_password(STRONG)


def test_the_old_change_done_route_is_gone(gp_client):
    assert gp_client.get("/accounts/password_change/done/").status_code == 404
```

In `tests/test_security.py`, add `"/accounts/account/", "/accounts/password_change/"` to the `PROTECTED` list. In `tests/test_template_hygiene.py`, add `"/accounts/account/", "/accounts/password_change/", "/accounts/password_reset/"` to the `parametrize` list above `test_no_developer_notes_reach_the_rendered_page`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_password_links.py tests/test_security.py tests/test_template_hygiene.py -q`
Expected: FAIL — `/accounts/account/` is 404; the change form renders the admin template; `/accounts/password_change/done/` is 200.

- [ ] **Step 3: Routes and views**

In `accounts/urls.py`, replace the two `password_change` entries with:

```python
    path("account/", views.account, name="account"),
    path("password_change/", views.ChangePasswordView.as_view(), name="password_change"),
```

Append to `accounts/views.py` (add `from django.contrib import messages`, `from django.contrib.auth.decorators import login_required`, `from django.contrib.auth.views import PasswordChangeView` and `from django.shortcuts import render` to its imports):

```python
class ChangePasswordView(PasswordChangeView):
    """Signed in and knows the old one. Back to the Account page with a
    word, rather than Django's separate done page."""

    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("account")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)


@login_required
def account(request):
    """The person's own page: who they are signed in as, and the things
    only they can do to it. Passkeys join it on their own branch."""
    return render(request, "accounts/account.html")
```

- [ ] **Step 4: Templates and the two links**

`templates/accounts/account.html`:

```html
{% extends "base.html" %}
{% block title %}Account{% endblock %}
{% block content %}
<div class="stack">
  <div class="page-head">
    <h1>Account</h1>
  </div>
  <div class="card">
    <p>Signed in as <strong>{{ user.email }}</strong>.</p>
    <div class="form-actions">
      <a href="{% url 'password_change' %}" class="btn">Change password</a>
    </div>
  </div>
</div>
{% endblock %}
```

`templates/registration/password_change_form.html`:

```html
{% extends "base.html" %}
{% block title %}Change password{% endblock %}
{% block content %}
<div class="auth-wrap">
  <p class="auth-brand">Rota</p>
  <div class="auth-card">
    <h1>Change password</h1>
    <form method="post">
      {% csrf_token %}
      {{ form.as_p }}
      <button type="submit" class="btn btn-primary">Change password</button>
    </form>
    <p class="field-help"><a href="{% url 'account' %}">Back to account</a></p>
  </div>
</div>
{% endblock %}
```

In `templates/base.html`, change line 40 from

```html
    <span class="nav-user">{{ user.email }}</span>
```

to

```html
    <a href="{% url 'account' %}" class="nav-user">{{ user.email }}</a>
```

and line 65 from

```html
        <span class="tabbar-user">{{ user.email }}</span>
```

to

```html
        <a href="{% url 'account' %}" class="tabbar-user">{{ user.email }}</a>
```

No CSS changes: `.nav-user` and `.tabbar-user` are class selectors and keep their muted colour over the element's link colour.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_password_links.py tests/test_security.py tests/test_template_hygiene.py tests/test_chrome_contrast.py -q`
Expected: all pass.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add accounts/urls.py accounts/views.py templates/accounts/account.html templates/registration/password_change_form.html templates/base.html tests/test_password_links.py tests/test_security.py tests/test_template_hygiene.py
git commit -m "feat: an Account page with change-password, linked from the signed-in email"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/admin/people.md` (the `### User` section, ~lines 58–70)
- Modify: `README.md` (the secrets block under Deploy, and a new subsection after "Point the Cloudflare tunnel…")

**Interfaces:** none — prose only. Every claim below is something a task above made true; check each against the code before writing it.

- [ ] **Step 1: `docs/admin/people.md`**

Replace the three paragraphs of `### User` (from "Links this clinician…" to the "(`is staff` is separate…)" sentence inclusive) with:

```markdown
Links this clinician to a **login account**, so they can see My Schedule and
propose swaps.

Optional. Leave it blank for someone who is on the rota but does not use the
app — the rota still works, they simply cannot log in. Locums often sit like
this.

Create the account first under **People › Login accounts › Add**: their
email, and whether they are a rota admin. That is all — there is no password
to type. Saving sends them an invitation with a link to choose their own;
their page then reads *Invited …, link expires …* until they have, and *Set
up* after. Links last seven days and work once.

- Link expired, or never arrived? Open the account and press **Send
  invitation again**.
- Forgotten their password? They can use *Forgotten your password?* on the
  login page themselves, or you can press **Send password-reset link** on
  their account.
- A whole practice at once: tick the accounts on the list and choose **Send
  invitation or reset link**.

If outgoing email is not set up (the dashboard's *Outgoing email* step says
so), each of those shows you the link instead, once, to copy into an email
yourself. Nobody — not even you — ever sees anyone's password; only a
superuser keeps a form that sets one directly.

Tick **is rota admin** on anyone who should run fills, publish weeks and
approve requests; it is also what lets them into this admin.
```

- [ ] **Step 2: `README.md`**

After the paragraph "Point the Cloudflare tunnel ingress at `http://127.0.0.1:8321`. Backups land in `backups/`, kept 30 days." insert:

```markdown
### Outgoing email

Invitations and password-reset links go by email. Without a relay the app
still works — an admin is shown each link to copy into an email — and the
dashboard's *Outgoing email* step and `manage.py check --deploy` both say
so.

Mailjet is plain authenticated SMTP. In Mailjet: validate the sender (the
whole domain, adding the SPF and DKIM records it gives you in Cloudflare
DNS), create an API key, and under account settings turn **click tracking**
and **open tracking** off — the app also asks for that on every message,
but a rewritten link is the one thing that must not happen to a password
link. Then:

    cat >> /etc/rota.env <<'EOF'
    EMAIL_HOST=in-v3.mailjet.com
    EMAIL_PORT=587
    EMAIL_HOST_USER=MAILJET_API_KEY_HERE
    EMAIL_HOST_PASSWORD=MAILJET_SECRET_KEY_HERE
    DEFAULT_FROM_EMAIL="Practice Rota <rota@rota.example.org>"
    EOF
    systemctl restart rota

The quotes matter: the file is sourced by a shell as well as read by
systemd, and an unquoted `<` is a redirection. No trailing comments — an
env file has no comment syntax after a value.

`EMAIL_USE_TLS` defaults on (STARTTLS on 587); set `EMAIL_USE_TLS=0` only
for a relay that has no TLS at all. Links last seven days. With `DEBUG=1`
and no `EMAIL_HOST`, mail prints to the console instead.
```

- [ ] **Step 3: Check the claims**

Run: `grep -n "Send invitation again\|Send password-reset link\|Send invitation or reset link\|Outgoing email" accounts/admin.py rota/admin_dashboard.py` — every phrase the docs use must appear. Run: `.venv/bin/python -m pytest tests/test_template_hygiene.py -q` (it scans templates, not docs, but the run is cheap).

- [ ] **Step 4: Commit**

```bash
git add docs/admin/people.md README.md
git commit -m "docs: login accounts by invitation; outgoing email via Mailjet"
```

---

## Self-review

**Spec coverage.** §1 email settings, headers, sending function, deploy check, dashboard step → Tasks 1, 2. §2 field/migration, add form, three messages, state field, one button by state, `Set up?` column, bulk action, permissions, superuser-only password form → Task 3. §3 confirm view, invitation vs reset copy, active-only, auto-login, invalid-link state → Task 4. §4 login link, public form incl. unset accounts, throttle, change password, Account page, nav links, `accounts/urls.py` → Tasks 4, 5. §6 the public form never showing a link → Task 4's test and bite check. §7 every listed test → present across the five test files. §8 docs → Task 6. Not in this plan, by design: §5 and the passkeys paragraph of `upgrading-unfold.md`.

**Placeholders.** None: every code step carries the code; the one conditional instruction (unfold escaping message HTML) names the file to copy and what to change.

**Type consistency.** `send_password_link(request, user, *, invite, throttle=False) -> LinkToCopy | None` is what Tasks 3 and 4 call; `LinkToCopy.link`/`.reason` is what `_report` reads; `email_is_configured()` is used by Tasks 2 and 4; `link_expires(sent_at)` by Task 3; URL names `password_reset`, `password_reset_confirm`, `login`, `account`, `password_change` are defined in Tasks 4–5 and reversed in templates and `mail.py`. Button names `accounts_user_send_invitation`/`accounts_user_send_reset_link` follow unfold's `{app_label}_{model_name}_{method}` rule.
