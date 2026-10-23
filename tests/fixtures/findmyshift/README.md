# FindMyShift fixtures

Synthetic. FindMyShift's developer portal documents the methods and their
arguments but not the shape of a response, so these records are the shape
the sync *reads* (rota/services/findmyshift/sync.py, FIELDS) rather than a
recording of a real account. `findmyshift_sync --inspect` against the
practice's own key is what confirms the real names; if they differ, add
them to FIELDS and re-record here, keeping every name and email synthetic —
this repository is public (tests/test_findmyshift_client.py,
test_the_fixtures_hold_no_personal_data).
