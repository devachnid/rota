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

## Open — needs a decision, not a fix

- **What should the trainee report's "expected" column mean?** Still open,
  verified at `rota/views/reports.py:179`. It shows the system-tracked figure,
  accruing from `trainee_anchor(profile)` — `requirements_tracked_from`, or the
  placement start when that is blank. That is the right basis for *scheduling* —
  the engine should not try to manufacture education time it never observed — but
  it understates the placement's total contractual requirement, which is what a
  deanery would ask about. Showing both figures side by side is probably the
  answer, but it is a domain call.

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

## Live configuration — not code, but the app is wrong until these are set

Found during the first real smoke test, 2026-08-24. All three are admin data,
not defects, but each makes a feature silently produce nonsense.

- **`counts_toward_entitlement` is inverted.** It is ON for Routine, Duty,
  Mentoring, SDL and VTS, and OFF for Annual Leave — so the leave report counts
  ordinary working sessions as leave taken and ignores actual leave. This is what
  produced the negative "Remaining" balances. Should be ON for absence types
  only.

- **Leave entitlement is unset for 20 of 22 active clinicians.** Only Paul
  Colquhoun (64) and Rebecca Rowlands (36) have a figure, so everyone else's
  balance goes negative on their first booked session regardless of the flag
  above.

- **Only 11 of 22 active clinicians have any pattern slots** (68 rows total, no
  recurring commitments). This is why the first assisted-fill run created 0
  sessions and reported 106 unfilled slots with "no eligible clinician" — the
  engine had no availability to work from. The bulk pattern editor on the
  Clinician admin page is the fast way in.

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
  dropdown (both fixed in `580747e`), the assisted-fill result explained by the
  missing pattern slots above, and a question about eligibility semantics that
  turned out to be working as intended. The autofill v2 review predicted this
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

- **The PAT in the git remote URL.** `.git/config` holds a GitHub personal access
  token in plaintext, so it surfaces in any git output, log or screen share.
  Rotate it and move to SSH or a credential helper.
