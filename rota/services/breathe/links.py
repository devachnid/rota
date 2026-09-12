"""Who should be linked to Breathe, decided once.

Breathe holds the practice's employees. A locum is a contractor, never
an employee, so there is no Breathe record a locum could be linked to —
and "not linked" is not something to fix for them. Every count of
unlinked clinicians (the dashboard's Breathe step and health line, the
sync status page, the week grid's banner) and the list those counts link
to leave the locum group out, and they all ask here so they cannot
drift apart.
"""

from django.urls import reverse

from rota.models import Clinician


def expects_link(clinician):
    """Whether this clinician has a Breathe record to be linked to."""
    return not clinician.group.is_locum_group


def unlinked_clinicians():
    """Active, not a locum, no Breathe link — the people whose leave is
    silently unread."""
    return (Clinician.objects.filter(active=True, group__is_locum_group=False,
                                     breathe_employee_id=None)
            .order_by("name"))


def unlinked_changelist_url():
    """The clinician list narrowed to exactly unlinked_clinicians()."""
    return (reverse("admin:rota_clinician_changelist")
            + "?breathe=unlinked&active__exact=1&group__is_locum_group__exact=0")
