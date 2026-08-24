"""The admin guide goes stale silently.

Documentation is the one artefact nothing exercises: a renamed heading breaks
every link pointing at it and no page 500s, no test fails, and the reader finds
out. These check the cheap, mechanical things — that internal links resolve and
that every admin screen is mentioned somewhere — not that the prose is right.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "admin"
MD_FILES = sorted(DOCS.glob("*.md")) + [ROOT / "README.md"]


def _anchor(heading: str) -> str:
    """GitHub's slug rules: lowercase, drop punctuation, then replace each
    whitespace character with a hyphen — individually, not collapsed. A
    heading like "VTS / SDL / X" loses the slash and keeps both surrounding
    spaces, so its anchor really does contain double hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[`*_]", "", s)
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s", "-", s).strip("-")


def _headings(path: Path) -> set[str]:
    return {
        _anchor(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", path.read_text(), re.M)
    }


@pytest.mark.parametrize("path", MD_FILES, ids=lambda p: p.name)
def test_internal_links_resolve(path):
    """Every relative link points at a file that exists, and every #anchor at
    a heading that exists in that file."""
    broken = []
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", path.read_text()):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        if not dest.is_file():
            broken.append(f"{target} -> no such file")
            continue
        if anchor and anchor not in _headings(dest):
            broken.append(f"{target} -> no heading '{anchor}' in {dest.name}")
    assert not broken, f"{path.name} has broken links:\n  " + "\n  ".join(broken)


def test_every_admin_registered_model_is_documented():
    """A model exposed in /admin/ that no page mentions is a setting the
    practice has to work out by trial and error."""
    from django.contrib import admin as dj

    prose = "\n".join(p.read_text() for p in DOCS.glob("*.md")).lower()

    undocumented = []
    for model in dj.site._registry:
        if model._meta.app_label != "rota":
            continue
        # Match on the human-readable name; the guide is written for admins,
        # who see "Coverage rule", not CoverageRule.
        name = model._meta.verbose_name.lower()
        if name not in prose and name.replace(" ", "") not in prose.replace(" ", ""):
            undocumented.append(model.__name__)

    assert not undocumented, (
        "these admin screens are not mentioned anywhere in docs/admin/: "
        + ", ".join(sorted(undocumented))
    )


def test_the_guide_index_links_to_every_page():
    index = (DOCS / "README.md").read_text()
    for page in DOCS.glob("*.md"):
        if page.name == "README.md":
            continue
        assert page.name in index, (
            f"docs/admin/{page.name} exists but the index does not link it"
        )
