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

SECRET_KEY = os.environ.get("SECRET_KEY") or (
    "test-only-key-not-used-outside-pytest" if _TESTING else "dev-insecure-key"
)

ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "accounts",
    "rota",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"init_command": "PRAGMA journal_mode=WAL;"},
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
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["username"]

# axes requires a request object during authenticate(), which the test
# client's login()/force_login() don't provide — disable it under pytest.
if _TESTING:
    AXES_ENABLED = False

# Nothing in this app reads the CSRF cookie from JavaScript — base.html feeds
# htmx the token from the template context — so it can be closed to scripts.
CSRF_COOKIE_HTTPONLY = True

if not DEBUG:
    SECURE_SSL_REDIRECT = False  # TLS terminates at the Cloudflare tunnel
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
