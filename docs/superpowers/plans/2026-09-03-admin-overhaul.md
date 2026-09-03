# Admin Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin a practice manager can use with no documentation, and that gets a new practice from empty to a filled rota by following the screen — built on `django-unfold`, organised by job, with the documentation moved onto the page.

**Architecture:** `django-unfold` provides the chrome; `RotaAdminSite(UnfoldAdminSite)` is installed as Django's default admin site through a custom `AdminConfig`, so every `@admin.register` in every app lands on it. `settings.UNFOLD` holds only plain values and dotted paths — unfold resolves those lazily per request — so the admin site is never imported at settings time. Colour scales are derived from `tokens.css` by `rota/admin_theme.py`; a small auth backend makes `is_rota_admin` the one flag; every `ModelAdmin` becomes unfold's with fieldsets and on-page help; the two bespoke pages become unfold custom pages; the dashboard is a callback plus one overridden template.

**Tech Stack:** Django 5.2.16, `django-unfold==0.104.1` (Tailwind v4 + Alpine, bundled; no CDN), WhiteNoise manifest storage, SQLite, pytest-django, Python 3.13. No node, no build step.

**Spec:** `docs/superpowers/specs/2026-09-03-admin-overhaul-design.md`

## Global Constraints

- Exactly one new dependency: `django-unfold==0.104.1`, pinned in `requirements.txt`. Nothing else.
- Every colour comes from `static/css/tokens.css` or `rota/palette.py`. The admin's scales are derived (Task 3), never typed. `static/admin/rota-admin.css` carries no colour literals (`#hex`, `rgb(`, `hsl(`) — a test greps it.
- `cell_state()` and every module under `rota/services/` are untouched. The app's own screens change only by the **Admin** link in `templates/base.html`.
- No pre-existing test assertion is weakened or deleted. The four admin test files (`tests/test_bulk_pattern_admin.py`, `test_pattern_editor.py`, `test_breathe_admin.py`, `test_admin_colour.py`) and `tests/test_breathe_status.py` are re-pointed only where a URL or markup changed; every re-pointing is listed in the task that causes it.
- The Breathe API key appears in no file.
- Migrations: two, containing only `AlterField` (help text) and `AlterModelOptions` (verbose names) — no schema or data change. **Plan-level correction to the spec:** the spec said Django does not migrate `verbose_name`; it does (`AlterModelOptions`), and the `accounts.User` rename needs its own app's migration. So: `rota/migrations/0025_admin_copy.py` and `accounts/migrations/000N_login_account_names.py`, both generated in Task 7.
- `settings.py` never imports `rota.admin_site`: every callable in `UNFOLD` is a dotted string, which unfold's `_get_value` resolves with `import_string` at request time. (The spec's `UNFOLD = build_config()` is replaced by this; same effect, no import-order hazard.)
- Tests: `/root/rota/.venv/bin/python -m pytest -q` from `/root/rota` (~5 min; run in the FOREGROUND with a 600000 ms timeout; targeted files while iterating, the whole suite once before each commit). Baseline: **967 passed** on `master` at `607006d`. Report actual counts; do not chase a forecast.
- Commit style: lower-case type prefix, a sentence on what and why, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Test fixtures (`tests/conftest.py`): `admin_client`/`admin_user` is a **rota admin who is not staff** — exactly the practice manager; `staff_client`/`staff_user` is a superuser; `gp_client`/`gp_user` is neither. Existing admin tests use `staff_client` and must keep passing untouched except where a task lists a re-pointing.

---

## File map

| File | Responsibility |
|---|---|
| `config/apps.py` | `RotaAdminConfig(AdminConfig)` with `default_site = "rota.admin_site.RotaAdminSite"`. |
| `config/settings.py` | `INSTALLED_APPS` order; the `UNFOLD` dict of plain values and dotted paths; the auth backend. |
| `rota/admin_site.py` | `RotaAdminSite`, `is_rota_admin`, `is_superuser`, `navigation(request)`, `settings_link(request)`, static-path callbacks. Imports no models at module level. |
| `rota/admin_theme.py` | `token(name)`, `primary(request=None)`, `base(request=None)` — the colour scales from tokens. |
| `accounts/backends.py` | `RotaAdminBackend` — rota admins hold every `rota.*` and `accounts.*` permission. |
| `rota/admin_forms.py` | `WEEKDAYS`, `MONTHS`, `IntListCheckboxField`, `OrderedCheckboxSelect`, `CoverageRuleForm`, `PracticeSettingsForm`. |
| `rota/admin_widgets.py` | `TintSwatchSelect` (rewritten), Breathe employee widget (unchanged). |
| `rota/admin.py` | Every rota `ModelAdmin`, on unfold's base classes. |
| `rota/admin_system.py` | axes and auth Group re-registered on unfold's `ModelAdmin`; imported by `rota/admin.py`. |
| `rota/admin_pages.py` | `PatternEditorView`, `BreatheStatusView` (unfold custom pages). |
| `rota/admin_dashboard.py` | `setup_steps()`, `health()`, `dashboard(request, context)`. |
| `accounts/admin.py` | `CustomUserAdmin` on unfold's forms. |
| `templates/admin/index.html` | The dashboard (the only unfold template overridden). |
| `templates/admin/rota/patternslot/editor.html`, `templates/admin/rota/breathesyncrun/status.html`, `templates/admin/rota/widgets/tint_swatch.html` | The custom pages and the swatch widget. |
| `static/admin/rota-admin.css`, `static/admin/theme-bridge.js` | Font override; theme sync. |
| `templates/base.html` | The **Admin** link. |
| `docs/admin/*.md`, `README.md` | Updated words; new `docs/admin/upgrading-unfold.md`. |

---

### Task 1: Install unfold and make our site Django's admin site

**Files:**
- Modify: `requirements.txt`
- Create: `config/apps.py`
- Create: `rota/admin_site.py`
- Modify: `config/settings.py` (`INSTALLED_APPS`, new `UNFOLD`)
- Modify: `tests/test_security.py:156-158` (`PROTECTED`)
- Test: `tests/test_admin_site.py` (new)

**Interfaces:**
- Produces: `rota.admin_site.RotaAdminSite`; `is_rota_admin(request) -> bool`; `is_superuser(request) -> bool`; `navigation(request) -> list` (empty until Task 4); static-path callbacks `favicon_32`, `apple_touch_icon`, `style_fonts`, `style_admin`, `script_theme_bridge` (each `(request) -> str`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_site.py`:

```python
"""Who gets into the admin, and what the site is.

`is_rota_admin` is the one flag: a practice manager is a rota admin and
nothing else. Superusers are admitted regardless. Anyone else is turned
away at the door — to the app's own login if anonymous, with a 403 if
signed in as a GP.
"""

import pytest
from django.contrib import admin

from rota.admin_site import RotaAdminSite

pytestmark = pytest.mark.django_db


def test_the_admin_site_is_ours():
    assert isinstance(admin.site, RotaAdminSite)


def test_a_rota_admin_who_is_not_staff_reaches_the_admin(admin_client, admin_user):
    assert not admin_user.is_staff
    assert admin_client.get("/admin/").status_code == 200


def test_a_superuser_reaches_the_admin(staff_client):
    assert staff_client.get("/admin/").status_code == 200


def test_an_anonymous_visitor_lands_on_the_apps_login(client):
    resp = client.get("/admin/", follow=True)
    final_url = resp.redirect_chain[-1][0]
    assert final_url.startswith("/accounts/login/?next=")


def test_a_signed_in_gp_gets_403_not_a_login_loop(gp_client):
    resp = gp_client.get("/admin/", follow=True)
    assert resp.status_code == 403


def test_the_next_parameter_cannot_send_someone_off_site(client):
    resp = client.get("/admin/login/?next=https://evil.example/", follow=False)
    assert resp.status_code == 302
    assert "evil.example" not in resp["Location"]


def test_the_header_reads_practice_rota(admin_client):
    html = admin_client.get("/admin/").content.decode()
    assert "Practice Rota" in html


def test_logout_is_post_only_and_returns_to_the_app_login(admin_client):
    assert admin_client.get("/admin/logout/").status_code == 405
    resp = admin_client.post("/admin/logout/")
    assert resp.status_code == 302 and resp["Location"] == "/accounts/login/"
```

In `tests/test_security.py`, add `"/admin/"` to `PROTECTED`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py -q`
Expected: `ImportError` on `rota.admin_site`.

- [ ] **Step 3: Install the package**

```bash
/root/rota/.venv/bin/python -m pip install django-unfold==0.104.1
```

In `requirements.txt`, add the line `django-unfold==0.104.1` after `django-axes==8.3.1`.

- [ ] **Step 4: The app config and the site**

Create `config/apps.py`:

```python
from django.contrib.admin.apps import AdminConfig


class RotaAdminConfig(AdminConfig):
    """Makes `admin.site` an instance of our RotaAdminSite — an unfold site
    with our access rule — so every @admin.register in every app (ours,
    django-axes', auth's) lands on it. Unfold's own DefaultAppConfig would
    replace admin.site with a plain UnfoldAdminSite; we use its
    BasicAppConfig instead and let Django's default_site mechanism do the
    replacing with our subclass."""
    default_site = "rota.admin_site.RotaAdminSite"
```

Create `rota/admin_site.py`:

```python
"""The admin site, and every value settings.UNFOLD reaches by dotted path.

settings.py never imports this module: unfold resolves the dotted strings
in UNFOLD with import_string at request time, which keeps the admin site
out of settings-import order entirely. Nothing here imports a model at
module level, for the same reason.
"""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.views import redirect_to_login
from django.http import (HttpResponseForbidden, HttpResponseNotAllowed,
                         HttpResponseRedirect)
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from unfold.sites import UnfoldAdminSite


def is_rota_admin(request):
    """The one flag. Superusers are admitted regardless."""
    user = request.user
    return bool(user.is_active and (
        getattr(user, "is_rota_admin", False) or user.is_superuser))


def is_superuser(request):
    return bool(request.user.is_active and request.user.is_superuser)


class RotaAdminSite(UnfoldAdminSite):
    site_title = "Rota"
    site_header = "Practice Rota"
    index_title = "Dashboard"

    def has_permission(self, request):
        return is_rota_admin(request)

    def _safe_next(self, request):
        target = request.GET.get("next", "")
        if target and url_has_allowed_host_and_scheme(
                target, allowed_hosts={request.get_host()},
                require_https=request.is_secure()):
            return target
        return reverse("admin:index")

    def login(self, request, extra_context=None):
        """One login page — the app's. A signed-in GP gets a 403 rather
        than a loop through a login form that would sign them in again."""
        if request.user.is_authenticated:
            if self.has_permission(request):
                return HttpResponseRedirect(self._safe_next(request))
            return HttpResponseForbidden("This account is not a rota admin.")
        return redirect_to_login(self._safe_next(request), settings.LOGIN_URL)

    def logout(self, request, extra_context=None):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        auth_logout(request)
        return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)


# ---- values settings.UNFOLD reaches by dotted path ------------------------

def favicon_32(request):
    return static("icons/favicon-32.png")


def apple_touch_icon(request):
    return static("icons/apple-touch-icon.png")


def style_fonts(request):
    return static("css/fonts.css")


def style_admin(request):
    return static("admin/rota-admin.css")


def script_theme_bridge(request):
    return static("admin/theme-bridge.js")


def navigation(request):
    """The sidebar. Filled in by the sidebar task."""
    return []
```

- [ ] **Step 5: Settings**

In `config/settings.py`, replace the first entry of `INSTALLED_APPS` so it begins:

```python
INSTALLED_APPS = [
    "unfold.apps.BasicAppConfig",   # the theme; Basic, so it does not replace admin.site
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "config.apps.RotaAdminConfig",  # django.contrib.admin with our site class
    "django.contrib.auth",
```

(everything after `django.contrib.auth` unchanged). After the `LOGOUT_REDIRECT_URL` line add:

```python
# The admin's chrome. Plain values and dotted paths only — unfold resolves
# the paths per request, so rota.admin_site is never imported here.
UNFOLD = {
    "SITE_TITLE": "Rota",
    "SITE_HEADER": "Practice Rota",
    "SITE_URL": "/rota/",
    "SITE_SYMBOL": "calendar_month",
    "SITE_FAVICONS": [
        {"rel": "icon", "sizes": "32x32", "type": "image/png",
         "href": "rota.admin_site.favicon_32"},
        {"rel": "apple-touch-icon", "sizes": "180x180", "type": "image/png",
         "href": "rota.admin_site.apple_touch_icon"},
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COMMAND": {"search_models": True, "show_history": False},
    "SIDEBAR": {
        "show_search": False,
        "show_all_applications": False,
        "navigation": "rota.admin_site.navigation",
    },
}
```

- [ ] **Step 6: Run the tests, then the suite**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py tests/test_security.py tests/test_bulk_pattern_admin.py tests/test_pattern_editor.py tests/test_breathe_admin.py tests/test_breathe_status.py tests/test_admin_colour.py -q` — all pass. The existing admin tests use `staff_client` (a superuser) and unfold renders the stock ModelAdmins inside its chrome, so they pass unchanged. If `test_breathe_status.py` fails because unfold's `change_list.html` lacks the `object-tools-items` block the old template extends, that is Task 11's port arriving early: report it and stop.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass; report the count.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config/apps.py rota/admin_site.py config/settings.py tests/test_admin_site.py tests/test_security.py
git commit -m "feat: unfold is the admin's chrome, and is_rota_admin opens the door

RotaAdminSite (an unfold site) is installed as Django's default site
through a custom AdminConfig, so every registration lands on it. One login
page — the app's; a signed-in GP gets 403, not a loop.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Rota admins hold every rota and accounts permission; the app links to the admin

**Files:**
- Create: `accounts/backends.py`
- Modify: `config/settings.py` (`AUTHENTICATION_BACKENDS`)
- Modify: `templates/base.html:31-34` and `:56-59`
- Test: `tests/test_admin_site.py`

**Interfaces:**
- Produces: `accounts.backends.RotaAdminBackend`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_site.py`:

```python
from datetime import date

from rota.models import ClosedDay


def test_a_rota_admin_can_open_and_change_rota_models(admin_client):
    assert admin_client.get("/admin/rota/clinician/").status_code == 200
    resp = admin_client.post("/admin/rota/closedday/add/",
                             {"day": "2026-12-25", "reason": "Christmas"})
    assert resp.status_code == 302
    assert ClosedDay.objects.filter(day=date(2026, 12, 25)).exists()


def test_a_rota_admin_can_open_login_accounts(admin_client):
    assert admin_client.get("/admin/accounts/user/").status_code == 200


@pytest.mark.parametrize("url", ["/admin/axes/accessattempt/", "/admin/auth/group/"])
def test_a_rota_admin_is_kept_out_of_system_tables(admin_client, staff_client, url):
    assert admin_client.get(url).status_code == 403
    assert staff_client.get(url).status_code == 200


def test_the_app_header_links_to_the_admin_for_rota_admins_only(admin_client, gp_client, gp_user):
    from rota.models import PracticeSettings
    from tests.factories import make_clinician
    PracticeSettings.load()
    make_clinician(user=gp_user)
    assert 'href="/admin/"' in admin_client.get("/rota/").content.decode()
    assert 'href="/admin/"' not in gp_client.get("/rota/").content.decode()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py -q`
Expected: the clinician changelist and closed-day POST fail (403 — no model permissions), the header test fails (no link).

- [ ] **Step 3: The backend**

Create `accounts/backends.py`:

```python
"""is_rota_admin is the one flag.

Django's admin asks `user.has_perm("rota.change_clinician")` for every page
and every save. A practice manager should never have to be granted those
one by one, so this backend answers yes to every permission on the two apps
the rota owns — and to nothing else, which keeps django-axes and auth
Groups for superusers. It authenticates nobody (BaseBackend.authenticate
returns None); axes and ModelBackend do that.
"""

from django.contrib.auth.backends import BaseBackend

ROTA_APPS = {"rota", "accounts"}


def _is_rota_admin(user):
    return bool(user.is_active and getattr(user, "is_rota_admin", False))


class RotaAdminBackend(BaseBackend):
    def has_perm(self, user_obj, perm, obj=None):
        return _is_rota_admin(user_obj) and perm.split(".", 1)[0] in ROTA_APPS

    def has_module_perms(self, user_obj, app_label):
        return _is_rota_admin(user_obj) and app_label in ROTA_APPS
```

In `config/settings.py`, `AUTHENTICATION_BACKENDS` becomes:

```python
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "accounts.backends.RotaAdminBackend",
]
```

(keep any comment already there.)

- [ ] **Step 4: The Admin link**

In `templates/base.html`, inside the desktop `{% if user.is_rota_admin %}` block after the Assisted fill link, add:

```html
    <a href="/admin/" class="nav-link">Admin</a>
```

and inside the phone sheet's `{% if user.is_rota_admin %}` block after Assisted fill:

```html
        <a href="/admin/" class="tabbar-link">Admin</a>
```

- [ ] **Step 5: Run the tests, then the suite, then commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py tests/test_security.py tests/test_template_hygiene.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add accounts/backends.py config/settings.py templates/base.html tests/test_admin_site.py
git commit -m "feat: a rota admin holds every rota and accounts permission

One flag instead of a permission matrix: RotaAdminBackend grants rota
admins everything on the two apps the rota owns and nothing else, so
axes and auth Groups stay with superusers. The app's header links to
the admin.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Colours from the tokens, the app's font, and a theme bridge

**Files:**
- Create: `rota/admin_theme.py`
- Create: `static/admin/rota-admin.css`, `static/admin/theme-bridge.js`
- Modify: `config/settings.py` (`UNFOLD` gains `COLORS`, `STYLES`, `SCRIPTS`)
- Test: `tests/test_admin_theme.py` (new)

**Interfaces:**
- Consumes: `rota.palette.srgb_to_oklch(hex) -> (L, C, H)` (L 0–1, H degrees), `palette.oklch_to_hex(L, C, H) -> "#rrggbb"`, `palette.contrast_ratio(hex_a, hex_b) -> float`.
- Produces: `rota.admin_theme.token(name) -> str`, `primary(request=None) -> dict[str, str]`, `base(request=None) -> dict[str, str]` — eleven shades `"50"`…`"950"` each, hex strings (unfold's `convert_color` accepts hex).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_theme.py`:

```python
"""The admin wears the app's colours, derived — never typed.

Unfold wants two eleven-shade scales. `primary` is generated around
--accent so shade 600 IS the accent; `base` is anchored on the app's
neutrals. Both are asserted AA on the roles unfold uses them for, in both
themes (unfold's dark chrome uses base-900 as its ground).
"""

import re
from pathlib import Path

import pytest

from rota import palette
from rota.admin_theme import base, primary, token

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]


def test_primary_600_is_the_accent():
    assert primary()["600"].lower() == token("--accent").lower()


@pytest.mark.parametrize("scale", [primary, base])
def test_each_scale_has_eleven_shades_getting_darker(scale):
    s = scale()
    assert list(s) == WEIGHTS
    lightness = [palette.srgb_to_oklch(s[w])[0] for w in WEIGHTS]
    assert lightness == sorted(lightness, reverse=True), "shades must darken with weight"


def test_base_anchors_are_the_apps_neutrals():
    s = base()
    assert s["50"].lower() == token("--ground").lower()
    assert s["900"].lower() == token("--ink").lower()
    assert s["500"].lower() == token("--muted").lower()


def test_text_and_button_roles_clear_aa_in_the_light_theme():
    p, b = primary(), base()
    assert palette.contrast_ratio("#FFFFFF", p["600"]) >= 4.5, "white on a primary button"
    assert palette.contrast_ratio(b["700"], b["50"]) >= 4.5, "default text on the ground"
    assert palette.contrast_ratio(b["900"], "#FFFFFF") >= 7, "important text on a card"


def test_text_roles_clear_aa_in_the_dark_theme():
    b = base()
    assert palette.contrast_ratio(b["300"], b["900"]) >= 4.5, "default text on the dark ground"
    assert palette.contrast_ratio(b["100"], b["900"]) >= 7, "important text on the dark ground"


def test_the_admin_stylesheet_carries_no_colour_literals():
    css = (ROOT / "static" / "admin" / "rota-admin.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", css)


def test_the_theme_bridge_names_both_keys_and_guards_storage():
    js = (ROOT / "static" / "admin" / "theme-bridge.js").read_text()
    assert '"rota-theme"' in js and '"adminTheme"' in js
    assert "try" in js and "catch" in js


@pytest.mark.django_db
def test_the_admin_page_carries_the_derived_colours_and_the_apps_font(admin_client):
    html = admin_client.get("/admin/").content.decode()
    assert "--color-primary-600" in html
    assert "fonts.css" in html and "rota-admin.css" in html and "theme-bridge.js" in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_theme.py -q`
Expected: `ImportError` on `rota.admin_theme`.

- [ ] **Step 3: The scales**

Create `rota/admin_theme.py`:

```python
"""The admin's colour scales, derived from the app's tokens.

Unfold takes two eleven-shade scales. Typing them would be a second palette
that drifts from the first, so both are computed: `primary` around
--accent (shade 600 is the accent itself; lighter shades are tinted
grounds, darker ones pressed states), `base` anchored on the app's
neutrals with the gaps interpolated in OKLCH. Read from tokens.css the way
scripts/make_icons.py reads it. Hex out — unfold converts.

Unfold has ONE base scale for both themes and uses base-900 as its dark
ground, so the dark-theme text roles reference the light scale's dark
end rather than a second scale (a narrowing of the spec, recorded here).
"""

import re
from pathlib import Path

from rota import palette

TOKENS = Path(__file__).resolve().parents[1] / "static" / "css" / "tokens.css"


def token(name):
    """A hex custom property from the light :root block of tokens.css."""
    css = TOKENS.read_text()
    light = css[css.index(":root {"):css.index("@media")]
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})", light)
    if not match:
        raise LookupError(f"{name} is not in the light :root block of tokens.css")
    return match.group(1)


# Lightness per shade, and how much of the accent's chroma each keeps: the
# ends of the scale are grounds and near-blacks, which want less colour.
_PRIMARY_L = {"50": .97, "100": .94, "200": .88, "300": .79, "400": .68,
              "500": .56, "700": .36, "800": .30, "900": .245, "950": .17}
_PRIMARY_C = {"50": .25, "100": .35, "200": .50, "300": .70, "400": .90,
              "500": 1.0, "700": .95, "800": .85, "900": .70, "950": .55}

_BASE_ANCHORS = {"50": "--ground", "100": "--sunken", "200": "--hairline",
                 "400": "--field-border", "500": "--muted",
                 "700": "--ink-soft", "900": "--ink"}


def _ordered(scale):
    return {w: scale[w] for w in sorted(scale, key=int)}


def primary(request=None):
    accent = token("--accent")
    _, chroma, hue = palette.srgb_to_oklch(accent)
    scale = {w: palette.oklch_to_hex(_PRIMARY_L[w], chroma * _PRIMARY_C[w], hue)
             for w in _PRIMARY_L}
    scale["600"] = accent
    return _ordered(scale)


def _between(a_hex, b_hex):
    la, ca, ha = palette.srgb_to_oklch(a_hex)
    lb, cb, hb = palette.srgb_to_oklch(b_hex)
    return palette.oklch_to_hex((la + lb) / 2, (ca + cb) / 2, (ha + hb) / 2)


def base(request=None):
    scale = {w: token(name) for w, name in _BASE_ANCHORS.items()}
    scale["300"] = _between(scale["200"], scale["400"])
    scale["600"] = _between(scale["500"], scale["700"])
    scale["800"] = _between(scale["700"], scale["900"])
    l, c, h = palette.srgb_to_oklch(scale["900"])
    scale["950"] = palette.oklch_to_hex(max(l - 0.06, 0.0), c, h)
    return _ordered(scale)
```

If `test_each_scale_has_eleven_shades_getting_darker` fails on `base` because two anchors are out of order (for example `--hairline` lighter than `--sunken`), adjust only the interpolated shades, never the anchors — and report which pair, because that is a fact about the tokens.

- [ ] **Step 4: The stylesheet and the bridge**

Create `static/admin/rota-admin.css`:

```css
/* The admin's font is the app's. No colour lives here: the admin's scales
   come from settings.UNFOLD["COLORS"], derived from tokens.css by
   rota/admin_theme.py, and unfold writes them as --color-* variables. */
:root {
  --font-sans: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif;
}
```

Create `static/admin/theme-bridge.js`:

```js
/* Keeps two theme choices in agreement: the app's (localStorage
   "rota-theme": system|light|dark, written by static/js/theme.js) and
   unfold's ("adminTheme": a JSON-encoded "auto"|"light"|"dark", written by
   its Alpine store). On load the app's choice seeds unfold's if unfold has
   none; afterwards unfold's toggle writes back to the app's key. Every
   storage access is guarded: a private window breaks nothing. */
(function () {
  var APP = "rota-theme", ADMIN = "adminTheme";
  var toAdmin = { system: "auto", light: "light", dark: "dark" };
  var toApp = { auto: "system", light: "light", dark: "dark" };
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* not persisted */ } }

  var app = get(APP);
  if (app && toAdmin[app] && get(ADMIN) === null) {
    set(ADMIN, JSON.stringify(toAdmin[app]));
  }

  var last = get(ADMIN);
  setInterval(function () {
    var now = get(ADMIN);
    if (now === last) { return; }
    last = now;
    try {
      var v = JSON.parse(now);
      if (toApp[v]) { set(APP, toApp[v]); }
    } catch (e) { /* not a value we wrote or read */ }
  }, 1000);
})();
```

- [ ] **Step 5: Settings**

Add to `UNFOLD` in `config/settings.py`:

```python
    "COLORS": {
        "primary": "rota.admin_theme.primary",
        "base": "rota.admin_theme.base",
        "font": {
            "subtle-light": "var(--color-base-500)",
            "subtle-dark": "var(--color-base-400)",
            "default-light": "var(--color-base-700)",
            "default-dark": "var(--color-base-300)",
            "important-light": "var(--color-base-900)",
            "important-dark": "var(--color-base-100)",
        },
    },
    "STYLES": ["rota.admin_site.style_fonts", "rota.admin_site.style_admin"],
    "SCRIPTS": ["rota.admin_site.script_theme_bridge"],
```

- [ ] **Step 6: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_theme.py tests/test_admin_site.py tests/test_chrome_contrast.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_theme.py static/admin/rota-admin.css static/admin/theme-bridge.js config/settings.py tests/test_admin_theme.py
git commit -m "feat: the admin wears the app's colours and font

Two eleven-shade scales derived from tokens.css — primary-600 is
--accent, base is anchored on the neutrals — asserted AA on unfold's
text and button roles in both themes. Plus Jakarta Sans replaces Inter;
a ten-line bridge keeps the app's theme toggle and unfold's agreeing.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The sidebar, organised by job

**Files:**
- Modify: `rota/admin_site.py` (`navigation`, `settings_link`)
- Modify: `rota/admin.py` (register `TraineeProfile`)
- Test: `tests/test_admin_site.py`

**Interfaces:**
- Consumes: URL names `admin:rota_<model>_changelist`, `admin:rota_patternslot_bulk` (exists), `admin:accounts_user_changelist`, `admin:auth_group_changelist`, `admin:axes_accessattempt_changelist`, `admin:axes_accessfailurelog_changelist`, `admin:axes_accesslog_changelist`.
- Produces: `navigation(request) -> list[dict]`; `settings_link(request) -> str`; `TraineeProfileAdmin` registered. Task 11 re-points the "Sync status" link from the changelist to its status page.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_site.py`:

```python
GROUPS = ["People", "Working patterns", "Calendar", "Sessions & rules",
          "Leave from Breathe", "Practice settings", "Records"]


def test_a_rota_admin_sees_the_eight_groups_and_not_system(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    for group in GROUPS:
        assert group in html, group
    assert "Login accounts" in html and "Audit log" in html
    assert "System" not in html and "Access attempts" not in html


def test_a_superuser_sees_system_too(staff_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = staff_client.get("/admin/").content.decode()
    assert "System" in html and "Access attempts" in html and "Auth groups" in html


def test_every_sidebar_link_resolves(staff_client, rf, staff_user):
    from rota.admin_site import navigation
    from rota.models import PracticeSettings
    PracticeSettings.load()
    request = rf.get("/admin/")
    request.user = staff_user
    for group in navigation(request):
        for item in group["items"]:
            link = item["link"]
            url = link(request) if callable(link) else str(link)
            assert staff_client.get(url).status_code == 200, (group["title"], item["title"], url)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py -q -k "groups or system or sidebar_link"`
Expected: FAIL — the navigation is empty.

- [ ] **Step 3: Register trainee profiles**

In `rota/admin.py`, after `TraineeStageRuleAdmin`, add:

```python
@admin.register(TraineeProfile)
class TraineeProfileAdmin(admin.ModelAdmin):
    list_display = ("clinician", "stage", "wte_percent", "trainer",
                    "placement_start", "placement_end")
    list_filter = ("stage",)
    search_fields = ("clinician__name",)
```

- [ ] **Step 4: The navigation**

In `rota/admin_site.py`, replace the placeholder `navigation` with:

```python
def settings_link(request):
    """The singleton's own change form — no changelist of one row."""
    from rota.models import PracticeSettings
    return reverse("admin:rota_practicesettings_change",
                   args=[PracticeSettings.load().pk])


def _item(title, icon, link, permission=is_rota_admin):
    return {"title": title, "icon": icon, "link": link, "permission": permission}


def navigation(request):
    """The sidebar, one group per job. Groups carry no permission of their
    own in unfold's schema, so System is left out of the list entirely
    unless the user is a superuser — an empty heading is worse than none."""
    from django.urls import reverse_lazy as rl
    groups = [
        {"title": "Dashboard", "separator": False, "items": [
            _item("Dashboard", "dashboard", rl("admin:index"))]},
        {"title": "People", "separator": True, "items": [
            _item("Clinicians", "badge", rl("admin:rota_clinician_changelist")),
            _item("Clinician groups", "groups", rl("admin:rota_cliniciangroup_changelist")),
            _item("Login accounts", "manage_accounts", rl("admin:accounts_user_changelist"))]},
        {"title": "Working patterns", "separator": True, "items": [
            _item("Pattern editor", "edit_calendar", rl("admin:rota_patternslot_bulk")),
            _item("Recurring commitments", "event_repeat", rl("admin:rota_recurringcommitment_changelist")),
            _item("Trainee profiles", "school", rl("admin:rota_traineeprofile_changelist"))]},
        {"title": "Calendar", "separator": True, "items": [
            _item("Closed days", "event_busy", rl("admin:rota_closedday_changelist")),
            _item("Day notes", "sticky_note_2", rl("admin:rota_daynote_changelist"))]},
        {"title": "Sessions & rules", "separator": True, "items": [
            _item("Session types", "category", rl("admin:rota_sessiontype_changelist")),
            _item("Coverage rules", "rule", rl("admin:rota_coveragerule_changelist")),
            _item("Trainee stage rules", "menu_book", rl("admin:rota_traineestagerule_changelist")),
            _item("Sites", "location_on", rl("admin:rota_site_changelist"))]},
        {"title": "Leave from Breathe", "separator": True, "items": [
            _item("Sync status", "sync", rl("admin:rota_breathesyncrun_changelist")),
            _item("Leave mapping", "swap_horiz", rl("admin:rota_breatheleavemapping_changelist")),
            _item("Absences", "sick", rl("admin:rota_breatheabsence_changelist"))]},
        {"title": "Practice settings", "separator": True, "items": [
            _item("Practice settings", "settings", settings_link)]},
        {"title": "Records", "separator": True, "items": [
            _item("Rota entries", "calendar_view_week", rl("admin:rota_rotaentry_changelist")),
            _item("Audit log", "history", rl("admin:rota_rotaentrylog_changelist")),
            _item("Locum requirements", "person_search", rl("admin:rota_locumrequirement_changelist")),
            _item("Swap requests", "swap_calls", rl("admin:rota_swaprequest_changelist"))]},
    ]
    if is_superuser(request):
        groups.append({"title": "System", "separator": True, "items": [
            _item("Auth groups", "shield", rl("admin:auth_group_changelist"), is_superuser),
            _item("Access attempts", "lock", rl("admin:axes_accessattempt_changelist"), is_superuser),
            _item("Access failures", "lock_open", rl("admin:axes_accessfailurelog_changelist"), is_superuser),
            _item("Access logs", "receipt_long", rl("admin:axes_accesslog_changelist"), is_superuser)]})
    return groups
```

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_site.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_site.py rota/admin.py tests/test_admin_site.py
git commit -m "feat: the admin sidebar is organised by job

Eight groups a practice manager would name, a ninth for superusers, the
command palette on. Trainee profiles get a registration so their item
resolves.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Checkbox lists and a swatch picker unfold can render

**Files:**
- Create: `rota/admin_forms.py`
- Modify: `rota/admin_widgets.py:22-49` (`TintSwatchSelect`)
- Test: `tests/test_admin_widgets.py` (new); `tests/test_admin_colour.py` (unchanged, must pass)

**Interfaces:**
- Produces: `rota.admin_forms.WEEKDAYS`, `MONTHS` (lists of `(int, label)`); `IntListCheckboxField(choices, ordered=False)` — a form field whose cleaned value is the comma-joined string the models store; `OrderedCheckboxSelect`; `CoverageRuleForm`, `PracticeSettingsForm` (ModelForms). Task 8 wires them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_widgets.py`:

```python
"""Free-text lists of numbers become checkboxes; the stored string is the
same, so every reader (rota/services/ranges.py) is untouched."""

import pytest
from django import forms

from rota.admin_forms import (MONTHS, WEEKDAYS, IntListCheckboxField,
                              CoverageRuleForm, PracticeSettingsForm)


class WeekdayForm(forms.Form):
    days = IntListCheckboxField(choices=WEEKDAYS)


class OrderedForm(forms.Form):
    days = IntListCheckboxField(choices=WEEKDAYS, ordered=True)


def test_checked_boxes_become_the_stored_string():
    f = WeekdayForm({"days": ["0", "1", "4"]})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["days"] == "0,1,4"


def test_nothing_ticked_is_an_empty_string():
    f = WeekdayForm({})
    assert f.is_valid()
    assert f.cleaned_data["days"] == ""


def test_the_stored_string_pre_ticks_the_boxes():
    f = WeekdayForm(initial={"days": "0,1,2,3,4"})
    html = f.as_p()
    assert html.count("checked") == 5


def test_a_value_outside_the_choices_is_refused():
    assert not WeekdayForm({"days": ["9"]}).is_valid()


def test_an_ordered_field_keeps_the_order_the_user_gave():
    f = OrderedForm({"days": ["3", "1"], "days_order_3": "1", "days_order_1": "2"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["days"] == "3,1"
    f = OrderedForm({"days": ["3", "1"], "days_order_3": "2", "days_order_1": "1"})
    assert f.is_valid()
    assert f.cleaned_data["days"] == "1,3"


def test_has_changed_compares_against_the_stored_string():
    f = WeekdayForm({"days": ["0", "1"]}, initial={"days": "0,1"})
    assert not f.has_changed()
    f = WeekdayForm({"days": ["0"]}, initial={"days": "0,1"})
    assert f.has_changed()


@pytest.mark.django_db
def test_the_coverage_rule_form_round_trips_through_the_model():
    from rota.models import CoverageRule
    from tests.factories import make_session_type
    st = make_session_type("Duty")
    f = CoverageRuleForm({"session_type": st.pk, "unit": "SESSION", "frequency": "WEEK",
                          "count": 2, "priority": 5, "parts": "BOTH",
                          "weekdays": ["1", "3"], "months": [],
                          "preferred_weekdays": ["3", "1"],
                          "preferred_weekdays_order_3": "1", "preferred_weekdays_order_1": "2"})
    assert f.is_valid(), f.errors
    rule = f.save()
    rule.refresh_from_db()
    assert (rule.weekdays, rule.months, rule.preferred_weekdays) == ("1,3", "", "3,1")
    assert rule.preferred_weekday_list() == [3, 1]


@pytest.mark.django_db
def test_the_settings_form_accepts_no_days_as_today_does():
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    f = PracticeSettingsForm({"min_clinical_per_session": 2, "open_weekdays": []}, instance=s)
    assert f.is_valid(), f.errors
    assert f.cleaned_data["open_weekdays"] == ""


def test_month_choices_are_january_to_december():
    assert MONTHS[0] == (1, "January") and MONTHS[-1] == (12, "December")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_widgets.py -q`
Expected: `ImportError` on `rota.admin_forms`.

- [ ] **Step 3: The field and forms**

Create `rota/admin_forms.py`:

```python
"""Form fields for the admin that present a stored list of integers as
checkboxes and store it back as the same comma-joined string.

PracticeSettings.open_weekdays and CoverageRule.weekdays / months /
preferred_weekdays are CharFields like "0,1,2,3,4", parsed by
rota/services/ranges.py. Nothing about storage changes here; the commonest
setup mistake — a stray comma — simply cannot be made from a checkbox.
"""

from django import forms

from rota.models import CoverageRule, PracticeSettings

WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
            (4, "Friday"), (5, "Saturday"), (6, "Sunday")]
MONTHS = [(1, "January"), (2, "February"), (3, "March"), (4, "April"),
          (5, "May"), (6, "June"), (7, "July"), (8, "August"),
          (9, "September"), (10, "October"), (11, "November"), (12, "December")]


class OrderedCheckboxSelect(forms.CheckboxSelectMultiple):
    """Checkboxes plus a small order number beside each, for the one field
    whose stored order is significant (preferred_weekdays: "3,1" means
    Thursday first, then Tuesday). Submits `<name>` for the ticks and
    `<name>_order_<value>` for the numbers; the field sorts by number."""
    template_name = "admin/rota/widgets/ordered_checkboxes.html"

    def value_from_datadict(self, data, files, name):
        ticked = data.getlist(name) if hasattr(data, "getlist") else data.get(name, [])
        def order(v):
            raw = data.get(f"{name}_order_{v}", "")
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 10 ** 6
        return sorted(ticked, key=order)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        current = [str(v) for v in (value or [])]
        context["widget"]["order"] = {v: i + 1 for i, v in enumerate(current)}
        return context


class IntListCheckboxField(forms.MultipleChoiceField):
    def __init__(self, *, choices, ordered=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", OrderedCheckboxSelect if ordered
                          else forms.CheckboxSelectMultiple)
        super().__init__(choices=[(str(v), label) for v, label in choices], **kwargs)

    @staticmethod
    def _split(value):
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return list(value or [])

    def prepare_value(self, value):
        return self._split(value)

    def clean(self, value):
        return ",".join(super().clean(value))

    def has_changed(self, initial, data):
        return self.clean(data) != ",".join(self._split(initial))


class CoverageRuleForm(forms.ModelForm):
    weekdays = IntListCheckboxField(choices=WEEKDAYS, label="Weekdays")
    months = IntListCheckboxField(choices=MONTHS, label="Months",
                                  help_text="None ticked means all year.")
    preferred_weekdays = IntListCheckboxField(
        choices=WEEKDAYS, ordered=True, label="Preferred weekdays",
        help_text="For per-week and per-month rules: tick the days to try "
                  "first, numbered in order of preference.")

    class Meta:
        model = CoverageRule
        fields = "__all__"


class PracticeSettingsForm(forms.ModelForm):
    open_weekdays = IntListCheckboxField(choices=WEEKDAYS, label="Open weekdays")

    class Meta:
        model = PracticeSettings
        fields = "__all__"
```

Create `templates/admin/rota/widgets/ordered_checkboxes.html`:

```html
{% for group, options, index in widget.optgroups %}{% for option in options %}
<label class="flex items-center gap-2 py-1">
  <input type="checkbox" name="{{ widget.name }}" value="{{ option.value }}"{% if option.selected %} checked{% endif %}>
  <span class="grow">{{ option.label }}</span>
  <input type="number" name="{{ widget.name }}_order_{{ option.value }}" min="1" max="7" class="w-14" aria-label="Order for {{ option.label }}"
         value="{{ widget.order|dict_get:option.value|default_if_none:'' }}">
</label>
{% endfor %}{% endfor %}
```

The `dict_get` filter does not exist yet: add `rota/templatetags/admin_extras.py` with

```python
from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    return (d or {}).get(str(key))
```

and `{% load admin_extras %}` as the template's first line (create `rota/templatetags/__init__.py` if absent). The model's `validate_int_list` still runs on save, so the "1..7" hints are convenience, not the validator.

- [ ] **Step 4: The swatch picker**

In `rota/admin_widgets.py`, replace `TintSwatchSelect.render` with markup unfold's form layout can hold — the same inputs, the same palette colours, plus the chosen tint shown large:

```python
class TintSwatchSelect(RadioSelect):
    """Radio inputs painted in the tint each one selects, and the chosen one
    shown large. Colours are inline because there are 42 of them and they
    come from rota.palette, not from a stylesheet."""

    def render(self, name, value, attrs=None, renderer=None):
        chosen = palette.TINTS.get(value)
        preview = ""
        if chosen:
            preview = format_html(
                '<div class="mb-3 inline-block rounded-default px-4 py-2 font-semibold" '
                'style="background:{}; color:{}">{}</div>',
                chosen.bg, chosen.fg, chosen.label)
        rows = format_html_join(
            "\n",
            '<label class="inline-block cursor-pointer rounded-default px-2 py-1 text-xs '
            'font-semibold" style="background:{}; color:{}; outline:{}">'
            '<input type="radio" name="{}" value="{}"{}> {}</label>',
            (
                (tint.bg, tint.fg,
                 "2px solid currentColor" if key == value else "none",
                 name, key,
                 mark_safe(" checked") if key == value else "",
                 tint.label)
                for key, tint in palette.TINTS.items()
            ),
        )
        return format_html(
            '<div>{}<div class="flex flex-wrap gap-1" style="max-width:52em">{}</div></div>',
            preview, rows)
```

`tests/test_admin_colour.py` keeps every assertion: one `name="colour"` per tint, the tint's `bg`/`fg` present, `value="amber-soft" checked`, the save round-trip, and no hex literal in the widget source.

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_widgets.py tests/test_admin_colour.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_forms.py rota/admin_widgets.py rota/templatetags templates/admin/rota/widgets/ordered_checkboxes.html tests/test_admin_widgets.py
git commit -m "feat: weekday and month lists are checkboxes; the swatch picker fits unfold

The stored strings and their parser are untouched; a stray comma can no
longer be typed. Preferred weekdays keep their order through a number
beside each box.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: The People batch — clinicians, groups, trainee profiles, login accounts

**Files:**
- Modify: `rota/admin.py` (`ClinicianGroupAdmin`, `TraineeProfileInline`, `ClinicianAdmin`, `TraineeProfileAdmin`; new `RecurringCommitmentInline`)
- Modify: `accounts/admin.py`
- Test: `tests/test_admin_models.py` (new); `tests/test_breathe_admin.py` (unchanged, must pass)

**Interfaces:**
- Consumes: `unfold.admin.ModelAdmin`, `StackedInline`, `TabularInline`; `rota.services.patterns.current_pattern` is NOT used for the list (it queries per call) — the summary is computed from prefetched rows.
- Produces: `rota.admin.pattern_text(rows, today) -> str` (module-level helper; Task 12 reuses the "no pattern" rule through the queryset, not this).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_models.py`:

```python
"""The model admins, rebuilt: fieldsets with the docs' sentences, search,
inlines, and a clinician page that says what pattern someone works."""

from datetime import date

import pytest

from rota.models import PatternSlot
from tests.factories import (make_clinician, make_group, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _change(client, obj):
    opts = obj._meta
    return client.get(f"/admin/{opts.app_label}/{opts.model_name}/{obj.pk}/change/").content.decode()


# ------------------------------------------------------------ clinicians ---

def test_the_clinician_page_has_the_four_fieldsets_and_two_inlines(admin_client):
    c = make_clinician("Ann Able")
    html = _change(admin_client, c)
    for title in ("Who", "Availability", "Roles", "Leave from Breathe"):
        assert title in html, title
    assert "Trainee profile" in html and "Recurring commitment" in html


def test_the_clinician_page_summarises_the_pattern_in_force(admin_client):
    c = make_clinician("Pat Tern")
    make_pattern(c, weekdays=(0, 3), parts=("AM", "PM"), effective_from=date(2025, 9, 1))
    PatternSlot.objects.create(clinician=c, weekday=1, part="AM", works=True,
                               effective_from=date(2025, 9, 1))
    html = _change(admin_client, c)
    assert "Mon AM/PM · Tue AM · Thu AM/PM" in html
    assert "since 1 Sep 2025" in html
    assert "/admin/rota/patternslot/bulk/?clinician_id=" in html


def test_a_clinician_without_a_pattern_says_so_in_the_list(admin_client):
    make_clinician("No Pattern")
    html = admin_client.get("/admin/rota/clinician/").content.decode()
    assert "No pattern yet" in html


def test_the_pattern_column_costs_no_query_per_clinician(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def add(n):
        for i in range(n):
            make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))

    add(2)
    admin_client.get("/admin/rota/clinician/")
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/rota/clinician/")
    baseline = len(ctx)
    add(8)
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/rota/clinician/")
    assert len(ctx) == baseline


def test_clinician_search_finds_by_name_initials_and_email(admin_client, gp_user):
    make_clinician("Alice Adams", user=gp_user)
    make_clinician("Bob Baker")
    for q in ("Alice", "AA", "gp@example.com"):
        html = admin_client.get(f"/admin/rota/clinician/?q={q}").content.decode()
        assert "Alice Adams" in html and "Bob Baker" not in html, q


def test_the_deactivate_action_and_deletion_guard_survive(admin_client):
    from tests.factories import make_entry
    c = make_clinician("Guarded")
    make_entry(c, is_published=True)
    resp = admin_client.get(f"/admin/rota/clinician/{c.pk}/delete/")
    assert "Deactivate this clinician instead" in resp.content.decode()
    resp = admin_client.post("/admin/rota/clinician/", {
        "action": "deactivate_clinicians", "_selected_action": [c.pk]}, follow=True)
    c.refresh_from_db()
    assert not c.active


# ----------------------------------------------------- groups & trainees ---

def test_group_order_and_minimum_are_editable_in_the_list(admin_client):
    make_group("Partners")
    html = admin_client.get("/admin/rota/cliniciangroup/").content.decode()
    assert 'name="form-0-display_order"' in html and 'name="form-0-min_per_session"' in html


def test_trainee_profiles_list_and_search(admin_client):
    from tests.factories import make_trainee
    t = make_trainee(make_clinician("Terry Trainee"))
    html = admin_client.get("/admin/rota/traineeprofile/?q=Terry").content.decode()
    assert "Terry Trainee" in html and t.stage in html


# --------------------------------------------------------- login accounts ---

def test_a_rota_admin_edits_accounts_without_the_system_fieldset(admin_client, gp_user, staff_client):
    make_clinician("Gwen Peters", user=gp_user)
    html = _change(admin_client, gp_user)
    assert "Rota admin" in html or "is_rota_admin" in html
    assert "Gwen Peters" in html, "the linked clinician is shown"
    assert 'name="is_superuser"' not in html
    assert 'name="is_superuser"' in _change(staff_client, gp_user)


def test_an_account_can_be_added_through_unfolds_form(admin_client):
    resp = admin_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com", "password1": "correct-horse-battery",
        "password2": "correct-horse-battery", "is_rota_admin": "on"}, follow=True)
    assert resp.status_code == 200
    from accounts.models import User
    assert User.objects.get(email="new@example.com").is_rota_admin
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py -q`
Expected: FAIL on fieldset titles, the pattern summary, "No pattern yet", the editable list, the account fieldsets.

- [ ] **Step 3: Clinicians, groups, trainees**

In `rota/admin.py`, change the imports: add `from unfold.admin import ModelAdmin, StackedInline, TabularInline` and `from unfold.decorators import display`; import `RecurringCommitment` is already there. Then:

```python
WEEKDAY_ABBR = [d[:3] for d in WEEKDAY_LABELS]


def pattern_text(rows, today):
    """'Mon AM/PM · Tue AM — since 1 Sep 2025' from a clinician's pattern
    rows, applying the in-force rule (latest effective_from on or before
    today wins per weekday/part) in Python so a list page costs no query
    per row. 'No pattern yet' when nothing is in force."""
    in_force = {}
    since = None
    for row in rows:
        if row.effective_from > today:
            continue
        key = (row.weekday, row.part)
        if key not in in_force or row.effective_from >= in_force[key].effective_from:
            in_force[key] = row
        if since is None or row.effective_from > since:
            since = row.effective_from
    worked = {}
    for (weekday, part), row in in_force.items():
        if row.works:
            worked.setdefault(weekday, []).append(part)
    if not worked:
        return "No pattern yet"
    days = " · ".join(
        f"{WEEKDAY_ABBR[wd]} {'/'.join(sorted(parts, key=('AM', 'PM').index))}"
        for wd, parts in sorted(worked.items()))
    return f"{days} — since {since.strftime('%-d %b %Y')}"


@admin.register(ClinicianGroup)
class ClinicianGroupAdmin(ModelAdmin):
    list_display = ("name", "display_order", "min_per_session", "is_locum_group")
    list_editable = ("display_order", "min_per_session")
    search_fields = ("name",)
    fieldsets = (
        (None, {
            "fields": ("name", "display_order"),
            "description": "Groups order the grid and drive a staffing warning. "
                           "Lower display order appears first.",
        }),
        ("Staffing", {
            "fields": ("min_per_session", "is_locum_group"),
            "description": "Set a minimum to warn when fewer of this group are in. "
                           "Exactly one group is the locum group: its members appear "
                           "on the grid only in weeks they hold a session.",
        }),
    )


class TraineeProfileInline(StackedInline):
    model = TraineeProfile
    fk_name = "clinician"
    extra = 0
    verbose_name = "Trainee profile"
    verbose_name_plural = "Trainee profile"


class RecurringCommitmentInline(TabularInline):
    model = RecurringCommitment
    fk_name = "clinician"
    extra = 0
    fields = ("session_type", "weekday", "part", "site", "active_from",
              "active_until", "interval_weeks")
    verbose_name_plural = "Recurring commitments"
```

Replace `ClinicianAdmin`'s class line and the top of its body (everything down to `formfield_for_dbfield`) with:

```python
@admin.register(Clinician)
class ClinicianAdmin(ModelAdmin):
    list_display = ("name", "initials", "group", "active", "is_trainer",
                    "pattern_column", "breathe_link")
    list_filter = ("group", "active", "is_trainer", BreatheLinkedFilter)
    search_fields = ("name", "initials", "user__email")
    inlines = [TraineeProfileInline, RecurringCommitmentInline]
    actions = ["deactivate_clinicians"]
    readonly_fields = ("pattern_summary",)
    fieldsets = (
        ("Who", {
            "fields": ("name", "initials", "group", "user"),
            "description": "Initials are what the grid shows. Link the login "
                           "account so this person sees their own schedule.",
        }),
        ("Availability", {
            "fields": ("active", "start_date", "end_date", "pattern_summary"),
            "description": "Untick Active to take someone out of every eligibility "
                           "pool while keeping their history — the alternative to "
                           "deleting. Dates bound when they can be scheduled.",
        }),
        ("Roles", {"fields": ("is_trainer",)}),
        ("Leave from Breathe", {
            "fields": ("breathe_employee_id",),
            "description": "Leave is read from Breathe for linked clinicians only. "
                           "An unlinked clinician is treated as always available.",
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("group", "user") \
            .prefetch_related("pattern_slots")

    @admin.display(description="Pattern")
    def pattern_column(self, obj):
        text = pattern_text(obj.pattern_slots.all(), date.today())
        if text == "No pattern yet":
            return format_html('<span style="color: var(--color-primary-700)">{}</span>', text)
        return text

    @admin.display(description="Working pattern")
    def pattern_summary(self, obj):
        if obj.pk is None:
            return "Save the clinician first, then set their pattern."
        text = pattern_text(obj.pattern_slots.all(), date.today())
        url = reverse("admin:rota_patternslot_bulk")
        return format_html('{} &nbsp; <a href="{}?clinician_id={}">Edit pattern</a>',
                           text, url, obj.pk)
```

Keep every existing method of `ClinicianAdmin` below that point (`formfield_for_dbfield`, `get_form`, `breathe_link`, `deactivate_clinicians`, `get_deleted_objects`, `_format_protected`, `delete_model`, `delete_queryset`, `save_model`, `_entries_outside_window`) and delete the old `pattern_link` (the summary replaces it). Change `TraineeProfileAdmin`'s base to `ModelAdmin`.

- [ ] **Step 4: Login accounts**

Replace `accounts/admin.py`:

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.forms import (AdminPasswordChangeForm, UserChangeForm,
                          UserCreationForm)

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ("email",)
    list_display = ("email", "is_rota_admin", "is_active", "clinician_name")
    list_filter = ("is_rota_admin", "is_active")
    search_fields = ("email",)
    readonly_fields = ("clinician_name",)
    add_fieldsets = (
        (None, {"fields": ("email", "password1", "password2", "is_rota_admin")}),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        sets = [
            ("Account", {"fields": ("email", "password")}),
            ("Rota", {
                "fields": ("is_rota_admin", "clinician_name"),
                "description": "A rota admin can publish weeks, run the fill, and "
                               "use this admin. Link a clinician on their record "
                               "under People › Clinicians.",
            }),
        ]
        if request.user.is_superuser:
            sets.append(("System", {"fields": ("is_active", "is_staff", "is_superuser")}))
        else:
            sets.append(("Status", {"fields": ("is_active",)}))
        return sets

    @admin.display(description="Clinician")
    def clinician_name(self, obj):
        clinician = getattr(obj, "clinician", None)
        if clinician is None:
            return "—"
        return format_html('<a href="/admin/rota/clinician/{}/change/">{}</a>',
                           clinician.pk, clinician.name)
```

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py tests/test_breathe_admin.py tests/test_admin_site.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin.py accounts/admin.py tests/test_admin_models.py
git commit -m "feat: clinicians, groups, trainees and accounts on unfold, with the docs on the page

The clinician page carries its trainee profile and commitments inline
and says which pattern is in force; groups edit in the list; accounts
use unfold's forms and hide the System fieldset from non-superusers.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The words on the fields — help text and verbose names, in two migrations

**Files:**
- Modify: `rota/models/people.py`, `catalog.py`, `entries.py`, `trainees.py`, `commitments.py`, `requests.py`; `accounts/models.py`
- Create: `rota/migrations/0025_admin_copy.py`, `accounts/migrations/000N_login_account_names.py` (generated)
- Test: `tests/test_admin_models.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_models.py`:

```python
def test_the_models_read_as_a_manager_would_say_them():
    from accounts.models import User
    from rota.models import PracticeSettings, RotaEntry, RotaEntryLog, TraineeProfile
    assert str(PracticeSettings._meta.verbose_name_plural) == "practice settings"
    assert str(RotaEntry._meta.verbose_name_plural) == "rota entries"
    assert str(RotaEntryLog._meta.verbose_name_plural) == "audit log"
    assert str(TraineeProfile._meta.verbose_name_plural) == "trainee profiles"
    assert str(User._meta.verbose_name_plural) == "login accounts"


@pytest.mark.parametrize("model,field", [
    ("Clinician", "initials"), ("Clinician", "active"), ("ClinicianGroup", "is_locum_group"),
    ("SessionType", "code"), ("SessionType", "category"), ("SessionType", "fairness_tracked"),
    ("CoverageRule", "count"), ("CoverageRule", "weekdays"),
    ("PracticeSettings", "min_clinical_per_session"), ("PracticeSettings", "default_fill_session_type"),
    ("ClosedDay", "reason"), ("DayNote", "text"),
])
def test_every_field_a_manager_meets_explains_itself(model, field):
    from rota import models
    assert getattr(models, model)._meta.get_field(field).help_text, f"{model}.{field}"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py -q -k "manager or explains"`
Expected: FAIL.

- [ ] **Step 3: Add the words**

Add `help_text=` to these fields, verbatim:

| Model.field | help_text |
|---|---|
| `Clinician.name` | `"Full name, as it appears on the day view and reports."` |
| `Clinician.initials` | `"Up to five characters — what the week grid shows."` |
| `Clinician.group` | `"Orders the grid and drives the group staffing warning."` |
| `Clinician.user` | `"The login account for this clinician, if they have one."` |
| `Clinician.active` | `"Untick to remove someone from every eligibility pool while keeping their history — the alternative to deleting."` |
| `ClinicianGroup.name` | `"Partners, Salaried, GPST, Locums …"` |
| `ClinicianGroup.display_order` | `"Groups appear on the grid in this order, lowest first."` |
| `ClinicianGroup.is_locum_group` | `"Exactly one group: locums appear on the grid only in weeks they hold a session."` |
| `SessionType.name` | `"Shown in dropdowns and on the day view."` |
| `SessionType.code` | `"What the grid cell shows. Keep it short and unique."` |
| `SessionType.category` | `"Clinical counts toward minimum staffing; Absence marks someone as off."` |
| `SessionType.fairness_tracked` | `"Shared out pro-rata to contracted sessions and reported on the fairness report."` |
| `CoverageRule.session_type` | `"What must be covered."` |
| `CoverageRule.unit` | `"The shape of one placement: a session, a full day, or a full day if someone is free for both halves."` |
| `CoverageRule.frequency` | `"Per slot checks every session; per week and per month are quotas the fill engine spreads out."` |
| `CoverageRule.count` | `"How many placements per unit and frequency."` |
| `CoverageRule.weekdays` | `"Days this rule applies on."` |
| `PracticeSettings.min_clinical_per_session` | `"Warn on the grid when fewer clinical GPs are in for a session."` |
| `PracticeSettings.default_fill_session_type` | `"What assisted fill puts in any cell still empty after the rules, when you tick that box."` |
| `PracticeSettings.open_weekdays` | `"The days the surgery is open. The grid shows only these."` (replaces the existing text) |
| `PracticeSettings.vts_session_type`, `sdl_session_type`, `mentoring_session_type` | `"Leave blank to skip this trainee pass."` |
| `ClosedDay.day` | `"A bank holiday or closure. No sessions are expected and no warnings raised."` |
| `ClosedDay.reason` | `"Shown on the grid header."` |
| `DayNote.text` | `"Shown on the grid header and the day view, to everyone."` |
| `RecurringCommitment.weekday` | `"Monday=0"` stays; the admin form renders a weekday dropdown (Task 8). |
| `LocumRequirement.details` | `"Which agency, what rate, who you called."` |

Verbose names — add to each `class Meta` (creating one where absent, keeping existing `ordering`/`constraints`):

- `PracticeSettings`: `verbose_name = "practice settings"`, `verbose_name_plural = "practice settings"`
- `RotaEntry`: `verbose_name = "rota entry"`, `verbose_name_plural = "rota entries"`
- `RotaEntryLog`: `verbose_name = "audit log entry"`, `verbose_name_plural = "audit log"`
- `TraineeProfile`: `verbose_name = "trainee profile"`, `verbose_name_plural = "trainee profiles"`
- `accounts.User`: `class Meta(AbstractUser.Meta): verbose_name = "login account"; verbose_name_plural = "login accounts"`

- [ ] **Step 4: Generate the migrations**

Run: `/root/rota/.venv/bin/python manage.py makemigrations rota -n admin_copy` → `rota/migrations/0025_admin_copy.py`. Open it and confirm it holds only `AlterField` and `AlterModelOptions` operations.
Run: `/root/rota/.venv/bin/python manage.py makemigrations accounts -n login_account_names` → confirm one `AlterModelOptions`.
Run: `/root/rota/.venv/bin/python manage.py makemigrations --check` → `No changes detected`.

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/models accounts/models.py rota/migrations/0025_admin_copy.py accounts/migrations tests/test_admin_models.py
git commit -m "feat: every field a manager meets explains itself

Help text on the fields the reference docs used to carry, and model names
that read as a manager would say them. Two migrations, words only.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The Sessions & rules, Calendar and Practice settings batch

**Files:**
- Modify: `rota/admin.py` (`SessionTypeAdmin`, `CoverageRuleAdmin`, `TraineeStageRuleAdmin`, `RecurringCommitmentAdmin`, `PracticeSettingsAdmin`; new `SiteAdmin`, `ClosedDayAdmin`, `DayNoteAdmin`)
- Test: `tests/test_admin_models.py`; `tests/test_admin_colour.py` (unchanged)

**Interfaces:**
- Consumes: `rota.admin_forms.CoverageRuleForm`, `PracticeSettingsForm`, `WEEKDAYS` (Task 5); `unfold.contrib.filters.admin.RangeDateFilter`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_models.py`:

```python
# ------------------------------------------------------ sessions & rules ---

def test_the_session_type_page_has_its_fieldsets_and_the_large_swatch(admin_client):
    st = make_session_type("Duty", code="DUTY")
    html = _change(admin_client, st)
    for title in ("Identity", "Where it appears", "Fairness", "Who may do it", "Clashes"):
        assert title in html, title


def test_coverage_rules_render_checkboxes_and_save_the_same_string(admin_client):
    st = make_session_type("Duty")
    html = admin_client.get("/admin/rota/coveragerule/add/").content.decode()
    assert 'name="weekdays" value="0"' in html and 'name="months" value="12"' in html
    assert "worked example" in html.lower() or "Duty, per full day" in html
    resp = admin_client.post("/admin/rota/coveragerule/add/", {
        "session_type": st.pk, "unit": "DAY", "frequency": "SLOT", "count": 1,
        "priority": 1, "parts": "BOTH", "weekdays": ["0", "1", "2", "3", "4"]})
    assert resp.status_code == 302, resp.content.decode()[:500]
    from rota.models import CoverageRule
    assert CoverageRule.objects.get().weekdays == "0,1,2,3,4"


def test_stage_rules_edit_in_the_list_and_cannot_be_deleted(admin_client):
    from rota.models import TraineeStageRule
    rule = TraineeStageRule.objects.get(stage="ST1")
    html = admin_client.get("/admin/rota/traineestagerule/").content.decode()
    assert 'name="form-0-vts_per_week"' in html
    assert admin_client.get(f"/admin/rota/traineestagerule/{rule.pk}/delete/").status_code == 403


def test_a_commitment_offers_weekdays_by_name(admin_client):
    html = admin_client.get("/admin/rota/recurringcommitment/add/").content.decode()
    assert '<option value="3">Thursday</option>' in html


# --------------------------------------------------------------- calendar ---

def test_closed_days_have_a_date_hierarchy_and_search(admin_client):
    from rota.models import ClosedDay
    ClosedDay.objects.create(day=date(2026, 12, 25), reason="Christmas")
    html = admin_client.get("/admin/rota/closedday/").content.decode()
    assert "2026" in html and "Christmas" in html
    assert "Christmas" in admin_client.get("/admin/rota/closedday/?q=Christ").content.decode()


# ------------------------------------------------------- practice settings ---

def test_the_settings_changelist_opens_the_singleton(admin_client):
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    resp = admin_client.get("/admin/rota/practicesettings/")
    assert resp.status_code == 302
    assert resp["Location"].endswith(f"/admin/rota/practicesettings/{s.pk}/change/")


def test_settings_render_weekday_checkboxes_and_warn_on_no_days(admin_client):
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    html = _change(admin_client, s)
    assert 'name="open_weekdays" value="0"' in html and "Trainees" in html
    resp = admin_client.post(f"/admin/rota/practicesettings/{s.pk}/change/", {
        "min_clinical_per_session": 2, "open_weekdays": []}, follow=True)
    assert "open on no days" in resp.content.decode()
    s.refresh_from_db()
    assert s.open_weekdays == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py -q -k "session_type or coverage or stage_rules or commitment or closed or settings"`
Expected: FAIL.

- [ ] **Step 3: The admins**

In `rota/admin.py` add `from django import forms`, `from unfold.contrib.filters.admin import RangeDateFilter`, and `from .admin_forms import WEEKDAYS, CoverageRuleForm, PracticeSettingsForm`. Then replace the corresponding classes and the three bare `admin.site.register(...)` lines:

```python
@admin.register(SessionType)
class SessionTypeAdmin(ModelAdmin):
    list_display = ("name", "code", "category", "colour_swatch",
                    "fairness_tracked", "pin_on_day_view")
    list_filter = ("pin_on_day_view", "fairness_tracked", "category")
    search_fields = ("name", "code")
    filter_horizontal = ("allowed_clinicians", "allowed_groups", "blocks_same_day")
    readonly_fields = ("legacy_colour",)
    fieldsets = (
        ("Identity", {"fields": ("name", "code", "colour")}),
        ("Where it appears", {
            "fields": ("category", "pin_on_day_view", "default_site"),
            "description": "Pin the roles someone opens the day view to check — Duty "
                           "above all. Default site is stamped on entries the fill "
                           "engine creates.",
        }),
        ("Fairness", {"fields": ("fairness_tracked",)}),
        ("Who may do it", {
            "fields": ("allowed_clinicians", "allowed_groups"),
            "description": "Leave both empty and anyone may do it. Otherwise only the "
                           "named clinicians and groups are eligible.",
        }),
        ("Clashes", {
            "fields": ("blocks_same_day",),
            "description": "A clinician holding this type on a day is not "
                           "auto-assigned any of these the same day.",
        }),
        ("History", {"fields": ("legacy_colour",), "classes": ("collapse",)}),
    )
    # formfield_for_dbfield and colour_swatch: unchanged


@admin.register(CoverageRule)
class CoverageRuleAdmin(ModelAdmin):
    form = CoverageRuleForm
    list_display = ("session_type", "unit", "frequency", "parts", "weekdays",
                    "months", "count", "priority")
    list_editable = ("priority",)
    list_filter = ("session_type", "frequency", "unit")
    fieldsets = (
        ("What", {
            "fields": ("session_type", "unit", "frequency", "count"),
            "description": "A worked example: Duty, per full day, per slot, count 1, "
                           "priority 1 means one clinician holds Duty all day, every "
                           "open day, and this rule is filled before any other.",
        }),
        ("When", {"fields": ("parts", "weekdays", "months", "preferred_weekdays")}),
        ("Order", {
            "fields": ("priority",),
            "description": "Lower fills first. When two rules want the same person, "
                           "the lower number gets them.",
        }),
    )


@admin.register(TraineeStageRule)
class TraineeStageRuleAdmin(ModelAdmin):
    list_display = ("stage", "vts_per_week", "sdl_per_week",
                    "mentoring_per_week", "vts_weekday", "vts_part")
    list_editable = ("vts_per_week", "sdl_per_week", "mentoring_per_week")

    def has_delete_permission(self, request, obj=None):
        # Reference data seeded by migration; deleting a row breaks the
        # trainee report and every fill for that stage.
        return False


@admin.register(RecurringCommitment)
class RecurringCommitmentAdmin(ModelAdmin):
    list_display = ("clinician", "weekday", "part", "session_type", "site",
                    "interval_weeks", "active_from", "active_until")
    list_filter = ("clinician", "session_type", ("active_from", RangeDateFilter))
    search_fields = ("clinician__name",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "weekday":
            kwargs["widget"] = forms.Select(choices=WEEKDAYS)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


@admin.register(Site)
class SiteAdmin(ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(ClosedDay)
class ClosedDayAdmin(ModelAdmin):
    list_display = ("day", "reason")
    date_hierarchy = "day"
    search_fields = ("reason",)
    ordering = ("-day",)


@admin.register(DayNote)
class DayNoteAdmin(ModelAdmin):
    list_display = ("day", "text")
    date_hierarchy = "day"
    search_fields = ("text",)
    ordering = ("-day",)


@admin.register(PracticeSettings)
class PracticeSettingsAdmin(ModelAdmin):
    form = PracticeSettingsForm
    fieldsets = (
        ("Opening", {"fields": ("open_weekdays",)}),
        ("Fill", {"fields": ("min_clinical_per_session", "default_fill_session_type")}),
        ("Trainees", {
            "fields": ("vts_session_type", "sdl_session_type", "mentoring_session_type"),
            "description": "Only for a practice with trainees. A blank type skips that "
                           "pass of the fill — no error.",
        }),
    )

    def has_add_permission(self, request):
        return not PracticeSettings.objects.exists()

    def changelist_view(self, request, extra_context=None):
        """No changelist of one row: open the singleton."""
        return redirect("admin:rota_practicesettings_change",
                        PracticeSettings.load().pk)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.open_weekday_list():
            messages.warning(request, "The surgery is open on no days: the grid "
                                      "will show nothing until a weekday is ticked.")
```

Remove the old `admin.site.register(Site)`, `admin.site.register(ClosedDay)`, `admin.site.register(DayNote)` lines. In the RecurringCommitment inline (Task 6), add the same `formfield_for_dbfield` weekday override.

- [ ] **Step 4: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py tests/test_admin_colour.py tests/test_admin_widgets.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin.py tests/test_admin_models.py
git commit -m "feat: session types, rules, the calendar and practice settings on unfold

Fieldsets carrying the docs' sentences, checkboxes for weekday and month
lists, stage rules editable in place, and the settings page opened
directly from the sidebar.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: The Records, Breathe and System batch

**Files:**
- Modify: `rota/admin.py` (`RotaEntryAdmin`, `RotaEntryLogAdmin`, `LocumRequirementAdmin`, `SwapRequestAdmin`, `BreatheAbsenceAdmin`, `BreatheLeaveMappingAdmin`, `BreatheSyncRunAdmin` base class only)
- Create: `rota/admin_system.py`
- Test: `tests/test_admin_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_models.py`:

```python
# ---------------------------------------------------------------- records ---

def test_rota_entries_search_and_filter(admin_client):
    from tests.factories import make_entry
    c = make_clinician("Searchable Sam")
    make_entry(c, note="bring laptop")
    html = admin_client.get("/admin/rota/rotaentry/?q=laptop").content.decode()
    assert "Searchable Sam" in html
    assert "day__year=" in html, "the date hierarchy renders a year link once an entry exists"


def test_the_audit_log_is_read_only(admin_client):
    from rota.models import RotaEntryLog
    log = RotaEntryLog.objects.create(day=date.today(), action="created", detail="x")
    assert admin_client.get("/admin/rota/rotaentrylog/add/").status_code == 403
    html = _change(admin_client, log)
    assert 'name="detail"' not in html


def test_locum_requirements_filter_by_status_and_search_covering(admin_client):
    from rota.models import LocumRequirement
    covered = make_clinician("Cara Covered")
    LocumRequirement.objects.create(day=date.today(), part="AM",
                                    session_type=make_session_type("Duty"),
                                    status="APPROVED", covering=covered)
    html = admin_client.get("/admin/rota/locumrequirement/?q=Cara").content.decode()
    assert "Cara Covered" in html and "Need approved" in html


# ---------------------------------------------------------------- system ---

@pytest.mark.parametrize("url", ["/admin/axes/accessattempt/", "/admin/axes/accesslog/",
                                 "/admin/axes/accessfailurelog/", "/admin/auth/group/"])
def test_system_tables_render_inside_unfold_for_superusers(staff_client, url):
    from unfold.admin import ModelAdmin
    from django.contrib import admin
    html = staff_client.get(url).content.decode()
    assert "Practice Rota" in html
    model = next(m for m in admin.site._registry
                 if f"/admin/{m._meta.app_label}/{m._meta.model_name}/" == url)
    assert isinstance(admin.site._registry[model], ModelAdmin)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py -q -k "records or audit or locum_requirements or system_tables"`
Expected: the search/filter tests fail (no `search_fields`), the system test fails on `isinstance`.

- [ ] **Step 3: The admins**

Replace in `rota/admin.py`:

```python
@admin.register(RotaEntry)
class RotaEntryAdmin(ModelAdmin):
    list_display = ("day", "part", "clinician", "session_type", "site",
                    "is_published", "manually_set")
    list_filter = ("is_published", "manually_set", "session_type", "clinician")
    search_fields = ("clinician__name", "note")
    date_hierarchy = "day"
    list_select_related = ("clinician", "session_type", "site")
    fieldsets = (
        (None, {"fields": ("day", "part", "clinician", "session_type", "site", "note")}),
        ("State", {
            "fields": ("is_published", "manually_set", "fill_reason"),
            "description": "Published entries are what GPs see. Manually set entries "
                           "are never overwritten by assisted fill; untick to let the "
                           "engine take a cell back.",
        }),
        ("Grouping", {"fields": ("allocation_group", "companion_group"), "classes": ("collapse",)}),
    )


@admin.register(RotaEntryLog)
class RotaEntryLogAdmin(ModelAdmin):
    list_display = ("at", "actor", "action", "day", "part", "clinician_name", "detail")
    list_filter = ("action",)
    search_fields = ("clinician_name", "detail")
    date_hierarchy = "at"
    readonly_fields = [f.name for f in RotaEntryLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LocumRequirement)
class LocumRequirementAdmin(ModelAdmin):
    list_display = ("day", "part", "session_type", "status", "clinician", "covering")
    list_filter = ("status", "session_type", ("day", RangeDateFilter))
    search_fields = ("details", "clinician__name", "covering__name")
    list_select_related = ("session_type", "clinician", "covering")


@admin.register(SwapRequest)
class SwapRequestAdmin(ModelAdmin):
    list_display = ("proposer", "colleague", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("proposer__name", "colleague__name")


@admin.register(BreatheAbsence)
class BreatheAbsenceAdmin(ModelAdmin):
    list_display = ("clinician", "kind", "reason", "start_date", "end_date",
                    "half_start_am_pm", "half_end_am_pm")
    list_filter = ("kind", ("start_date", RangeDateFilter))
    search_fields = ("clinician__name", "reason")
    readonly_fields = [f.name for f in BreatheAbsence._meta.fields]
    # has_add_permission / has_change_permission: unchanged (False)


@admin.register(BreatheLeaveMapping)
class BreatheLeaveMappingAdmin(ModelAdmin):
    list_display = ("kind", "reason", "session_type")
    list_filter = ("kind",)
    # has_delete_permission: unchanged
```

Change `BreatheSyncRunAdmin(admin.ModelAdmin)` to `BreatheSyncRunAdmin(ModelAdmin)`; leave its views for Task 11. Create `rota/admin_system.py`:

```python
"""The superuser-only tables, re-registered on unfold's ModelAdmin so even
the System group does not look like stock Django. django-axes and auth
register their own admins first (INSTALLED_APPS order), so this
unregisters and re-registers; the list columns and filters are theirs."""

from axes.admin import (AccessAttemptAdmin as AxesAttempt,
                        AccessFailureLogAdmin as AxesFailure,
                        AccessLogAdmin as AxesLog)
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin

for model in (AccessAttempt, AccessFailureLog, AccessLog, Group):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


@admin.register(AccessAttempt)
class AccessAttemptAdmin(AxesAttempt, ModelAdmin):
    pass


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(AxesFailure, ModelAdmin):
    pass


@admin.register(AccessLog)
class AccessLogAdmin(AxesLog, ModelAdmin):
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
```

At the very end of `rota/admin.py` add `from . import admin_system  # noqa: E402,F401 — re-registers the System tables on unfold`.

- [ ] **Step 4: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_models.py tests/test_admin_site.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin.py rota/admin_system.py tests/test_admin_models.py
git commit -m "feat: records, Breathe and the System tables on unfold

Search and date filters on entries, the audit log, locum requirements
and absences; axes and auth Groups re-registered so nothing looks stock.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: The pattern editor as an unfold page

**Files:**
- Create: `rota/admin_pages.py` (`PatternEditorView`)
- Create: `templates/admin/rota/patternslot/editor.html`
- Modify: `rota/admin.py` (`PatternSlotAdmin`: `get_urls`, remove `bulk_view`, `_pattern_history`, `change_list_template`)
- Delete: `templates/admin/rota/patternslot/bulk_form.html`, `templates/admin/rota/patternslot/change_list.html`
- Test: `tests/test_pattern_editor.py` (new tests appended); `tests/test_bulk_pattern_admin.py` and the existing tests in `test_pattern_editor.py` must pass unchanged

**Interfaces:**
- Produces: URL name `admin:rota_patternslot_bulk` at the same path `/admin/rota/patternslot/bulk/`; GET params `clinician_id`, `effective_from`, `missing`; POST fields unchanged (`clinician_id`, `effective_from`, `action` ∈ {load, save}, `d<weekday>_<part>`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pattern_editor.py`:

```python
def test_missing_preselects_the_first_clinician_without_a_pattern_and_lists_the_rest(staff_client):
    from tests.factories import make_clinician, make_group, make_pattern
    done = make_clinician("Done Already")
    make_pattern(done)
    a = make_clinician("Alan Empty")
    b = make_clinician("Beth Empty")
    locums = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Idle Locum", group=locums)   # locums are never "missing"
    html = staff_client.get(URL, {"missing": "1"}).content.decode()
    assert f'<option value="{a.pk}" selected' in html
    assert "Beth Empty" in html and "Idle Locum" not in html.split("<form")[0]


def test_saving_with_missing_set_offers_the_next_clinician(staff_client):
    from tests.factories import make_clinician
    a = make_clinician("Alan Empty")
    make_clinician("Beth Empty")
    resp = staff_client.post(URL + "?missing=1", {
        "action": "save", "clinician_id": a.pk, "effective_from": "2026-01-05",
        "d0_AM": "on"}, follow=True)
    html = resp.content.decode()
    assert "Next: Beth Empty" in html
    assert "missing=1" in resp.redirect_chain[-1][0]


def test_the_editor_wears_the_admin_chrome(staff_client, clinician):
    html = staff_client.get(URL, {"clinician_id": clinician.pk}).content.decode()
    assert "Practice Rota" in html and "Pattern editor" in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_pattern_editor.py -q`
Expected: the three new tests FAIL; the existing ones pass.

- [ ] **Step 3: The view**

Create `rota/admin_pages.py`:

```python
"""The admin's bespoke pages, as unfold custom pages.

Each is a class-based view carrying `title` and `permission_required`,
mounted under its ModelAdmin's get_urls() through admin_site.admin_view.
The pattern editor's behaviour is the old bulk_view's, moved not changed:
every guard in it was paid for.
"""

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView
from unfold.views import UnfoldModelAdminViewMixin

from rota.models import Clinician, Part, PatternSlot
from rota.services.patterns import bulk_set_pattern, current_pattern

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]


def clinicians_without_a_pattern():
    """Active, not a locum, no pattern rows at all — the dashboard's
    'working patterns' step and the editor's ?missing=1 share this."""
    return (Clinician.objects.filter(active=True, group__is_locum_group=False,
                                     pattern_slots__isnull=True)
            .order_by("name").distinct())


def pattern_history(clinician):
    by_date = {}
    for row in PatternSlot.objects.filter(clinician=clinician).order_by(
            "effective_from", "weekday", "part"):
        by_date.setdefault(row.effective_from, []).append(
            f"{WEEKDAY_LABELS[row.weekday][:3]} {row.part}{'' if row.works else ' off'}")
    return [{"effective_from": d, "sessions": ", ".join(v)}
            for d, v in sorted(by_date.items())]


class PatternEditorView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Pattern editor"
    permission_required = ("rota.change_patternslot",)
    template_name = "admin/rota/patternslot/editor.html"

    def get(self, request, *args, **kwargs):
        return self._respond(request)

    def post(self, request, *args, **kwargs):
        return self._respond(request)

    def _respond(self, request):
        missing = list(clinicians_without_a_pattern()) if request.GET.get("missing") else []
        clinicians = Clinician.objects.filter(active=True).order_by("name")
        clinician = None
        clinician_id = (request.POST.get("clinician_id")
                        or request.GET.get("clinician_id"))
        if not clinician_id and missing:
            clinician_id = missing[0].pk
        if clinician_id:
            clinician = get_object_or_404(Clinician, pk=clinician_id)

        # raw_date is for RENDERING (POST or the query string the post-save
        # redirect carries); posted_date is the only thing a SAVE may look
        # at. Conflating them was the overwrite bug: a cleared field fell
        # back to a stale query-string date.
        raw_date = (request.POST.get("effective_from")
                    or request.GET.get("effective_from") or "")
        posted_date = request.POST.get("effective_from") or ""
        date_error = ""
        if raw_date:
            try:
                effective_from = date.fromisoformat(raw_date)
            except ValueError:
                effective_from = date.today()
                date_error = (f"{raw_date!r} is not a date (use YYYY-MM-DD). "
                              f"Nothing was saved.")
        else:
            effective_from = date.today()

        action = request.POST.get("action")
        saving = request.method == "POST" and action == "save" and clinician
        if saving and not posted_date:
            date_error = "Effective date is required. Nothing was saved."

        if saving and not date_error:
            desired = {(weekday, part): f"d{weekday}_{part}" in request.POST
                       for weekday in range(7) for part in Part.values}
            changed = bulk_set_pattern(clinician, effective_from, desired)
            text = (f"Saved pattern for {clinician.name} effective "
                    f"{effective_from} ({changed} slot(s) changed).")
            query = f"?clinician_id={clinician.pk}&effective_from={effective_from.isoformat()}"
            if request.GET.get("missing"):
                remaining = [c for c in clinicians_without_a_pattern() if c.pk != clinician.pk]
                if remaining:
                    text += f" Next: {remaining[0].name}."
                    query = f"?clinician_id={remaining[0].pk}&missing=1"
                else:
                    text += " Everyone has a pattern now."
            messages.success(request, text)
            return redirect(f"{request.path}{query}")

        grid, history = None, []
        if clinician:
            in_force = current_pattern(clinician, effective_from)
            grid = [{"weekday": w, "label": WEEKDAY_LABELS[w],
                     "am_checked": in_force.get((w, "AM"), False),
                     "pm_checked": in_force.get((w, "PM"), False)} for w in range(7)]
            history = pattern_history(clinician)

        context = self.get_context_data(
            clinicians=clinicians, clinician=clinician, effective_from=effective_from,
            date_error=date_error, grid=grid, history=history, missing=missing)
        return self.render_to_response(context)
```

In `rota/admin.py`, `PatternSlotAdmin` becomes:

```python
@admin.register(PatternSlot)
class PatternSlotAdmin(ModelAdmin):
    list_display = ("clinician", "weekday", "part", "works", "effective_from")
    list_filter = ("clinician",)

    def get_urls(self):
        from .admin_pages import PatternEditorView
        return [
            path("bulk/",
                 self.admin_site.admin_view(PatternEditorView.as_view(model_admin=self)),
                 name="rota_patternslot_bulk"),
        ] + super().get_urls()
```

Delete `bulk_view`, `_pattern_history`, the `change_list_template` line, and the two old templates. Remove the now-unused imports (`bulk_set_pattern`, `current_pattern`, `get_object_or_404`, `Part`, `WEEKDAY_LABELS` if nothing else uses them — `WEEKDAY_LABELS` is still used by `pattern_text`).

- [ ] **Step 4: The template**

Create `templates/admin/rota/patternslot/editor.html`:

```html
{% extends "admin/base.html" %}
{% load i18n unfold %}

{% block breadcrumbs %}{% endblock %}
{% block title %}{{ title }} | {{ site_title }}{% endblock %}
{% block branding %}{% include "unfold/helpers/site_branding.html" %}{% endblock %}

{% block content %}
{% component "unfold/components/container.html" %}
  {% component "unfold/components/title.html" %}{{ title }}{% endcomponent %}

  {% if missing %}
  {% component "unfold/components/card.html" with title="Clinicians without a pattern" class="mb-6" %}
    <p class="mb-2">The fill engine can place nobody it does not know the working days of. Set each in turn — Save moves on to the next.</p>
    <ul class="list-disc pl-5">{% for c in missing %}<li>{{ c.name }}</li>{% endfor %}</ul>
  {% endcomponent %}
  {% endif %}

  {% component "unfold/components/card.html" %}
  {# One form, deliberately: the date you can see is the date that posts. #}
  <form method="post">
    {% csrf_token %}
    <div class="flex flex-wrap items-end gap-4 mb-6">
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-sm">Clinician</span>
        <select name="clinician_id" class="border border-base-200 rounded-default px-3 py-2 dark:border-base-700 dark:bg-base-900">
          <option value="">— choose —</option>
          {% for c in clinicians %}
          <option value="{{ c.id }}" {% if clinician.id == c.id %}selected{% endif %}>{{ c.name }}</option>
          {% endfor %}
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-sm">Effective from</span>
        <input type="date" name="effective_from" value="{{ effective_from|date:'Y-m-d' }}" class="border border-base-200 rounded-default px-3 py-2 dark:border-base-700 dark:bg-base-900">
      </label>
      {% component "unfold/components/button.html" with submit=1 name="action" value="load" %}Load{% endcomponent %}
    </div>

    {% if date_error %}<p class="text-red-600 dark:text-red-500 font-semibold mb-4">{{ date_error }}</p>{% endif %}

    {% if clinician %}
    <p class="mb-4">Ticked boxes are the sessions {{ clinician.name }} works on {{ effective_from }} — the pattern in force on that date, including any change already dated {{ effective_from }}. Save writes only the cells you change, dated {{ effective_from }}. A change dated today replaces today's pattern; date a future change on the day it starts.</p>
    <table class="border-collapse mb-6">
      <thead><tr><th class="text-left pr-6 py-1">Day</th><th class="px-4 py-1">AM</th><th class="px-4 py-1">PM</th></tr></thead>
      <tbody>
        {% for row in grid %}
        <tr class="border-t border-base-200 dark:border-base-800">
          <th class="text-left pr-6 py-2 font-medium">{{ row.label }}</th>
          <td class="px-4 py-2 text-center"><input type="checkbox" name="d{{ row.weekday }}_AM"{% if row.am_checked %} checked{% endif %}></td>
          <td class="px-4 py-2 text-center"><input type="checkbox" name="d{{ row.weekday }}_PM"{% if row.pm_checked %} checked{% endif %}></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% component "unfold/components/button.html" with submit=1 name="action" value="save" variant="primary" %}Save pattern{% endcomponent %}
    {% endif %}
  </form>
  {% endcomponent %}

  {% if history %}
  {% component "unfold/components/card.html" with title="Pattern history" class="mt-6" %}
    <p class="mb-3">Every date this clinician's pattern changes on.</p>
    <table class="border-collapse">
      <thead><tr><th class="text-left pr-6 py-1">Effective from</th><th class="text-left py-1">Sets</th></tr></thead>
      <tbody>{% for h in history %}<tr class="border-t border-base-200 dark:border-base-800"><th class="text-left pr-6 py-2 font-medium">{{ h.effective_from }}</th><td class="py-2">{{ h.sessions }}</td></tr>{% endfor %}</tbody>
    </table>
  {% endcomponent %}
  {% endif %}
{% endcomponent %}
{% endblock %}
```

If `unfold/components/button.html` does not accept `name`/`value`/`submit` in this version (check the file in the installed package), render the two buttons as plain `<button type="submit" name="action" value="...">` with unfold's button classes copied from that component — the `name="action"` / `value` pair is load-bearing and must survive.

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_pattern_editor.py tests/test_bulk_pattern_admin.py tests/test_admin_site.py -q` — all pass, including every pre-existing assertion.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_pages.py rota/admin.py templates/admin/rota/patternslot/editor.html tests/test_pattern_editor.py
git rm -q templates/admin/rota/patternslot/bulk_form.html templates/admin/rota/patternslot/change_list.html
git commit -m "feat: the pattern editor is an unfold page, behaviour unchanged

Same URL, same guards, same history table; plus ?missing=1, which walks
the clinicians who have no pattern yet.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Sync status as an unfold page

**Files:**
- Modify: `rota/admin_pages.py` (`BreatheStatusView`)
- Create: `templates/admin/rota/breathesyncrun/status.html`
- Modify: `rota/admin.py` (`BreatheSyncRunAdmin`), `rota/admin_site.py` (the Sync status link)
- Delete: `templates/admin/rota/breathesyncrun/change_list.html`
- Test: `tests/test_breathe_status.py` (re-pointed)

**Interfaces:**
- Produces: URL `admin:rota_breathesyncrun_status` at `/admin/rota/breathesyncrun/status/`; `admin:rota_breathesyncrun_refresh` redirects there.

- [ ] **Step 1: Re-point the existing tests and add two**

In `tests/test_breathe_status.py`, every `"/admin/rota/breathesyncrun/"` GET becomes `"/admin/rota/breathesyncrun/status/"` (lines 24, 32). The refresh tests already POST to `/refresh/`; where one follows the redirect and reads the page, it now lands on the status page — no assertion changes. Append:

```python
def test_the_status_page_lists_recent_runs_and_the_changelist_is_plain(staff_client):
    from django.utils import timezone
    from rota.models import BreatheSyncRun
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True,
                                  n_requests=1, n_absences=2, n_sicknesses=0,
                                  n_deduped=3, n_unlinked=0)
    html = staff_client.get("/admin/rota/breathesyncrun/status/").content.decode()
    assert "Refresh now" in html and "Recent runs" in html
    plain = staff_client.get("/admin/rota/breathesyncrun/").content.decode()
    assert "Last successful sync" not in plain


def test_the_sidebar_links_the_status_page(staff_client):
    html = staff_client.get("/admin/").content.decode()
    assert "/admin/rota/breathesyncrun/status/" in html
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_breathe_status.py -q`
Expected: the status URL 404s.

- [ ] **Step 3: The view and the admin**

Append to `rota/admin_pages.py`:

```python
from datetime import timedelta

from django.utils import timezone

from rota.models import BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun
from rota.services.breathe import client as breathe_client


def unmapped_absence_count():
    mapping = BreatheLeaveMapping.as_dict()
    return sum(1 for kind, reason in BreatheAbsence.objects.values_list("kind", "reason")
               if (kind, reason) not in mapping and (kind, "") not in mapping)


class BreatheStatusView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Sync status"
    permission_required = ("rota.view_breathesyncrun",)
    template_name = "admin/rota/breathesyncrun/status.html"

    def get_context_data(self, **kwargs):
        last_ok = BreatheSyncRun.objects.filter(ok=True).first()
        last = BreatheSyncRun.objects.first()
        return super().get_context_data(
            configured=breathe_client.from_settings() is not None,
            last_ok=last_ok,
            last_error=last if (last and not last.ok) else None,
            unlinked=Clinician.objects.filter(active=True, breathe_employee_id=None)
                                      .order_by("name"),
            unmapped_count=unmapped_absence_count(),
            runs=BreatheSyncRun.objects.all()[:20],
            **kwargs)
```

Move the imports to the top of the module. In `rota/admin.py`, `BreatheSyncRunAdmin` becomes:

```python
@admin.register(BreatheSyncRun)
class BreatheSyncRunAdmin(ModelAdmin):
    list_display = ("started", "ok", "n_deduped", "n_unlinked", "error")
    readonly_fields = [f.name for f in BreatheSyncRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        from .admin_pages import BreatheStatusView
        return [
            path("status/",
                 self.admin_site.admin_view(BreatheStatusView.as_view(model_admin=self)),
                 name="rota_breathesyncrun_status"),
            path("refresh/", self.admin_site.admin_view(self.refresh),
                 name="rota_breathesyncrun_refresh"),
        ] + super().get_urls()

    def refresh(self, request):
        # unchanged body, with every redirect target changed to
        # "admin:rota_breathesyncrun_status"
        ...
```

Delete `changelist_view`, `change_list_template`, and `_unmapped_absence_count` from `rota/admin.py` (the page module owns it now). In `rota/admin_site.py`, the Sync status item links `rl("admin:rota_breathesyncrun_status")`.

- [ ] **Step 4: The template**

Create `templates/admin/rota/breathesyncrun/status.html`:

```html
{% extends "admin/base.html" %}
{% load i18n unfold %}

{% block breadcrumbs %}{% endblock %}
{% block title %}{{ title }} | {{ site_title }}{% endblock %}
{% block branding %}{% include "unfold/helpers/site_branding.html" %}{% endblock %}

{% block content %}
{% component "unfold/components/container.html" %}
  {% component "unfold/components/title.html" %}{{ title }}{% endcomponent %}

  {% component "unfold/components/card.html" with title="Breathe" class="mb-6" %}
    {% if not configured %}
      <p class="mb-2"><strong>Breathe is not configured.</strong> Set <code>BREATHE_API_KEY</code> in <code>/etc/rota.env</code> and restart. Until then no leave is read and every clinician is treated as available.</p>
    {% endif %}
    {% if last_ok %}
      <p class="mb-2"><strong>Last successful sync:</strong> {{ last_ok.started|date:"D j M H:i" }} — {{ last_ok.n_deduped }} absence{{ last_ok.n_deduped|pluralize }} from {{ last_ok.n_requests }} request{{ last_ok.n_requests|pluralize }}, {{ last_ok.n_absences }} absence record{{ last_ok.n_absences|pluralize }} and {{ last_ok.n_sicknesses }} sickness{{ last_ok.n_sicknesses|pluralize:"es" }}; {{ last_ok.n_unlinked }} for unlinked employees.</p>
    {% elif configured %}
      <p class="mb-2"><strong>No successful sync yet.</strong></p>
    {% endif %}
    {% if last_error %}
      <p class="mb-2 text-red-600 dark:text-red-500"><strong>Most recent run failed</strong> ({{ last_error.started|date:"D j M H:i" }}): {{ last_error.error }}</p>
    {% endif %}
    {% if unmapped_count %}
      <p class="mb-2 text-red-600 dark:text-red-500">{{ unmapped_count }} absence{{ unmapped_count|pluralize }} have no mapping and render as empty cells — <a href="{% url 'admin:rota_breatheleavemapping_changelist' %}" class="underline">add a mapping</a>.</p>
    {% endif %}
    {% if unlinked %}
      <p class="mb-2"><strong>Not linked to Breathe</strong> — no leave is read for these, so they are always available:
      {% for c in unlinked %}<a class="underline" href="{% url 'admin:rota_clinician_change' c.pk %}">{{ c.name }}</a>{% if not forloop.last %}, {% endif %}{% endfor %}</p>
    {% endif %}
    <form method="post" action="{% url 'admin:rota_breathesyncrun_refresh' %}" class="mt-4">
      {% csrf_token %}
      <button type="submit" class="bg-primary-600 text-white rounded-default px-4 py-2 font-semibold{% if not configured %} opacity-50{% endif %}"{% if not configured %} disabled title="BREATHE_API_KEY is not set"{% endif %}>Refresh now</button>
    </form>
  {% endcomponent %}

  {% component "unfold/components/card.html" with title="Recent runs" %}
    <table class="border-collapse w-full">
      <thead><tr><th class="text-left py-1">Started</th><th class="text-left py-1">OK</th><th class="text-left py-1">Absences</th><th class="text-left py-1">Unlinked</th><th class="text-left py-1">Error</th></tr></thead>
      <tbody>
      {% for r in runs %}
      <tr class="border-t border-base-200 dark:border-base-800"><td class="py-2">{{ r.started|date:"D j M H:i" }}</td><td class="py-2">{{ r.ok|yesno:"yes,no" }}</td><td class="py-2">{{ r.n_deduped }}</td><td class="py-2">{{ r.n_unlinked }}</td><td class="py-2">{{ r.error }}</td></tr>
      {% empty %}
      <tr><td colspan="5" class="py-2">No runs yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  {% endcomponent %}
{% endcomponent %}
{% endblock %}
```

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_breathe_status.py tests/test_admin_site.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_pages.py rota/admin.py rota/admin_site.py templates/admin/rota/breathesyncrun/status.html tests/test_breathe_status.py
git rm -q templates/admin/rota/breathesyncrun/change_list.html
git commit -m "feat: Breathe sync status is its own page

What a manager needs first — configured, last good sync, last error,
who is unlinked, what is unmapped, Refresh now — then the runs as
history. The changelist is plain again.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: The dashboard — a setup checklist and a health panel

**Files:**
- Create: `rota/admin_dashboard.py`
- Create: `templates/admin/index.html`
- Modify: `config/settings.py` (`UNFOLD["DASHBOARD_CALLBACK"]`)
- Test: `tests/test_admin_dashboard.py` (new)

**Interfaces:**
- Consumes: `rota.admin_pages.clinicians_without_a_pattern()`, `unmapped_absence_count()`; `rota.services.warnings.day_warnings`; `rota.services.calendar.is_open`.
- Produces: `setup_steps() -> dict`, `health() -> list[dict]`, `dashboard(request, context) -> context`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_dashboard.py`:

```python
"""The dashboard reads the database. Each setup step flips on one exact
condition; each health line counts one thing and links to its fix; the
whole page costs a fixed number of queries."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from rota.admin_dashboard import health, setup_steps
from rota.models import (BreatheSyncRun, ClinicianGroup, CoverageRule,
                         PracticeSettings, Site)
from tests.factories import (make_clinician, make_group, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _step(title):
    return next(s for s in setup_steps()["steps"] if s["title"] == title)


def test_practice_settings_step_needs_open_days_and_a_default_type():
    s = PracticeSettings.load()
    assert not _step("Practice settings")["done"]
    s.default_fill_session_type = make_session_type("Routine")
    s.save()
    assert _step("Practice settings")["done"]
    s.open_weekdays = ""
    s.save()
    assert not _step("Practice settings")["done"]


def test_sites_and_rules_steps():
    assert not _step("Sites")["done"] and not _step("Coverage rules")["done"]
    Site.objects.create(name="Main")
    CoverageRule.objects.create(session_type=make_session_type("Duty"))
    assert _step("Sites")["done"] and _step("Coverage rules")["done"]


def test_groups_step_needs_exactly_one_locum_group():
    make_group("Partners")
    assert not _step("Clinician groups")["done"]
    make_group("Locum", is_locum_group=True, display_order=99)
    assert _step("Clinician groups")["done"]


def test_session_types_step_needs_a_clinical_and_an_absence_type():
    make_session_type("Routine")
    assert not _step("Session types")["done"]
    make_session_type("Annual Leave", code="AL", category="ABSENCE")
    assert _step("Session types")["done"]


def test_clinicians_and_patterns_steps():
    assert not _step("Clinicians")["done"]
    c = make_clinician("Ann Able")
    assert _step("Clinicians")["done"] and not _step("Working patterns")["done"]
    assert "1 clinician" in _step("Working patterns")["detail"]
    make_pattern(c)
    assert _step("Working patterns")["done"]


def test_breathe_step_needs_key_sync_and_links(settings):
    c = make_clinician("Ann Able", breathe_employee_id=1)
    assert not _step("Breathe")["done"]
    settings.BREATHE_API_KEY = "set"
    assert not _step("Breathe")["done"]
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)
    assert _step("Breathe")["done"]
    make_clinician("Bob Unlinked")
    assert not _step("Breathe")["done"]


def test_the_headline_counts_and_names_the_next_step():
    Site.objects.create(name="Main")
    steps = setup_steps()
    assert steps["done"] == 1 and steps["total"] == 8
    assert steps["next"]["title"] == "Practice settings"
    assert not steps["complete"]


def test_health_lines_count_and_link():
    make_clinician("No Pattern")
    lines = {h["label"]: h for h in health()}
    assert lines["Clinicians with no working pattern"]["count"] == 1
    assert "missing=1" in lines["Clinicians with no working pattern"]["url"]
    assert lines["Clinicians not linked to Breathe"]["count"] == 1
    assert lines["Breathe sync"]["detail"] == "not configured"


def test_the_dashboard_renders_both_cards(admin_client):
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    assert "Setup" in html and "Health" in html and "of 8" in html


def test_the_dashboard_does_not_query_per_clinician(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    PracticeSettings.load()
    for i in range(3):
        make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))
    admin_client.get("/admin/")
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/")
    baseline = len(ctx)
    for i in range(3, 13):
        make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/")
    assert len(ctx) == baseline
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_dashboard.py -q`
Expected: `ImportError` on `rota.admin_dashboard`.

- [ ] **Step 3: The module**

Create `rota/admin_dashboard.py`:

```python
"""The dashboard: a setup checklist detected from the database, and a
health panel of the things that go quietly wrong. Pure functions over the
ORM; the template renders what they return."""

from datetime import date, timedelta

from django.conf import settings
from django.urls import reverse

from rota.admin_pages import clinicians_without_a_pattern, unmapped_absence_count
from rota.models import (BreatheSyncRun, Clinician, ClinicianGroup, CoverageRule,
                         LocumRequirement, PracticeSettings, SessionType, Site,
                         TraineeProfile)
from rota.services.calendar import is_open
from rota.services.warnings import day_warnings


def _cl(name, **params):
    url = reverse(f"admin:rota_{name}_changelist")
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def _unlinked():
    return Clinician.objects.filter(active=True, group__is_locum_group=False,
                                    breathe_employee_id=None)


def setup_steps():
    ps = PracticeSettings.load()
    missing_patterns = clinicians_without_a_pattern().count()
    unlinked = _unlinked().count()
    any_active = Clinician.objects.filter(active=True).exists()
    steps = [
        {"title": "Practice settings",
         "done": bool(ps.open_weekday_list()) and ps.default_fill_session_type_id is not None,
         "detail": "open days and a default session type",
         "url": reverse("admin:rota_practicesettings_change", args=[ps.pk])},
        {"title": "Sites", "done": Site.objects.exists(),
         "detail": "at least one", "url": reverse("admin:rota_site_add")},
        {"title": "Clinician groups",
         "done": ClinicianGroup.objects.exists()
                 and ClinicianGroup.objects.filter(is_locum_group=True).count() == 1,
         "detail": "at least one, and exactly one locum group",
         "url": _cl("cliniciangroup")},
        {"title": "Session types",
         "done": SessionType.objects.filter(category=SessionType.Category.CLINICAL).exists()
                 and SessionType.objects.filter(category=SessionType.Category.ABSENCE).exists(),
         "detail": "at least one clinical and one absence type",
         "url": _cl("sessiontype")},
        {"title": "Coverage rules", "done": CoverageRule.objects.exists(),
         "detail": "what must be staffed", "url": _cl("coveragerule")},
        {"title": "Clinicians", "done": any_active,
         "detail": "at least one active", "url": reverse("admin:rota_clinician_add")},
        {"title": "Working patterns",
         "done": any_active and missing_patterns == 0,
         "detail": (f"{missing_patterns} clinician{'s' if missing_patterns != 1 else ''} "
                    f"without one" if missing_patterns else "everyone has one"),
         "url": reverse("admin:rota_patternslot_bulk") + "?missing=1"},
        {"title": "Breathe",
         "done": bool(settings.BREATHE_API_KEY)
                 and BreatheSyncRun.objects.filter(ok=True).exists()
                 and unlinked == 0,
         "detail": (f"{unlinked} not linked" if unlinked else "key set, synced, everyone linked"),
         "url": (_cl("clinician", breathe="unlinked", active__exact=1) if unlinked
                 else reverse("admin:rota_breathesyncrun_status"))},
    ]
    done = sum(s["done"] for s in steps)
    nxt = next((s for s in steps if not s["done"]), None)
    return {"steps": steps, "done": done, "total": len(steps),
            "next": nxt, "complete": nxt is None}


def health():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week = [monday + timedelta(days=i) for i in range(7)]
    gap_days = sum(1 for d in week if is_open(d) and day_warnings(d, include_drafts=True))

    last = BreatheSyncRun.objects.first()
    last_ok = BreatheSyncRun.objects.filter(ok=True).first()
    if not settings.BREATHE_API_KEY:
        breathe = ("not configured", "warn")
    elif last is not None and not last.ok:
        breathe = (f"last run failed: {last.error[:80]}", "warn")
    elif last_ok is None:
        breathe = ("no successful sync yet", "warn")
    else:
        breathe = (f"last good sync {last_ok.started:%a %-d %b %H:%M}", "ok")

    ps = PracticeSettings.load()
    trainee_gap = (TraineeProfile.objects.exists()
                   and not (ps.vts_session_type_id and ps.sdl_session_type_id
                            and ps.mentoring_session_type_id))
    return [
        {"label": "Clinicians with no working pattern",
         "count": clinicians_without_a_pattern().count(),
         "url": reverse("admin:rota_patternslot_bulk") + "?missing=1", "level": "warn"},
        {"label": "Clinicians not linked to Breathe", "count": _unlinked().count(),
         "url": _cl("clinician", breathe="unlinked", active__exact=1), "level": "warn"},
        {"label": "Breathe sync", "count": None, "detail": breathe[0],
         "url": reverse("admin:rota_breathesyncrun_status"), "level": breathe[1]},
        {"label": "Absences with no mapping", "count": unmapped_absence_count(),
         "url": _cl("breatheleavemapping"), "level": "warn"},
        {"label": "Days with staffing gaps this week", "count": gap_days,
         "url": "/reports/staffing/", "level": "warn"},
        {"label": "Locum needs not yet advertised (next fortnight)",
         "count": LocumRequirement.objects.filter(
             status__in=[LocumRequirement.Status.POSSIBLE, LocumRequirement.Status.APPROVED],
             day__range=(today, today + timedelta(days=14))).count(),
         "url": _cl("locumrequirement", status__exact="POSSIBLE"), "level": "warn"},
        {"label": "Trainee session types unset", "count": 1 if trainee_gap else 0,
         "url": reverse("admin:rota_practicesettings_change", args=[ps.pk]), "level": "warn"},
    ]


def dashboard(request, context):
    context["setup"] = setup_steps()
    context["health"] = health()
    return context
```

- [ ] **Step 4: The template and setting**

Create `templates/admin/index.html`:

```html
{% extends "admin/base.html" %}
{% load i18n unfold %}

{% block title %}{{ title }} | {{ site_title }}{% endblock %}
{% block branding %}{% include "unfold/helpers/site_branding.html" %}{% endblock %}

{% block content %}
<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
  <div class="lg:w-1/2">
    {% component "unfold/components/card.html" with title="Setup" %}
      {% if setup.complete %}
        <p class="font-semibold">Setup complete.</p>
        <details class="mt-2"><summary class="cursor-pointer text-base-500">Show the steps</summary>
      {% else %}
        <p class="mb-3"><strong>{{ setup.done }} of {{ setup.total }} done</strong> — next: <a class="underline" href="{{ setup.next.url }}">{{ setup.next.title }}</a> ({{ setup.next.detail }}).</p>
      {% endif %}
      <ol class="list-decimal pl-5 flex flex-col gap-1">
        {% for step in setup.steps %}
        <li class="{% if step.done %}text-base-500{% elif step == setup.next %}font-semibold{% endif %}">
          <a href="{{ step.url }}" class="underline">{{ step.title }}</a>
          <span class="text-base-500">— {{ step.detail }}</span>{% if step.done %} ✓{% endif %}
        </li>
        {% endfor %}
      </ol>
      {% if setup.complete %}</details>{% endif %}
    {% endcomponent %}
  </div>
  <div class="lg:w-1/2">
    {% component "unfold/components/card.html" with title="Health" %}
      <ul class="flex flex-col gap-2">
        {% for h in health %}
        <li class="flex items-baseline gap-3{% if h.count == 0 %} text-base-500{% elif h.level == 'warn' and h.count != None %} text-red-600 dark:text-red-500 font-semibold{% endif %}">
          <a href="{{ h.url }}" class="underline grow">{{ h.label }}</a>
          {% if h.count != None %}<span>{{ h.count }}</span>{% else %}<span class="{% if h.level == 'warn' %}text-red-600 dark:text-red-500{% endif %}">{{ h.detail }}</span>{% endif %}
        </li>
        {% endfor %}
      </ul>
    {% endcomponent %}
  </div>
</div>
{% endblock %}
```

If `text-red-600`/`dark:text-red-500` are absent from unfold's compiled `styles.css` (grep `unfold/static/unfold/css/styles.css` in the installed package for `.text-red-600`), add `.rota-warn { color: var(--color-primary-700); font-weight: 600 }` to `static/admin/rota-admin.css` and use that class instead — no literal colour either way.

Add to `UNFOLD` in `config/settings.py`: `"DASHBOARD_CALLBACK": "rota.admin_dashboard.dashboard",`.

- [ ] **Step 5: Run the tests, the suite, and commit**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_dashboard.py tests/test_admin_site.py -q` — all pass.
Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add rota/admin_dashboard.py templates/admin/index.html config/settings.py tests/test_admin_dashboard.py
git commit -m "feat: the admin opens on a setup checklist and a health panel

Eight steps detected from the database, each a link to where it is
done; seven health lines for what goes quietly wrong. Fixed query count.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Render everything, and prove the deploy

**Files:**
- Create: `tests/test_admin_render.py`
- Test: run `collectstatic` under manifest storage and `check --deploy` on this box (acceptance, not a test file)

- [ ] **Step 1: Write the test**

Create `tests/test_admin_render.py`:

```python
"""Every admin page renders for the practice manager — the upgrade tripwire.

Walks the registry: changelist, add form and change form per model (one
fixture row each), plus the dashboard and the two custom pages. A future
unfold pin bump that breaks a template fails here, not on staging.
"""

from datetime import date

import pytest
from django.contrib import admin
from django.utils import timezone

from tests.factories import (make_clinician, make_commitment, make_entry,
                             make_group, make_pattern, make_session_type,
                             make_site, make_trainee)

pytestmark = pytest.mark.django_db

LEAKED = ["{#", "#}", "{%", "TODO:", "FIXME:", "XXX:", "vestigial"]


@pytest.fixture
def rows(admin_user):
    """One row per rota/accounts model."""
    from rota.models import (BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun,
                             ClosedDay, CoverageRule, DayNote, LocumRequirement,
                             PatternSlot, PracticeSettings, RotaEntryLog, SwapRequest,
                             TraineeStageRule)
    from tests.factories import make_absence
    group = make_group("Partners")
    make_group("Locum", is_locum_group=True, display_order=99)
    c = make_clinician("Ann Able", group=group, user=admin_user)
    d = make_clinician("Bob Baker", group=group)
    st = make_session_type("Duty")
    make_pattern(c)
    return {
        "cliniciangroup": group, "clinician": c, "sessiontype": st,
        "site": make_site(), "patternslot": PatternSlot.objects.first(),
        "coveragerule": CoverageRule.objects.create(session_type=st),
        "traineestagerule": TraineeStageRule.objects.first(),
        "traineeprofile": make_trainee(d),
        "recurringcommitment": make_commitment(c, st),
        "closedday": ClosedDay.objects.create(day=date(2026, 12, 25), reason="Christmas"),
        "daynote": DayNote.objects.create(day=date(2026, 9, 7), text="CQC visit"),
        "practicesettings": PracticeSettings.load(),
        "rotaentry": make_entry(c, session_type=st),
        "rotaentrylog": RotaEntryLog.objects.create(day=date.today(), action="created"),
        "locumrequirement": LocumRequirement.objects.create(
            day=date.today(), part="AM", session_type=st),
        "swaprequest": SwapRequest.objects.create(
            proposer=c, proposer_day=date.today(), proposer_part="AM",
            colleague=d, colleague_day=date.today(), colleague_part="PM"),
        "breatheabsence": make_absence(c, date.today()),
        "breatheleavemapping": BreatheLeaveMapping.objects.first(),
        "breathesyncrun": BreatheSyncRun.objects.create(
            started=timezone.now(), finished=timezone.now(), ok=True),
        "user": admin_user,
    }


def _models():
    return [m for m in admin.site._registry if m._meta.app_label in ("rota", "accounts")]


@pytest.mark.parametrize("model", _models(), ids=lambda m: m._meta.model_name)
def test_every_changelist_and_form_renders_for_a_rota_admin(admin_client, rows, model):
    opts = model._meta
    base = f"/admin/{opts.app_label}/{opts.model_name}/"
    ma = admin.site._registry[model]
    resp = admin_client.get(base, follow=True)
    assert resp.status_code == 200, (base, resp.status_code)
    if ma.has_add_permission(resp.wsgi_request):
        assert admin_client.get(base + "add/").status_code == 200, base + "add/"
    row = rows[opts.model_name]
    resp = admin_client.get(f"{base}{row.pk}/change/")
    assert resp.status_code == 200, f"{base}{row.pk}/change/"
    html = resp.content.decode()
    for frag in LEAKED:
        assert frag not in html, (base, frag)


@pytest.mark.parametrize("url", ["/admin/", "/admin/rota/patternslot/bulk/",
                                 "/admin/rota/breathesyncrun/status/"])
def test_the_dashboard_and_custom_pages_render(admin_client, rows, url):
    resp = admin_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    for frag in LEAKED:
        assert frag not in html, (url, frag)
```

- [ ] **Step 2: Run it**

Run: `/root/rota/.venv/bin/python -m pytest tests/test_admin_render.py -q` — all pass. Any 500 here is a real defect in an earlier task's admin: fix it in that admin (the reviewer will see the fix in this task's diff) and say which in the report.

- [ ] **Step 3: Deploy acceptance on this box**

With the environment the deployed service uses (`set -a && source /etc/rota.env && set +a`, which sets DEBUG off), run:

```bash
/root/rota/.venv/bin/python manage.py collectstatic --noinput --clear -v 0
/root/rota/.venv/bin/python manage.py check --deploy
```

Both must succeed (the manifest storage hashes unfold's files and rewrites its `url()`s; the deploy check confirms every referenced static file exists). Paste both outputs into the report. `staticfiles/` is git-ignored; confirm `git status` is clean of it.

- [ ] **Step 4: Run the suite and commit**

Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add tests/test_admin_render.py
git commit -m "test: every admin page renders for a rota admin

The upgrade tripwire: a future unfold bump that breaks a template fails
here rather than in front of a manager.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: The words around it

**Files:**
- Modify: `README.md` (First-time setup), `docs/admin/README.md`, each `docs/admin/*.md` (a "Where" line)
- Create: `docs/admin/upgrading-unfold.md`

- [ ] **Step 1: README**

In `README.md`, replace the `## First-time setup (via /admin/)` heading and its numbered list with:

```markdown
## First-time setup

1. `python manage.py createsuperuser`
2. Sign in and open **Admin**. The dashboard's **Setup** card lists eight
   steps, each detected from the database and linked to where it is done;
   follow it until it reads "Setup complete". The **Health** card beside it
   is what to glance at afterwards.

The sequence the checklist walks, for reference: practice settings → sites →
clinician groups → session types → coverage rules → clinicians → working
patterns → Breathe. Trainees, recurring commitments and locum bookings are
day-to-day work, not setup — see [docs/admin/](docs/admin/README.md).
```

Move the old numbered steps (2–14) under a new heading `### Appendix: the setup steps in detail` at the end of the README, unchanged.

- [ ] **Step 2: The admin guide**

In `docs/admin/README.md`, after the first paragraph add:

```markdown
The admin now explains itself: every field carries a sentence, every page a
short description, and the dashboard's Setup card walks a new practice
through the eight steps in order. This guide is the reference for the
"why" — read it when a setting does not do what you expected.
```

Add a `**Where:** sidebar › <Group> › <Item>` line under the first heading of each page: `practice-settings.md` (Practice settings; Sessions & rules › Sites), `people.md` (People › Clinician groups / Clinicians / Login accounts; Working patterns › Trainee profiles), `availability.md` (Working patterns › Pattern editor / Recurring commitments; Calendar › Closed days / Day notes), `session-types.md` (Sessions & rules › Session types), `coverage-rules.md` (Sessions & rules › Coverage rules / Trainee stage rules), `day-to-day.md` (Records › Rota entries / Audit log / Locum requirements / Swap requests), `breathe.md` (Leave from Breathe › Sync status / Leave mapping / Absences).

- [ ] **Step 3: Upgrading unfold**

Create `docs/admin/upgrading-unfold.md`:

```markdown
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
```

- [ ] **Step 4: Run the suite and commit**

Run: `/root/rota/.venv/bin/python -m pytest -q` — all pass.

```bash
git add README.md docs/admin
git commit -m "docs: setup is the dashboard now; the guide is the why; upgrading unfold

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review against the spec

**Spec coverage.**

| Spec section | Task |
|---|---|
| §1 package, INSTALLED_APPS, site identity, favicons, `has_permission`, login redirect, logout | 1 |
| §1 colours from tokens, font, theme bridge, `STYLES`/`SCRIPTS` | 3 |
| §1 permissions backend, Admin link | 2 |
| §2 sidebar groups, System for superusers, command palette, verbose names, TraineeProfile registration | 4 (sidebar, registration), 7 (verbose names) |
| §3 dashboard: eight steps, seven health lines, collapse when complete, fixed queries, `admin/index.html` | 12 |
| §4 shared treatment, checkbox lists, every model's fieldsets/search/filters/inlines, help-text migration | 5 (fields/widgets), 6 (People), 7 (words), 8 (Sessions/Calendar/Settings), 9 (Records/Breathe/System) |
| §5 pattern editor port with `?missing=1` and Next; Sync status page; swatches; login/logout | 10, 11, 5, 1 |
| §6 failure modes | covered in the tasks' code (fallbacks kept in 6; System hidden in 4; singleton via `load()` in 4/8; pin + render test in 13; contrast in 3; bridge try/catch in 3) |
| §7 render-everything test, permissions tests, colour tests, dashboard tests, widget tests, behaviour preserved, deploy acceptance, docs | 13, 1–2, 3, 12, 5, 10–11, 13, 14 |

Three plan-level corrections to the spec, recorded here for the controller's rulings list: (1) verbose names migrate (`AlterModelOptions`), so there are two migrations, both words-only; (2) `settings.UNFOLD` uses dotted paths rather than `build_config()` to avoid importing the admin site at settings time; (3) unfold has one `base` scale for both themes, so the dark font roles reference its dark end rather than a second scale.

**Placeholder scan.** No "TBD"/"TODO"/"similar to". Two steps name a verification the implementer must do against the installed package (the button component's parameters in Task 10; the red text classes in Task 12) and give the fallback to use — those are instructions with both branches written, not gaps. The `refresh` body in Task 11 is shown as "unchanged body with redirect targets changed" because it exists verbatim in the file the implementer edits.

**Type consistency.** `is_rota_admin(request)` / `is_superuser(request)` (Task 1) are the permission callables Task 4 passes; `navigation(request)` and the five static callbacks are the dotted paths Tasks 1 and 3 name; `primary(request=None)`/`base(request=None)` (Task 3) are what `COLORS` names; `IntListCheckboxField(choices, ordered)` and the two forms (Task 5) are what Task 8 assigns; `clinicians_without_a_pattern()` and `unmapped_absence_count()` (Tasks 10–11) are what Task 12 imports; `admin:rota_patternslot_bulk` (Task 10) and `admin:rota_breathesyncrun_status` (Task 11) are what Tasks 4, 6 and 12 reverse.
