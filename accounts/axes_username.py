"""The name django-axes counts login failures against.

The login name is an email address, and the lockout is per name: five
failures against "tom@…" lock "tom@…". Without this, "Tom@…" and "TOM@…"
were separate names with separate counters, so the limit was five times
the number of spellings. Now every spelling is one name — the same one
the login lookup uses (accounts.models.UserManager.get_by_natural_key).

Reads the same field axes would read without a callable: the form's
"username" key (AXES_USERNAME_FORM_FIELD), from the credentials when a
backend passes them and from the POST body otherwise.
"""

from django.conf import settings


def axes_username(request, credentials=None):
    field = settings.AXES_USERNAME_FORM_FIELD
    if credentials:
        value = credentials.get(field)
    else:
        value = getattr(request, "data", request.POST).get(field)
    return value.strip().lower() if isinstance(value, str) else value
