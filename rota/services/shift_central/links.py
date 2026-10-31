"""Who should have a login so Shift Central's leave can be matched to them
by its email (a login always has one). A locum books their own sessions and has no leave to read, so is left
out of every count, as before."""

from django.urls import reverse

from rota.models import Clinician


def without_email():
    return (Clinician.objects.filter(active=True, group__is_locum_group=False)
            .filter(user__isnull=True)
            .order_by("name"))


def without_email_changelist_url():
    return reverse("admin:rota_clinician_changelist") + "?active__exact=1&group__is_locum_group__exact=0&user__isnull=True"
