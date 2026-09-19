"""The admin for personal requirements: weekdays as checkboxes like a
coverage rule, only active clinicians offered, and a clinician who is not
eligible for the session type refused by name."""

import pytest

from tests.factories import make_clinician, make_group, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def _data(nh, people, **extra):
    data = {"session_type": nh.id, "clinicians": [c.id for c in people],
            "interval_weeks": 6, "part": "EITHER", "weekdays": [],
            "active_from": "2026-01-05", "active_until": ""}
    data.update(extra)
    return data


def test_the_form_refuses_a_clinician_not_eligible_for_the_type():
    from rota.admin_forms import PersonalRequirementForm
    partners = make_group("Partner", display_order=1)
    ann = make_clinician("Ann Able", group=partners)
    bob = make_clinician("Bob Baker")
    nh = make_session_type("Nursing home round", code="NH")
    nh.allowed_groups.add(partners)
    form = PersonalRequirementForm(data=_data(nh, [ann, bob]))
    assert not form.is_valid()
    assert "Bob Baker" in str(form.errors["clinicians"])
    assert "Ann Able" not in str(form.errors["clinicians"])
    ok = PersonalRequirementForm(data=_data(nh, [ann]))
    assert ok.is_valid(), ok.errors


def test_the_form_offers_active_clinicians_only_and_stores_weekdays_as_a_list():
    from rota.admin_forms import PersonalRequirementForm
    ann = make_clinician("Ann Able")
    make_clinician("Gone Away", active=False)
    nh = make_session_type("Nursing home round", code="NH")
    form = PersonalRequirementForm(data=_data(nh, [ann], weekdays=["1", "3"]))
    assert [c.name for c in form.fields["clinicians"].queryset] == ["Ann Able"]
    assert form.is_valid(), form.errors
    req = form.save()
    assert req.weekdays == "1,3" and list(req.clinicians.all()) == [ann]


def test_the_changelist_and_form_render_and_the_sidebar_links_it(admin_client):
    ann = make_clinician("Ann Able")
    req = make_requirement(clinicians=[ann])
    html = admin_client.get("/admin/rota/personalrequirement/").content.decode()
    assert "Nursing home round" in html and "6 weeks" in html
    assert admin_client.get(f"/admin/rota/personalrequirement/{req.pk}/change/").status_code == 200
    index = admin_client.get("/admin/").content.decode()
    assert "Personal requirements" in index
    assert "/admin/rota/personalrequirement/" in index
