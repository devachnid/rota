# Coverage rules and trainee stage rules

## Coverage rules

`/admin/rota/coveragerule/` — what must be staffed. Each rule says "we need
*this many* of *this session type*, on *these days*, at *this rate*".

This is the most expressive part of the app and the easiest to misconfigure,
because three fields interact: **unit**, **frequency** and **count**.

### Session type

What is being covered.

### Unit — how one placement is shaped

| Unit | Means |
|---|---|
| **Per session** | One placement is one AM or PM session |
| **Per full day** | One placement is AM **and** PM, same clinician, both or neither |
| **Full day preferred (splittable)** | Try a full day first; if nobody is free for both, fall back to separate AM/PM sessions |

Use **Per full day** for Duty, where a half-day makes no sense. Use **Full day
preferred** for demand-driven clinics where one person for the whole day is
better but two halves is acceptable.

### Frequency — how often the need recurs

| Frequency | Means |
|---|---|
| **Per slot** | Every matching session, every matching day. A standing requirement |
| **Per week** | `count` placements somewhere in the week |
| **Per month (average)** | `count` placements per month, spread by weekly accrual |

**Per slot** is the standing-cover shape: "there must always be a Duty GP".

**Per week** and **Per month** are the demand-driven shape: "we need about two
vasectomy sessions a week", "roughly two coil clinics a month". These do not
demand a rigid number in every week — they accrue at a weekly rate and place
whatever is owed, so a quiet week is made up later rather than lost.

Per month converts to a weekly rate of `count × 12 ÷ 52.18`, so two a month
accrues at about 0.46 a week.

### Count

How many. Its meaning depends on frequency: per slot it is "this many in every
matching session", per week or per month it is "this many across the period".

**One validation rule to know:** a **Per full day** rule with **Per week** or
**Per month** frequency must have an **even count**, because each placement
consumes two sessions. An odd count could never be satisfied and the rule would
silently place nothing forever, so the admin rejects it at save time rather than
letting you find out weeks later.

### Parts

AM, PM, or Both. **Per-session rules only — ignored for full-day units**, since
a full day is both by definition.

Use it for asymmetric cover: branch surgery staffed all day in winter but
mornings only in summer is two rules, one with parts AM.

### Weekdays

Comma-separated, **Monday = 0**. Default `0,1,2,3,4`.

Which days the rule applies on at all. A rule that only applies Tuesdays and
Thursdays is `1,3`.

### Months

Comma-separated month numbers, 1–12. **Blank means all year.**

For seasonal cover. Winter branch cover is `10,11,12,1,2,3,4`; the summer
version is `5,6,7,8,9`. Because a rule must match both its weekday list and its
month list, two rules configured this way never overlap — which is how you
express "all day in winter, mornings only in summer" as a pair.

### Preferred weekdays

Ordered comma-separated weekday numbers, tried first. **Per-week and per-month
rules only** — a per-slot rule already names its days.

This is preference, not restriction. `3,1` means "try Thursday, then Tuesday,
then anything else in the weekdays list". A vasectomy clinic that should
normally be Thursday but must not be missed if Thursday is impossible.

### Priority

**Lower fills first. Default 100.**

Coverage rules run in priority order, and earlier rules get first pick of who is
available. This is how you say Duty matters more than branch cover: give Duty
priority 1.

Priority also decides whether a
[`blocks_same_day`](session-types.md#blocks-same-day) restriction fires at all —
the blocking type must fill *first*, so it needs the lower number.

### A worked example

"Two vasectomy sessions a week, ideally Thursday, otherwise Tuesday, preferably
one person for the whole day but splittable, shared evenly between the three
GPs who do them."

- Session type: Vasectomy, with `fairness_tracked` ticked and
  `allowed_clinicians` set to those three GPs — that defines the fairness pool
- Unit: **Full day preferred (splittable)**
- Frequency: **Per week**, count **2**
- Preferred weekdays: `3,1`
- Priority: higher number than Duty, so Duty gets first pick of people

## Trainee stage rules

`/admin/rota/traineestagerule/` — one row per training stage, **seeded
automatically**. You edit these; you cannot add or delete them.

**Deletion is blocked deliberately.** These four rows are reference data that
the trainee report and every trainee fill pass read. Deleting one used to break
both.

Each row sets the weekly entitlement for that stage, which is then scaled by
each trainee's [WTE percent](people.md#wte-percent).

### VTS per week / SDL per week / Mentoring per week

Sessions per week at full time. Decimals are allowed, because pro-rata rarely
lands on whole numbers.

The seeded defaults follow the usual pattern: ST1–ST3 get 1 VTS, 1 SDL and 1
mentoring; FY2 gets 0 VTS and 2 SDL instead, plus 1 mentoring. Adjust if your
deanery differs.

### VTS weekday / VTS part

**Anchors VTS to a fixed session** — the local VTS afternoon.

Monday = 0. Blank weekday means VTS is not anchored and can go anywhere, which
is how FY2 is seeded.

Anchoring matters because the VTS pass runs **second**, before coverage rules,
precisely so the anchored session is protected before anything else competes for
it. If a trainee's VTS is unanchored it gets placed like any other requirement
and can be squeezed.

The three session types these rules refer to are configured in [Practice
settings](practice-settings.md#vts--sdl--mentoring-session-type). **Leaving one
blank skips that pass silently.**
