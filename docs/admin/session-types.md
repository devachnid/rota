# Session types

`/admin/rota/sessiontype/` — everything a clinician can be doing in a session:
Routine, Duty, Urgent, a branch clinic, SDL, annual leave.

Session types carry more configuration than anything else in the app. Each flag
drives a different feature, and several of them are the difference between a
report telling the truth and telling nonsense.

## Name / Code

Name appears in dropdowns and reports. **Code appears in the grid**, where a
cell is about 100px wide — keep it to a few characters.

## Category

**Clinical / Non-clinical / Absence.** This is not cosmetic; three separate
features branch on it.

- **Clinical** counts toward the [minimum clinical GPs per
  session](practice-settings.md#minimum-clinical-per-session) warning.
- **Non-clinical** does not. SDL, VTS, mentoring and admin belong here — a
  trainee doing SDL is not clinical cover.
- **Absence** is excluded from the [group minimum
  warning](people.md#min-per-session), so someone on leave correctly does not
  count as present. Absence types are also the only ones offered on the leave
  request form.

Getting this wrong is quiet. A study-leave type marked Clinical will make a day
look staffed when nobody is there.

## Colour

The tint shown on the grid, chosen from a fixed palette of 42 — 20 hue families
in two strengths, plus a **neutral** pair. Every tint is contrast-checked, so
the text on a chip is always readable in both light and dark mode.

Two strengths per hue lets related types share a family at different weights:
branch-Urgent and branch-Routine as two blues, for instance, so the grid encodes
that they are related.

**Neutral is the default**, and it heads the dropdown. Use it for anything that
should recede — admin time, non-clinical sessions, the types you want the eye to
skip over on a busy week. Spending a colour on everything is how a grid stops
communicating.

Colour is a **recognition aid, not the only signal** — nobody reliably tells 40
hues apart at chip size, so the code is always shown as well.

## Legacy colour

**Read-only.** The free-form hex this type used before the palette existed, kept
so a mapping that looks wrong can be traced back. Nothing reads it at runtime.

## Fairness tracked

Tick this on types that need to be **shared out evenly** — Duty above all, and
usually the demand-driven clinics.

Two things follow:

1. The type appears in the fairness report, and the fill engine picks whoever is
   furthest behind rather than simply whoever is free longest.
2. **A clinician will not be given two different fairness-tracked types on the
   same day.** This stops someone drawing Duty and a vasectomy list on one day
   while a colleague draws neither.

Fairness is pooled by **who is eligible** for the type, which is why the next
setting matters as much as this one.

## Counts toward entitlement

**Tick this on absence types only.**

It means "a session of this type consumes one session of the clinician's annual
leave allowance". It is the entire basis of the leave report and of the balance
on each GP's My Schedule: published entries of types with this ticked, inside
the current leave year, counted as *taken* (past) or *booked* (future) against
their entitlement.

Two things worth knowing:

- **It counts published entries only.** Drafts do not consume allowance.
- **It counts sessions, not days.** A full day off is two.

If this is ticked on working session types, the leave report counts ordinary
work as leave taken and balances go negative. If it is unticked on Annual Leave,
actual leave is counted against nobody. Both mistakes produce a report that
looks broken rather than one that looks empty, so it is worth checking directly
rather than inferring from the numbers.

## Default site

The [site](practice-settings.md#sites) auto-stamped on entries the fill engine
creates for this type.

Set it on branch-surgery types and the grid shows where people are without
anyone typing it. An admin picking a site by hand on a cell overrides it, as
does a recurring commitment with its own site.

## Allowed clinicians and Allowed groups

Who may be given this type. **The two are additive** — the eligible pool is
every named clinician **plus** every member of every named group.

**Leaving both empty means the type is open to everyone.** It does not mean
restricted to nobody.

Use groups for organisational rules ("branch cover is Partners and Salaried
only, not trainees") and named clinicians for skills ("these three do
vasectomies"). Mix them freely.

Two behaviours to know:

- Inactive clinicians drop out of the pool automatically.
- A type that names only individuals, all of whom have since gone inactive,
  stays **restricted to nobody** rather than falling open to everyone. That is
  deliberate — silently opening a skills-restricted clinic to the whole practice
  would be worse than filling nothing.

Because fairness is pooled by eligibility, this field also defines the fairness
pool. A fairness-tracked type with no restrictions shares itself across the
entire practice, which is rarely what you want for a skilled clinic.

## Blocks same day

A clinician holding **this** type on a day is not auto-assigned any of the types
listed here, on the same day.

The classic use is "no Duty on a day you are covering the branch surgery": put
Duty in the branch type's `blocks_same_day`.

**It is directional and evaluated at placement time**, which has a consequence
worth understanding: the block only bites if the *blocking* type is placed
first. If Duty fills before branch cover, the block never fires. So give the
blocking type's coverage rule a **lower `priority` number** than the type it is
meant to block.

This trips people up because the setting looks symmetric and is not.
