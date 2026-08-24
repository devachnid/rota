# Post-merge backlog

**Last checked against live code: 2026-08-24.** Entries here have gone stale
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

- **The trainee report's "expected" column** shows requirements accruing from
  `requirements_tracked_from` (or placement start when blank), and that is what
  it should show — Tom, 2026-08-24. The system reports what it was asked to
  track; the placement's full contractual total is a deanery question, not a
  rota one. No change needed; `rota/views/reports.py:179` already does this.

## Open — needs a decision, not a fix

- **The session palette has no true neutral.** All 40 tints are colours. The
  family generated at hue 360° was named "Slate", which implied grey but renders
  pink; its label now reads "Rose", which is honest but leaves the gap. A session
  type with no colour chosen, or one whose pre-migration colour was grey, lands
  on that pink via `DEFAULT_TINT`. Adding a genuine neutral means changing the
  tint key set and migrating stored values, so it wants doing deliberately rather
  than bolted on. Deferred by Tom, 2026-08-24.

## Open — minor

- `rota/views/reports.py:150`: `report_trainees` monkeypatches
  `profile.stage_rule` with a lambda to cache the prefetched stage rules. It
  works, but a plain helper computing rates from the prefetched dict would be
  less fragile. (The related crash — a deleted `TraineeStageRule` row 500ing the
  report and every fill — is fixed.)

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
- **Axes lockout is keyed on username only.** Correct behind the Cloudflare
  tunnel, where every request carries the tunnel's IP and IP-keying would be
  useless. Accepted consequence: someone who knows a GP's email can lock that
  account for an hour.
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

