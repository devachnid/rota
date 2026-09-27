import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

import sys

# Running under pytest. Django's test runner forces DEBUG=False anyway, and the
# suite must not require a real SECRET_KEY in the environment to run.
_TESTING = "pytest" in sys.modules

# DEBUG defaults OFF. It used to default ON, which meant a deployment that
# simply forgot to set the variable came up with tracebacks, the URL map on
# every 404, no HSTS, cookies without the Secure flag, and — because the
# SECRET_KEY guard below only fires when DEBUG is off — the placeholder key
# that is published in this repository. A staging deployment did exactly that.
# Forgetting a variable must fail towards safety, so development now opts in
# with DEBUG=1 rather than production opting out with DEBUG=0.
DEBUG = os.environ.get("DEBUG", "0") == "1"

if not os.environ.get("SECRET_KEY") and not _TESTING:
    from django.core.exceptions import ImproperlyConfigured

    if not DEBUG:
        raise ImproperlyConfigured(
            "SECRET_KEY env var must be set. Generate one with:\n"
            "  python -c \"from django.core.management.utils import "
            "get_random_secret_key as k; print(k())\""
        )

def _dev_secret_key():
    """A development key private to this checkout. It was a constant,
    published in this repository, so a server that ran with DEBUG=1 and no
    SECRET_KEY had a key anyone could forge session cookies with. Now it
    is random, written once to a git-ignored file beside manage.py, and
    stable across restarts, so a dev box stays signed in."""
    path = BASE_DIR / ".dev_secret_key"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        from django.core.management.utils import get_random_secret_key
        key = get_random_secret_key()
        path.touch(mode=0o600)
        path.write_text(key)
        return key


SECRET_KEY = os.environ.get("SECRET_KEY") or (
    "test-only-key-not-used-outside-pytest" if _TESTING else _dev_secret_key()
)

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "unfold.apps.BasicAppConfig",   # the theme; Basic, so it does not replace admin.site
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "config.apps.RotaAdminConfig",  # django.contrib.admin with our site class
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "accounts",
    "rota",
    "feedback",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.middleware.RequestLogMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.PrivatePagesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "rota.context_processors.waiting",
                "accounts.context_processors.signed_in_recently",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # Production keeps the database out of the code tree, in the rota
        # user's state directory (deploy/gunicorn.service): SQLite needs to
        # write the directory its database is in, and the app must be able to
        # write its data without being able to write its own code. Unset, the
        # database sits beside manage.py, which is what development wants.
        "NAME": os.environ.get("DB_PATH") or BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # WAL lets readers and the single writer proceed together.
            "init_command": "PRAGMA journal_mode=WAL;",
            # SQLite's default DEFERRED transaction only takes the write lock at
            # the first write, and if another connection (the Breathe sync, the
            # other gunicorn worker) got there first it fails at once with
            # "database is locked" rather than waiting out the busy timeout.
            # IMMEDIATE takes the lock at BEGIN, so writers queue instead.
            "transaction_mode": "IMMEDIATE",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"
# MinimumLengthValidator alone accepts "password" and "12345678". These four
# are Django's full set: length, similarity to the user's own email, the
# 20k-common-password list, and all-numeric.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/rota/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# The admin's chrome. Plain values and dotted paths only — unfold resolves
# the paths per request, so rota.admin_site is never imported here.
UNFOLD = {
    "SITE_TITLE": "Rota",
    "SITE_HEADER": "Practice Rota",
    "SITE_URL": "/rota/",
    "SITE_SYMBOL": "calendar_month",
    "SITE_FAVICONS": [
        {"rel": "icon", "sizes": "32x32", "type": "image/png",
         "href": "rota.admin_site.favicon_32"},
        {"rel": "apple-touch-icon", "sizes": "180x180", "type": "image/png",
         "href": "rota.admin_site.apple_touch_icon"},
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COMMAND": {"search_models": True, "show_history": False},
    "SIDEBAR": {
        "show_search": False,
        "show_all_applications": False,
        "navigation": "rota.admin_site.navigation",
    },
    "COLORS": {
        "primary": "rota.admin_theme.primary",
        "base": "rota.admin_theme.base",
        "font": {
            "subtle-light": "var(--color-base-500)",
            "subtle-dark": "var(--color-base-400)",
            "default-light": "var(--color-base-700)",
            "default-dark": "var(--color-base-300)",
            "important-light": "var(--color-base-900)",
            "important-dark": "var(--color-base-100)",
        },
    },
    "STYLES": ["rota.admin_site.style_fonts", "rota.admin_site.style_admin"],
    "SCRIPTS": ["rota.admin_site.script_theme_bridge"],
    "DASHBOARD_CALLBACK": "rota.admin_dashboard.dashboard",
}

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # The manifest storage requires a collectstatic run, which the test suite
    # has no reason to do — keyed off _TESTING as well as DEBUG so that
    # defaulting DEBUG to off does not make every test need a build step.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if (DEBUG or _TESTING)
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "accounts.backends.RotaAdminBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours

# Addresses whose forwarded-IP header is believed. cloudflared connects over
# loopback, and the systemd unit binds gunicorn there on purpose — see
# accounts/client_ip.py for why that binding is load-bearing.
TRUSTED_PROXY_IPS = frozenset(
    h.strip() for h in os.environ.get(
        "TRUSTED_PROXY_IPS", "127.0.0.1,::1"
    ).split(",") if h.strip()
)

# BreatheHR, which owns leave. Read-only. The key comes from /etc/rota.env
# like SECRET_KEY and never from a file in this repository; with no key the
# integration is off and every consumer degrades quietly.
# Stripped: a key pasted with a trailing newline or CR (a CRLF-edited
# /etc/rota.env) makes http.client refuse the header — with the key itself
# in the error text.
BREATHE_API_KEY = os.environ.get("BREATHE_API_KEY", "").strip()
BREATHE_API_URL = os.environ.get("BREATHE_API_URL", "https://api.breathehr.com/v1")

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

# Links are minted ahead of a start date, so a week rather than Django's
# three days. One setting covers invitations and resets alike.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7

# Without this axes uses REMOTE_ADDR, which behind the tunnel is always
# 127.0.0.1 — one key for every user in the world. django-ipware would also do
# it, but that is a new dependency and this project does not take those.
AXES_CLIENT_IP_CALLABLE = "accounts.client_ip.client_ip"

# Each top-level entry is an independent lockout; a nested list would be one
# combined key. So this locks a username after AXES_FAILURE_LIMIT failures
# *and, separately*, an address — the second is what stops one source
# spraying many accounts, which username-only keying cannot see.
#
# How each is counted is accounts/axes_handler.py's: an address is locked by
# failures against that many *different* accounts, and a success clears only
# the signed-in person's own failures. Clinicians share the surgery's NAT
# address, and axes' own reset — any success there clearing every counter
# for the address — kept fumbles from locking the building out, but it also
# let anyone with an account wipe a colleague's counter and keep guessing.
AXES_HANDLER = "accounts.axes_handler.RotaAxesHandler"
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
# Django's login form — and the passkey login view — report a failure as
# credentials={"username": ...} whatever USERNAME_FIELD is called; axes'
# default for this setting is USERNAME_FIELD ("email"), which never matched,
# so every attempt was recorded with username=None and only the address half
# of the lockout ever locked. Name the key the form actually sends.
AXES_USERNAME_FORM_FIELD = "username"
# ...and lower-case it, so "Tom@" and "tom@" are one name with one counter,
# as they are one account to the login lookup.
AXES_USERNAME_CALLABLE = "accounts.axes_username.axes_username"
# A success clears the person's own counter — only theirs; see AXES_HANDLER.
AXES_RESET_ON_SUCCESS = True
# A lockout lasts AXES_COOLOFF_TIME from the failure that caused it. axes'
# default restarts the hour on every attempt made while locked, which let
# anyone who knew an address keep its owner locked out indefinitely, one
# request an hour. The owner can still get in meanwhile — with a passkey,
# or a password link by email; the lockout page says so.
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
# The page or, for the passkey endpoints, the JSON a locked-out request gets.
AXES_LOCKOUT_CALLABLE = "accounts.lockout.lockout_response"

# AccessAttempt is a counter, and a success clears it — so the admin's
# "Access attempts" can read empty minutes after real failures. The failure
# log is the permanent record; axes leaves it off by default.
AXES_ENABLE_ACCESS_FAILURE_LOG = True

# axes requires a request object during authenticate(), which the test
# client's login()/force_login() don't provide — disable it under pytest.
if _TESTING:
    AXES_ENABLED = False

# Nothing in this app reads the CSRF cookie from JavaScript — base.html feeds
# htmx the token from the template context — so it can be closed to scripts.
CSRF_COOKIE_HTTPONLY = True

if not DEBUG:
    # TLS terminates at the Cloudflare tunnel, and cloudflared says so in
    # X-Forwarded-Proto (SECURE_PROXY_SSL_HEADER below), so a request that
    # arrives as http really was http and is sent to https — whatever the
    # Cloudflare zone's own "Always Use HTTPS" happens to be set to. Not
    # under pytest: CI runs the suite with DEBUG off, over the test client's
    # plain http.
    SECURE_SSL_REDIRECT = not _TESTING
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Where the app's own warnings go: stderr, which systemd sends to the
# journal (`journalctl -u rota`). Without this, Django sends nothing there
# when DEBUG is off — a 500, a CSRF failure or a request with a forged Host
# header left no trace for anyone looking back at an incident.
#
# One handler, on the root logger; the named loggers only set levels and
# propagate to it. (Naming "django" here also drops Django's own console
# handler, which is DEBUG-only, and mail_admins, which ADMINS leaves idle.)
# Propagation matters beyond the journal: tests read log records through
# the root logger, and a logger that stopped propagating would pass every
# "the key never appears in the log" test by logging nowhere they look.
#   django.request at ERROR: 5xx responses, with tracebacks (4xx would be
#     every scanner's 404).
#   django.security: CSRF failures, disallowed hosts, suspicious operations.
#   rota.access: one line per request (config/middleware.RequestLogMiddleware),
#     with the client address from Cloudflare.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "stderr": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["stderr"], "level": "WARNING"},
    "loggers": {
        "django": {"level": "WARNING"},
        "django.request": {"level": "ERROR"},
        "django.security": {"level": "INFO"},
        "rota": {"level": "INFO"},
        "accounts": {"level": "INFO"},
        "feedback": {"level": "INFO"},
    },
}
