"""Who should be linked to FindMyShift, decided once.

FindMyShift holds the practice's own staff and their time off. A locum is
a contractor who books their own sessions, so there is no time off to read
for one — and "not linked" is not something to fix for them. Every count of
unlinked clinicians (the dashboard's FindMyShift step and health line, the
sync status page, the week grid's banner) and the list those counts link
to leave the locum group out, and they all ask here so they cannot drift
apart.
"""

from django.urls import reverse

from rota.models import Clinician


def expects_link(clinician):
    """Whether this clinician has a FindMyShift record to be linked to."""
    return not clinician.group.is_locum_group


def unlinked_clinicians():
    """Active, not a locum, no FindMyShift link — the people whose time off
    is silently unread."""
    return (Clinician.objects.filter(active=True, group__is_locum_group=False,
                                     findmyshift_staff_id=None)
            .order_by("name"))


def unlinked_changelist_url():
    """The clinician list narrowed to exactly unlinked_clinicians()."""
    return (reverse("admin:rota_clinician_changelist")
            + "?findmyshift=unlinked&active__exact=1&group__is_locum_group__exact=0")
