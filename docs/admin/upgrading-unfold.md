# Upgrading django-unfold

The admin's chrome is `django-unfold`, pinned exactly in `requirements.txt`.
It is a 0.x package and releases often. Everything we build on it uses its
documented hooks and nothing else:

- `settings.UNFOLD` — plain values and dotted paths (`rota.admin_site.*`,
  `rota.admin_theme.*`, `rota.admin_dashboard.dashboard`).
- `unfold.admin.ModelAdmin`, `StackedInline`, `TabularInline` — every admin.
- `unfold.views.UnfoldModelAdminViewMixin` — the pattern editor and Sync
  status (`rota/admin_pages.py`).
- `unfold.forms` — the login-account forms.
- `unfold.contrib.filters.admin.RangeDateFilter`.
- `{% component %}` with `unfold/components/card.html`, `container.html`,
  `title.html`, `button.html` — in `templates/admin/index.html` and the two
  page templates. `admin/index.html` is the only unfold template overridden.

To upgrade: bump the pin, `pip install -r requirements.txt`, run the suite.
`tests/test_admin_render.py` renders every page as a rota admin;
`tests/test_admin_theme.py` checks the colour variables still reach the
page; the pattern-editor and Breathe tests check the custom pages. Then
open the dashboard and one change form in both themes and look. If a
component template's parameters changed, the two page templates are where
it shows.
