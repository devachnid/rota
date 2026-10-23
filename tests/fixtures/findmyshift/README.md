# FindMyShift fixtures

Synthetic, in the shape a real test account sent on 2026-10-23, with every
name, email and id made up. A team is `teamId` + `timeOffTypes`
(`timeOffTypeId`/`description`); a staff record is `staffId` and the
fields the client projects; a time-off record is day-based
(`firstDayOff`/`lastDayOff`, a `days` weekday mask with Sunday 0,
`dateApproved`/`dateDeleted` timestamps or null, `staffId` possibly null,
`type` and `timeOffTypeId`). `recurrence`'s values are the one thing here
that is still assumed — the account held no recurring record. This
repository is public (tests/test_findmyshift_client.py,
test_the_fixtures_hold_no_personal_data).
