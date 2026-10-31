"""Who should have a login so Shift Central's leave can be matched to them
by its email. A clinician with no login at all is listed. A login whose email
is blank is possible too (the user model does not insist on one); it matches
nothing, and the sync ignores it, but it is not listed here. A locum books
their own sessions and has no leave to read, so is left out of every count."""

from django.urls import reverse

from rota.models import Clinician


def without_email():
    return (Clinician.objects.filter(active=True, group__is_locum_group=False)
            .filter(user__isnull=True)
            .order_by("name"))


def without_email_changelist_url():
    return reverse("admin:rota_clinician_changelist") + "?active__exact=1&group__is_locum_group__exact=0&user__isnull=True"
