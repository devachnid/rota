# Post-merge backlog

**Last checked against live code: 2026-08-31.** Entries here have gone stale
before — two were already fixed when checked, and this file claimed the app was
undeployed for a day after it went live. Verify before acting on anything
recorded here.

Three sweeps on 2026-08-23 cleared everything actionable that the v1 and
autofill v2 review processes had accumulated:

- **Nine user-visible defects** — stuck swap proposals, backwards leave ranges,
  the unreadable unfilled list, false "behind target" readings, lost note/site
  on the eligibility warning, the stage-rule crash, orphaned locum re-booking,
  dead leave/swap links.
- **Six correctness edges** — fairness seeding blind to in-range entries,
  half-covered full-day double-cover, the 29 Feb leave-year crash, whole-range
  trainee accrual seeding, a non-monotonic rotation tie-break, inactive
  clinicians surviving in eligibility pools.
- **The structural tidies** — the duplicated availability rule consolidated into
  one `PatternResolver`, site precedence and the trainee-pass skeleton extracted,
  `swaps.validate()` made single-pass, plus assorted query and validation
  hygiene and the test-coverage gaps earlier reviews flagged.

## Settled

- **Axes now locks by address as well as username** (2026-08-26). The earlier
  decision — username only, because behind the tunnel every request carries the
  tunnel's IP — was correct about the symptom and wrong about the fix: axes was
  falling back to `REMOTE_ADDR` because django-ipware is not installed.
  `AXES_CLIENT_IP_CALLABLE` resolves `CF-Connecting-IP` with no new dependency,
  and `AXES_RESET_ON_SUCCESS` keeps a shared surgery NAT address from locking
  the building out. Verified end to end: five failures across five different
  usernames from one address now blocks it, and an unrelated address is
  unaffected. Clears the `axes.W006` system check.

- **The palette has a true neutral** (2026-08-24). It had none: all 40 tints
  were colours, and the family at hue 360° was named "slate" while rendering a
  pink, which `DEFAULT_TINT` pointed at. That family is now `rose`, which is what
  it is, and a real neutral pair is generated outside the hue ring and is the new
  default. Migration `0019` renames stored values; the rename does not change the
  colour anything renders.

- **The `stage_rule` monkeypatch is gone** (`1b4f094`, 2026-08-24).
  `stage_rule()` and `weekly_rates()` take an optional `{stage: rule}` mapping
  instead. The same N+1 existed unfixed in the fill engine — three trainee
  passes each calling `weekly_rates()` per profile — and is fixed too. Guarded
  by query count rather than by mechanism.

- **The trainee report's "expected" column** shows requirements accruing from
  `requirements_tracked_from` (or placement start when blank), and that is what
  it should show — Tom, 2026-08-24. The system reports what it was asked to
  track; the placement's full contractual total is a deanery question, not a
  rota one. No change needed; `rota/views/reports.py:179` already does this.

## Open — check before deploying the rota-fixes branch

**Stored weekday and month lists are parsed more strictly than they were.** The
branch gave four free-text fields a real parser (`rota/services/ranges.py`):
`PracticeSettings.open_weekdays`, and `CoverageRule.months`, `weekdays`,
`preferred_weekdays`. The old parser silently dropped empty segments, so a
value like `"0,1,2,3,4,"` was savable and readable before and is neither now —
it raises at read time.

That matters because two views reach the parser without the decorator that
turns a parse failure into a 400 explaining itself: `grid`
(`rota/views/grid.py:15`) and `leave_approve` (`rota/views/requests.py:71`). A
trailing comma stored under the old rules therefore 500s the main page rather
than naming the offending value.

**Nothing on this box's dev database trips it — checked 2026-08-31. The staging
database on the LXC is a different database and was not checked.** Run this
there:

```bash
python manage.py shell <<'EOF'
from django.core.exceptions import ValidationError
from rota.models import PracticeSettings, CoverageRule
from rota.services.ranges import validate_int_list as v

bad = []
for s in PracticeSettings.objects.all():
    try:
        v(s.open_weekdays, 0, 6, "open_weekdays")
    except ValidationError as e:
        bad.append(("PracticeSettings", s.pk, e.messages))
for r in CoverageRule.objects.all():
    for field, lo, hi in (("months", 1, 12), ("weekdays", 0, 6), ("preferred_weekdays", 0, 6)):
        try:
            v(getattr(r, field), lo, hi, field)
        except ValidationError as e:
            bad.append((str(r), field, e.messages))
print(bad or "all range fields parse cleanly")
EOF
```

Anything it lists is fixed by editing the field in `/admin/` and saving — the
form validator now rejects the bad value with a message naming it.

The durable fix is a **deploy check** over all four fields, in the existing
`rota/checks.py` `@register(deploy=True)` pattern — view-agnostic, so it closes
both routes and any future one, where wrapping views one at a time closes one
instance of the hazard and leaves the next open. Deliberately not done on the
branch: it would have been unreviewed code landed after the final review gate.

## Open — minor

- **Closed-day headers render two-tone.** On a bank holiday the day-name cell
  greys correctly but the AM/PM row beneath it stays on the surface colour,
  because `closed` is only applied to the upper `<th>` in `grid.html`. Confirmed
  in a browser. Cosmetic, and a template change rather than a styling one.

## Configuration notes

The three configuration problems previously recorded here — inverted
`counts_toward_entitlement`, unset leave entitlements, and missing pattern
slots — were read off the **development** database on this box, not the test
deployment. They do not describe the deployed system and have been removed.

Worth keeping as a lesson rather than a task: the dev DB and the deployed one
have diverged, so any future claim about "the data" needs to say which database
it came from.

## Decided — not defects, do not re-raise

Deliberate choices, recorded so they stop being re-reported by each review pass.

- **systemd units run as root.** Correct for this single-purpose LXC. Revisit
  only if the container ever hosts anything else.
- **Fill re-run has no preview step**, though the spec asks for previews on
  destructive actions. Accepted: re-run provably touches only its own unpublished
  drafts, never published or manually-set entries, and that is enforced by tests.
- **Swap audit log records one clinician's name per touched slot** (the other
  appears in the free-text detail). A second row per swap would be a tidier
  trail, but the information is not lost.
- **The draft hatch is a weak signal on its own.** Unpublished sessions carry a
  diagonal wash, deliberately subtle so the tint underneath stays readable, which
  means it reads as texture rather than as a WCAG 1.4.11 non-text cue. Acceptable
  while draft state is also carried by the "Publish week" button and the fill
  screen's own summary — worth revisiting if drafts ever appear without that
  surrounding context.

## Outstanding project work

- **Deployment — done, 2026-08-24.** Running on the LXC. Not yet exercised
  through the Cloudflare tunnel by real users.

- **Manual smoke test — in progress.** The first pass immediately found four
  issues: a template comment rendering to the page and an unfiltered trainer
  dropdown (both fixed in `580747e`), an assisted-fill run that produced nothing
  because the clinician patterns had not been populated yet, and a question about
  eligibility semantics that turned out to be working as intended. The autofill v2 review predicted this
  pass would surface things no amount of review would, and it did. Still to do:
  configure the real practice rules, run a 4-week fill with patterns populated,
  and check the result against how the rota is actually built.

- **Frontend Phase 1 — done and merged** (`f82033c`, 2026-08-24). Design system
  applied to every screen, browser-verified. **Phases 2 and 3 are specced but not
  started:** Phase 2 is mobile — My Schedule reworked for a phone, plus a day
  view answering "who is on duty today, and is there enough cover for me to take
  leave?", which is currently unanswerable on a phone and is what most GPs will
  actually use. Phase 3 is grid interaction — drag-and-drop assignment, keyboard
  navigation, inline editing.

