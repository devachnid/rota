from datetime import timedelta

import pytest

from rota.models import CoverageRule
from tests.factories import MON, make_session_type

pytestmark = pytest.mark.django_db

# A separate file from tests/test_fill_view.py (the v1 behaviour gate, left
# untouched) so this display-only grouping behaviour has its own regression
# coverage without touching the gate file.


def test_unfilled_slots_grouped_by_type_and_reason(admin_client):
    # Five open weekdays, zero clinicians in the system -> five individual
    # UnfilledSlot rows, all sharing (session_type="Duty",
    # reason="no eligible clinician"). Before grouping, the fill screen
    # rendered one <li> per row (125 rows in a realistic 8-week fill); it
    # must now render exactly one grouped row with the right count.
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    end = MON + timedelta(days=4)
    resp = admin_client.post("/rota/fill/", {
        "start": MON.isoformat(), "end": end.isoformat()})
    content = resp.content.decode()
    assert resp.status_code == 200
    assert content.count("no eligible clinician") == 1, (
        "expected one grouped row, not one per unfilled slot")
    assert "5 occurrence" in content
    assert "(full day)" in content
