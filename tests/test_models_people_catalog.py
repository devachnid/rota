import pytest
from django.db import IntegrityError

from tests.factories import make_clinician, make_group, make_session_type

pytestmark = pytest.mark.django_db


def test_session_type_open_to_all_by_default():
    c = make_clinician()
    st = make_session_type("Routine")
    assert st.is_eligible(c)


def test_session_type_restricted_to_named_clinician():
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    st = make_session_type("Vasectomy")
    st.allowed_clinicians.add(a)
    assert st.is_eligible(a) and not st.is_eligible(b)


def test_session_type_restricted_to_group():
    partners = make_group("Partner", display_order=1)
    a = make_clinician("Alice Adams", group=partners)
    b = make_clinician("Beth Brown")
    st = make_session_type("Duty", fairness_tracked=True)
    st.allowed_groups.add(partners)
    assert st.is_eligible(a) and not st.is_eligible(b)


def test_only_one_locum_group():
    make_group("Locum", is_locum_group=True)
    with pytest.raises(IntegrityError):
        make_group("Locum 2", is_locum_group=True)
