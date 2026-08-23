# Frontend Phase 1 — Design system

**Date:** 2026-08-23
**Status:** Approved design, pre-implementation
**Builds on:** the v1 spec (`2026-07-18-gp-rota-design.md`) and autofill v2
(`2026-08-22-autofill-v2-design.md`), both merged.

## Purpose

The app works but looks unfinished: 51 lines of CSS across 13 templates, no type
scale, no spacing system, no component vocabulary, no active state in the nav, no
dark mode, and no responsive behaviour. This phase gives it a real design system
and applies it everywhere, changing no application logic.

This is the first of three frontend phases agreed with the practice:

1. **Phase 1 (this spec)** — design system, applied to all screens.
2. **Phase 2** — mobile: My Schedule reworked for a phone, plus a new day view
   answering "who is on duty today, and is there enough cover for me to take
   leave?" (currently unanswerable on a phone).
3. **Phase 3** — grid interaction: drag-and-drop assignment, keyboard
   navigation, inline editing.

Phases 2 and 3 both inherit this phase's system, which is why it goes first.

## Visual direction

Chosen from three mocked directions: **Daylight's palette and typography with
Ward Board's density**. Daylight answers the original complaint ("doesn't look
like a modern website") and its spacing already suits touch targets, which
matters because most users are GPs on phones. Ward Board's tighter rows keep a
25-clinician week on one desktop screen.

The rejected third direction (Control Room — dark, dense, monospace) remains the
right answer to a different question: if grid density ever outweighs
approachability, it is the reference to return to.

## Tokens

All values are CSS custom properties on `:root`. Nothing in a component
stylesheet may hard-code a colour.

### Colour — chrome

| Token | Light | Role |
|---|---|---|
| `--accent` | `#2F5D50` | Primary buttons, active nav, focus ring |
| `--accent-ink` | `#FFFFFF` | Text on accent |
| `--accent-soft` | `#E4F2EC` | Accent-tinted surfaces |
| `--ink` | `#1B1F27` | Headings |
| `--ink-soft` | `#454C5A` | Body text |
| `--muted` | `#8A91A0` | Labels, column headers, metadata |
| `--ground` | `#FCFCFD` | Page background |
| `--surface` | `#FFFFFF` | Cards, table surface, modal |
| `--sunken` | `#F7F8FA` | Inset areas, unavailable cells |
| `--hairline` | `#ECEDF1` | The few borders that survive |

Semantic colours are separate from the accent: `--danger` (`#A03A24`),
`--warning` (`#855B1B`), `--ok` (`#23604A`), each with a `-soft` background
counterpart.

Neutrals carry a slight cool bias toward the accent's hue rather than being
pure grey.

### Colour — session tints (the 40-colour palette)

Session-type colours are currently a free-text hex field, so the grid's coherence
depends on whoever last typed a colour into the admin. This phase replaces that
with a generated palette.

**Structure: 20 hue families × 2 tones = 40 tints.** Generated in OKLCH at a
fixed lightness and chroma per tone, so every tint occupies the same perceptual
band and the set reads as one family. Hues are spaced evenly around the wheel
(~18° apart) for maximum distinguishability at chip size.

Each tint resolves to three values: a background, a foreground guaranteed to meet
WCAG AA (≥4.5:1) against it, and a dark-mode background for the dark ground.
Contrast is asserted in tests, not eyeballed.

The two tones let related session types share a hue at different strengths —
PMC-Urgent and PMC-Routine, or the vas/coil/implant clinics — so the grid encodes
relatedness rather than assigning 40 unrelated colours.

**Colour is a recognition aid, not the only signal.** Nobody reliably
distinguishes 40 hues at chip size, so session identity is always carried by its
code or name as well; category (clinical / non-clinical / absence) continues to
carry meaning through layout and the existing warning logic.

**Migration:** `SessionType.colour` becomes a choice field over the 40 tint keys.
It is currently `CharField(max_length=7)` — sized for `#RRGGBB` — so the field
widens to hold a key like `teal-strong`. Existing free-form hex values map to
their nearest tint by OKLCH distance, so no configuration is lost and no admin
has to re-pick anything. The old value is kept in a `legacy_colour` column for
one release in case a mapping looks wrong.

### Type

**Plus Jakarta Sans** (400/600/700/800) via Google Fonts, with a real system
fallback stack. Chosen for a contemporary, slightly warm geometric feel that is
not the templated default.

Scale (rem-based, 16px root): `11.5 / 12.5 / 13.5 / 15 / 21 / 30px`.
`font-variant-numeric: tabular-nums` wherever digits align in columns — the
grid, all four reports, and leave balances.

### Space and shape

A 4px base scale (`4 / 8 / 12 / 16 / 24 / 32 / 48`). Radii: `6px` controls,
`8px` chips and cards, `12px` modal. Layout uses flex/grid with `gap` rather
than per-element margins.

### Density

From Ward Board: grid rows `34px`, cell text `12.5px`, chip padding `5px 2px`.
A 25-clinician week fits a 1080p screen without vertical scrolling.

## Dark mode

Built in this phase, not retrofitted. Three states must resolve correctly:

- `:root` defines the complete light palette.
- `@media (prefers-color-scheme: dark)` redefines **only tokens**, guarded as
  `:root:not([data-theme="light"])`.
- `:root[data-theme="dark"]` redefines them again so an explicit choice wins.

No colour may be declared solely inside a media or `[data-theme]` block. `body`
sets an explicit background from a token. Follows the OS setting; no toggle in
Phase 1 (the `[data-theme]` hooks exist so one can be added without restructuring).

## Component vocabulary

Built once, reused across all 13 templates:

- **Buttons** — primary, secondary, quiet; consistent focus ring.
- **Forms** — labels, help text, error states, and the eligibility-warning
  pattern the cell form already uses.
- **Tables** — a `grid` variant (dense, sticky header, sticky clinician column)
  and a `report` variant (roomier, tabular numerals).
- **Session chips** — the tinted cell contents, including the merged full-day
  variant and the hatched draft treatment.
- **Status badges** — the locum ladder (possibly needed / advertised / booked).
- **Warning strips** — day-header warnings and staffing gaps, in semantic colour.
- **Modal** — the htmx-driven cell/day-note/locum editor.
- **Nav** — with an active state, which it currently lacks.
- **Empty states** — several screens currently render a bare table head with no
  rows and no explanation.

## Scope

All 13 templates plus `base.html`: grid, my schedule, fill, inbox, leave form,
swap form, the four reports, and the three htmx partials. Plus the login page,
which is currently unstyled.

**Not in this phase:** any change to interaction (Phase 3), the mobile day view
(Phase 2), and the Django admin, which stays stock — it is a setup surface used
by one person, and styling it is not worth the maintenance.

## Constraints

- **No build step.** Hand-written CSS with custom properties, consistent with the
  v1 decision to favour boring tech that runs for years. No Tailwind, no node,
  no preprocessor.
- **No application logic changes.** Views, services, and models are untouched
  except for the `SessionType.colour` migration.
- **Markup changes must preserve what tests assert:** the `mine`, `closed` and
  `draft` classes, `colspan="2"` on merged duty days, session codes as text,
  clinician names, form field `name` attributes, and the "with <partner>"
  tooltip. The grid stays a `<table>` — it is tabular data, this is correct for
  accessibility, and it keeps those tests meaningful.
- **Accessibility:** visible keyboard focus everywhere, `prefers-reduced-motion`
  respected, AA contrast for all text including every session tint, and the grid
  navigable by screen reader (proper `<th>` scope, caption).

## Testing

CSS itself is not unit-testable, so correctness is protected three ways:

1. **The existing 214 tests must pass unmodified.** They assert on the semantic
   content a restyle must not disturb; they are the regression net.
2. **New tests** for the parts that are logic, not style: the tint palette
   resolves every key to a background/foreground pair, every pair meets AA
   contrast, and the migration maps a set of known legacy hex values to sensible
   tints.
3. **Manual visual check** of every screen in both themes at desktop and phone
   widths, recorded in the implementation report — the only way to catch a
   cascade collision or a silent font fallback.

## Out of scope for the frontend work entirely

Deployment and the manual smoke test of the real practice rules remain
outstanding project work, tracked in `docs/backlog.md`. Neither is a frontend
concern, but the app still has never been deployed.
