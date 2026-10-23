# FindMyShift fixtures

Synthetic. `teams.json` and `staff.json` follow the shape a real account
sent on 2026-10-23 (`teamId`, `staffId`, `timeOffTypes` with
`timeOffTypeId`/`description`), with every name and email made up.
`time-off.json` is still the shape the sync *reads*
(rota/services/findmyshift/sync.py, FIELDS) rather than a recording: the
developer portal documents no response shapes and the test account held no
time off when it was measured. `findmyshift_sync --inspect` against the
practice's own key is what confirms the real names; if they differ, add
them to FIELDS and re-record here, keeping every name and email synthetic —
this repository is public (tests/test_findmyshift_client.py,
test_the_fixtures_hold_no_personal_data).
