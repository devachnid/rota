"""Who should have a login email so Shift Central's leave can be matched to
them. A locum books their own sessions and has no leave to read, so is left
out of every count, as before."""

from django.db.models import Q
from django.urls import reverse

from rota.models import Clinician


def without_email():
    return (Clinician.objects.filter(active=True, group__is_locum_group=False)
            .filter(Q(user__isnull=True) | Q(user__email=""))
            .order_by("name").distinct())


def without_email_changelist_url():
    return reverse("admin:rota_clinician_changelist") + "?active__exact=1&group__is_locum_group__exact=0&user__isnull=True"
