# Practice HR: foundation and absence — pointer

**Date:** 2026-09-27

The practice's HR system is its own project, `devachnid/practice-hr`. Its
first design spec, *foundation and absence*, was drafted here on 2026-09-27
and moved to that repository's `docs/superpowers/specs/` the same day.

It matters to the rota for two reasons:

- **Sign-in.** The HR system becomes the OpenID Connect provider and the rota
  a relying party; the rota's one change in that release is a *Sign in with
  the practice account* path (the spec's section 3).
- **The next spec, rota integration,** replaces the Breathe sync
  (`2026-09-02-breathe-leave-design.md`) and the rota's own pattern editing
  with feeds from the HR system's read API (the spec's section 7).
