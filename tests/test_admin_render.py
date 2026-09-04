"""Every admin page renders for the practice manager — the upgrade tripwire.

Walks the registry: changelist, add form and change form per model (one
fixture row each), plus the dashboard and the two custom pages. A future
unfold pin bump that breaks a template fails here, not on staging.
"""

from datetime import date

import pytest
from django.contrib import admin
from django.utils import timezone

from tests.factories import (make_clinician, make_commitment, make_entry,
                             make_group, make_pattern, make_session_type,
                             make_site, make_trainee)

pytestmark = pytest.mark.django_db

LEAKED = ["{#", "#}", "{%", "TODO:", "FIXME:", "XXX:", "vestigial"]


@pytest.fixture
def rows(admin_user):
    """One row per rota/accounts model."""
    from rota.models import (BreatheLeaveMapping, BreatheSyncRun,
                             ClosedDay, CoverageRule, DayNote, LocumRequirement,
                             PatternSlot, PracticeSettings, RotaEntryLog, SwapRequest,
                             TraineeStageRule)
    from tests.factories import make_absence
    group = make_group("Partners")
    make_group("Locum", is_locum_group=True, display_order=99)
    c = make_clinician("Ann Able", group=group, user=admin_user)
    d = make_clinician("Bob Baker", group=group)
    st = make_session_type("Duty")
    make_pattern(c)
    return {
        "cliniciangroup": group, "clinician": c, "sessiontype": st,
        "site": make_site(), "patternslot": PatternSlot.objects.first(),
        "coveragerule": CoverageRule.objects.create(session_type=st),
        "traineestagerule": TraineeStageRule.objects.first(),
        "traineeprofile": make_trainee(d),
        "recurringcommitment": make_commitment(c, st),
        "closedday": ClosedDay.objects.create(day=date(2026, 12, 25), reason="Christmas"),
        "daynote": DayNote.objects.create(day=date(2026, 9, 7), text="CQC visit"),
        "practicesettings": PracticeSettings.load(),
        "rotaentry": make_entry(c, session_type=st),
        "rotaentrylog": RotaEntryLog.objects.create(day=date.today(), action="created"),
        "locumrequirement": LocumRequirement.objects.create(
            day=date.today(), part="AM", session_type=st),
        "swaprequest": SwapRequest.objects.create(
            proposer=c, proposer_day=date.today(), proposer_part="AM",
            colleague=d, colleague_day=date.today(), colleague_part="PM"),
        "breatheabsence": make_absence(c, date.today()),
        "breatheleavemapping": BreatheLeaveMapping.objects.first(),
        "breathesyncrun": BreatheSyncRun.objects.create(
            started=timezone.now(), finished=timezone.now(), ok=True),
        "user": admin_user,
    }


def _models():
    return [m for m in admin.site._registry if m._meta.app_label in ("rota", "accounts")]


def _clean(html, where):
    for frag in LEAKED:
        assert frag not in html, (where, frag)


@pytest.mark.parametrize("model", _models(), ids=lambda m: m._meta.model_name)
def test_every_changelist_and_form_renders_for_a_rota_admin(admin_client, rows, model):
    opts = model._meta
    base = f"/admin/{opts.app_label}/{opts.model_name}/"
    ma = admin.site._registry[model]
    resp = admin_client.get(base, follow=True)
    assert resp.status_code == 200, (base, resp.status_code)
    final = resp.redirect_chain[-1][0] if resp.redirect_chain else base
    assert final.startswith(base), (base, final)
    _clean(resp.content.decode(), base)
    if ma.has_add_permission(resp.wsgi_request):
        add_resp = admin_client.get(base + "add/")
        assert add_resp.status_code == 200, base + "add/"
        _clean(add_resp.content.decode(), base + "add/")
    row = rows[opts.model_name]
    resp = admin_client.get(f"{base}{row.pk}/change/")
    assert resp.status_code == 200, f"{base}{row.pk}/change/"
    _clean(resp.content.decode(), f"{base}{row.pk}/change/")


@pytest.mark.parametrize("url", ["/admin/", "/admin/rota/patternslot/bulk/",
                                 "/admin/rota/breathesyncrun/status/"])
def test_the_dashboard_and_custom_pages_render(admin_client, rows, url):
    resp = admin_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    for frag in LEAKED:
        assert frag not in html, (url, frag)


def test_further_admin_pages_render_too(admin_client, rows, gp_user):
    """The other pages a rota admin actually reaches: a row's history and
    delete confirmation, another (non-superuser) account's password page,
    the shared password-change form, and the header search endpoint."""
    clinician = rows["clinician"]
    urls = [
        f"/admin/rota/clinician/{clinician.pk}/history/",
        f"/admin/rota/clinician/{clinician.pk}/delete/",
        f"/admin/accounts/user/{gp_user.pk}/password/",
        "/admin/password_change/",
        "/admin/search/?s=x",
    ]
    for url in urls:
        resp = admin_client.get(url)
        assert resp.status_code == 200, url
        html = resp.content.decode()
        for frag in LEAKED:
            assert frag not in html, (url, frag)
