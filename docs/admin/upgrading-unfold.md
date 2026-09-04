# Upgrading django-unfold

The admin's chrome is `django-unfold`, pinned exactly in `requirements.txt`.
It is a 0.x package and releases often. Everything we build on it uses its
documented hooks and nothing else:

- `settings.UNFOLD` — plain values and dotted paths (`rota.admin_site.*`,
  `rota.admin_theme.*`, `rota.admin_dashboard.dashboard`).
- `unfold.admin.ModelAdmin`, `StackedInline`, `TabularInline` — every admin.
- `unfold.views.UnfoldModelAdminViewMixin` — the pattern editor and Sync
  status (`rota/admin_pages.py`).
- `unfold.forms` — the login-account change form and the superuser's
  set-password form (the add form is the app's own `InviteForm`).
- `unfold.decorators.action` with `actions_submit_line` — the login-account
  page's **Send invitation again** / **Send password-reset link** button. It
  relies on unfold's `ActionModelAdminMixin.save_model` calling the pressed
  button's method after the save, and on `get_actions_submit_line()` deciding
  which button renders *and* which may fire — guarded by
  `tests/test_invitations.py`.
- `unfold.contrib.filters.admin.RangeDateFilter`.
- `{% component %}` with `unfold/components/card.html`, `container.html`,
  `title.html`, `button.html` — in `templates/admin/index.html` and the two
  page templates. `admin/index.html` is the only unfold template overridden.
- `unfold/helpers/site_branding.html` — included by all three of the
  project's own admin templates (`admin/index.html` and the two custom
  page templates) for the `{% block branding %}` block.
- Tailwind utility classes those same three templates borrow straight from
  unfold's compiled `styles.css` (e.g. `lg:w-1/2`, `text-red-600`,
  `dark:text-red-500`) rather than from a stylesheet of our own — guarded
  by `tests/test_admin_css_classes.py`.
- The font override in `static/admin/rota-admin.css` sets `--font-sans` on
  a bare `:root`, unlayered, so it wins over unfold's own declaration only
  because unfold declares `--font-sans` *inside* an `@layer theme` block
  (lower cascade precedence than an unlayered rule) — guarded by
  `tests/test_admin_theme.py`.

To upgrade: bump the pin, `pip install -r requirements.txt`, run the suite.
`tests/test_admin_render.py` renders every page as a rota admin;
`tests/test_admin_theme.py` checks the colour variables still reach the
page; `tests/test_admin_css_classes.py` checks the borrowed Tailwind classes
still exist in unfold's compiled CSS; the pattern-editor and Breathe tests
check the custom pages; `tests/test_invitations.py` and
`tests/test_passkeys_admin.py` check the login-account page's buttons and
its passkey inline. Then open the dashboard and one change form in both
themes and look. If a component template's parameters changed, the two page
templates are where it shows.
