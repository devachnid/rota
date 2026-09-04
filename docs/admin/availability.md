# Availability

**Where:** sidebar › Working patterns › Pattern editor / Recurring commitments; Calendar › Closed days / Day notes

Three separate things decide whether a clinician can be given a session:
**pattern slots** (do they work it), **recurring commitments** (is it already
spoken for), and **closed days** (is the practice open at all).

## Pattern slots

`/admin/rota/patternslot/` — the clinician's standard working week. This is the
foundation everything else sits on: **the fill engine will never assign anyone
to a session they do not have a pattern slot for.**

If a fill produces nothing and reports "no eligible clinician" everywhere, this
is almost always why.

### Use the bulk editor

Adding slots one at a time is painful — a full-time GP needs ten rows. Instead,
from any Clinician's admin page click **"Edit pattern"**, or go to the Pattern
slots list and use the **Bulk edit** link.

That gives you one screen per clinician: tick every AM/PM session they work
across the week, set the effective date, save. It writes only the slots that
actually changed relative to the pattern in force the day before, so it stays
tidy on repeat edits.

### Weekday / Part

Monday = 0. Part is AM or PM.

### Works

Whether they work that session. A slot with **works unticked** is meaningful,
not redundant — it is how you record that someone has *stopped* working a
session they used to.

### Effective from

The date this row starts applying.

**The rule: for a given clinician, weekday and part, the row with the latest
`effective_from` on or before the day in question wins. No matching row at all
means not working.**

This is what makes patterns change cleanly over time. To move a GP from working
Wednesday PM to not working it from 1 October, you do not edit or delete the old
row — you add a new one with `works` unticked and `effective_from` 1 October.
The rota before that date still resolves correctly against the old row, so
history stays accurate.

The bulk editor does this for you: it shows you the pattern in force before the
date you chose, and writes new rows for the differences.

## Recurring commitments

`/admin/rota/recurringcommitment/` — fixed personal fixtures. A GP's weekly
diabetes clinic, a partner's fortnightly management session.

The commitments pass runs **first**, before every other pass, and never
overwrites an existing entry. So a commitment reliably wins over any coverage
rule that would have wanted the same person.

### Clinician / Session type

Who, and what they are doing.

### Weekday

Monday = 0.

### Part

AM, PM, or **Both** for a full day.

### Site

Optional. Overrides the session type's `default_site` for this commitment —
useful when the same session type happens at different sites for different
people.

### Active from / Active until

The window this commitment applies over. `active_until` is optional; blank means
indefinitely. Use it rather than deleting a commitment that has ended, so past
rotas still explain themselves.

### Interval weeks

**Default: 1** — weekly. Set `2` for fortnightly.

Fortnightly commitments are **anchored to the week of `active_from`**, so that
date decides which weeks the commitment falls in. If a fortnightly clinic is
landing on the wrong weeks, shift `active_from` by one week rather than trying
to compensate elsewhere.

## Closed days

`/admin/rota/closedday/` — bank holidays and one-off closures.

### Day / Reason

The date, and a short label. The reason shows in the grid header.

A closed day is skipped entirely: nothing is filled, no warnings are generated,
and the column is greyed. This is different from
[open weekdays](practice-settings.md#open-weekdays) in Practice settings, which
sets the normal working week — closed days are the exceptions to it.

Add bank holidays as they come round. Nothing does it automatically.

## Day notes

`/admin/rota/daynote/` — a free-text note attached to a whole day, shown in the
grid's day header.

Intended for things that affect planning rather than any one clinician: a
practice meeting, a CQC visit, a training afternoon. Anything that makes you
want to plan the rota around it, but which is not itself a session anybody is
assigned to.

Editable directly from the grid — click a day header — which is usually easier
than coming into the admin for it.
