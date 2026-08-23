# Post-merge backlog

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

Two entries turned out to be already fixed when checked against live code. Verify
before acting on anything recorded here.

## Open — needs a decision, not a fix

- **What should the trainee report's "expected" column mean?** It currently shows
  the system-tracked figure, accruing from `requirements_tracked_from` (or the
  placement start when that is blank). That is the right basis for *scheduling* —
  the engine should not try to manufacture education time it never observed — but
  it understates the placement's total contractual requirement, which is what a
  deanery would ask about. Showing both figures side by side is probably the
  answer, but it is a domain call, not an implementation one.

## Open — minor

- `rota/views/reports.py`: `report_trainees` monkeypatches `profile.stage_rule`
  with a lambda to cache the prefetched stage rules. It works, but a plain helper
  computing rates from the prefetched dict would be less fragile. (The related
  crash — a deleted `TraineeStageRule` row 500ing the report and every fill — is
  fixed.)

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

## Not yet done (not backlog — outstanding project work)

- **Deployment.** The app has never been deployed. `README.md` has the sequence:
  systemd units, Cloudflare tunnel ingress, `createsuperuser`, and the
  first-time setup data.
- **Manual smoke test.** Configure the real practice rules in `/admin/`, run a
  4-week fill, and eyeball the grid. The autofill v2 review noted this pass alone
  would have independently surfaced three of the defects it found.
- **Frontend.** Still the basic server-rendered UI from v1 — one of the three
  workstreams identified at the start, and the only one untouched.
