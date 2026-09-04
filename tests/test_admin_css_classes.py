"""The project's admin templates borrow Tailwind utility classes straight
from unfold's compiled CSS rather than shipping a stylesheet of our own —
so a future unfold upgrade that drops one of those utilities from its
build would silently blank a layout with no test failing. This walks the
four templates that do that, extracts every class token they use, and
checks each one is still a selector in the installed unfold stylesheet.

The project's own `rota-*` classes (defined in static/admin/rota-admin.css,
for the handful of utilities unfold's build does not carry) are excluded —
they were never meant to be found in unfold's CSS.
"""

import re
from pathlib import Path

import pytest
import unfold

ROOT = Path(__file__).resolve().parents[1]
UNFOLD_CSS = (Path(unfold.__file__).resolve().parent
             / "static" / "unfold" / "css" / "styles.css")

TEMPLATES = [
    ROOT / "templates" / "admin" / "index.html",
    ROOT / "templates" / "admin" / "rota" / "patternslot" / "editor.html",
    ROOT / "templates" / "admin" / "rota" / "breathesyncrun" / "status.html",
    ROOT / "rota" / "templates" / "admin" / "rota" / "widgets" / "ordered_checkboxes.html",
]

# Whole {% ... %} and {{ ... }} blocks are dropped before splitting on
# whitespace, so a conditional like class="{% if x %}text-red-600{% endif %}"
# yields the real class token(s) it renders, not template syntax.
_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
_CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"')


def _tokens(path):
    text = path.read_text()
    tokens = []
    for m in _CLASS_ATTR.finditer(text):
        stripped = _TAG.sub(" ", m.group(1))
        for tok in stripped.split():
            if "{{" in tok or "{%" in tok:
                continue
            if tok.startswith("rota-"):
                continue
            tokens.append(tok)
    return tokens


def _as_selector(token):
    # Tailwind escapes ':' and '/' in the class names it emits as CSS
    # selectors: "dark:text-red-500" -> ".dark\:text-red-500",
    # "lg:w-1/2" -> ".lg\:w-1\/2".
    return "." + token.replace(":", r"\:").replace("/", r"\/")


@pytest.fixture(scope="module")
def unfold_css():
    return UNFOLD_CSS.read_text()


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_every_borrowed_class_exists_in_unfolds_css(path, unfold_css):
    tokens = _tokens(path)
    assert tokens, f"no class tokens found in {path.name} — extraction is broken"
    missing = [t for t in tokens if _as_selector(t) not in unfold_css]
    assert not missing, (
        f"{path.name} uses classes not found in unfold's compiled CSS: {missing}"
    )
