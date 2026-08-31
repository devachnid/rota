"""Cascade regressions for the declarations that reviews caught being inert.

This branch's repeat failure mode was CSS that *looked* correct and did
nothing: a rule beaten on specificity by another rule in the same sheet, or
defeated by a layout mechanism that ignores the property being set. Four of
those shipped and were caught only by a human reading the cascade. Nobody is
going to read the cascade again, so the six survivors are pinned here.

`tests/test_chrome_contrast.py` already parses these stylesheets to audit
colour; this module parses them the same way to audit the cascade. Each test
asserts a *pairing* — this declaration, on this selector — and, where the fix
only works by beating something else, that the intended selector really does
out-rank the rule it has to beat. Grepping the file for `width: 100%` would
prove nothing; a rule can carry the declaration and still lose.

WHAT THESE TESTS CANNOT PROVE
-----------------------------
There is no browser here. Everything below is read out of the source text and
scored against the cascade rules in the specs (CSS 2.2 §6.4.3 for the order,
Selectors 3 §9 for specificity). That is enough to catch a declaration that is
absent, misplaced onto the wrong selector, or out-ranked — the three ways
these six actually failed. It is *not* enough to prove a browser paints the
result: nothing here renders, measures, or checks that a property has any
visual effect on the box it lands on. `table-layout: fixed` is asserted to be
present and to win; whether the grid then looks right on a 1080p monitor is a
visual check, and it is still outstanding. The parser reads `@media` and
`@supports` bodies and tags each rule inside one with the query text it sits
under, but it does not evaluate that query: whether a rule actually applies
at a given viewport is still not proven by anything here.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS_DIR = ROOT / "static" / "css"

# Cascade order, lowest priority first. Asserted against templates/base.html by
# test_stylesheet_order_matches_base_html below, so re-ordering the <link> tags
# without re-ordering this list is itself a failure.
SHEETS = ["components.css", "screens.css"]


# --------------------------------------------------------------------------
# a very small CSS reader
# --------------------------------------------------------------------------

class Rule:
    """One selector out of one rule, with its declarations and cascade order."""

    def __init__(self, sheet, order, selector, declarations, *, media=None):
        self.sheet = sheet
        self.order = order          # global, across SHEETS in link order
        self.selector = selector
        self.declarations = declarations
        self.media = media          # None at top level, else the @media/@supports query

    def __repr__(self):
        return f"<{self.sheet} #{self.order} {self.selector!r}>"


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _parse(css: str, sheet: str, first_order: int) -> tuple[list[Rule], int]:
    """`selector-list { prop: value; ... }` rules, flat or nested one level
    deep inside an `@media`/`@supports` block.

    `order` IS the cascade (CSS 2.2 §6.4.3), so it has to track document
    position exactly — a block near the end of the sheet must out-rank every
    rule before it, at-rule or not. The sheet is therefore walked once, left
    to right: whatever sits before an at-rule block is parsed (and numbered)
    first, then the block's own body, then whatever follows. Any other
    at-rule — one with no block, like `@import` or `@charset` — is refused
    the same way an unsupported one always was: loudly, rather than quietly
    scoring the cascade wrong.
    """
    rules, order = [], first_order

    def _rulesets(body, media):
        nonlocal order
        assert "@" not in body, (
            f"{sheet} has an at-rule this parser cannot place in the "
            f"cascade; it only handles @media and @supports blocks"
        )
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", body):
            declarations = {}
            for declaration in match.group(2).split(";"):
                if ":" not in declaration:
                    continue
                prop, _, value = declaration.partition(":")
                declarations[prop.strip()] = value.strip()
            for selector in (s.strip() for s in match.group(1).split(",")):
                if selector:
                    rules.append(Rule(sheet, order, selector, declarations,
                                      media=media))
            order += 1

    cursor = 0
    for match in re.finditer(r"@(\w+)([^{]*)\{", css):
        assert match.group(1) in ("media", "supports"), (
            f"{sheet} has an @{match.group(1)} rule; this parser only "
            f"handles @media and @supports"
        )
        _rulesets(css[cursor:match.start()], None)  # top-level, before the block
        depth, i = 1, match.end()
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        _rulesets(css[match.end():i - 1], match.group(2).strip())
        cursor = i
    _rulesets(css[cursor:], None)  # top-level, after the last block (or all of it)

    return rules, order


def _read_all() -> list[Rule]:
    rules, order = [], 0
    for sheet in SHEETS:
        found, order = _parse(
            _strip_comments((CSS_DIR / sheet).read_text()), sheet, order
        )
        rules.extend(found)
    return rules


RULES = _read_all()


def specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes/attributes/pseudo-classes, types/pseudo-elements).

    Selectors 3 §9. Every selector in these two sheets is simple enough to
    score by walking the string; a functional pseudo-class (`:not()`, `:is()`)
    would need its argument scored too, so it raises rather than under-count.
    """
    ids = classes = types = 0
    i, n = 0, len(selector)
    while i < n:
        char = selector[i]
        if char in "#.":
            if char == "#":
                ids += 1
            else:
                classes += 1
            i += 1
        elif char == "[":
            classes += 1
            while i < n and selector[i] != "]":
                i += 1
            i += 1
            continue
        elif char == ":":
            if selector.startswith("::", i):
                types += 1
                i += 2
            else:
                classes += 1
                i += 1
        elif char.isalpha():
            types += 1
        else:  # whitespace, combinator, or the universal selector
            i += 1
            continue
        while i < n and (selector[i].isalnum() or selector[i] in "-_"):
            i += 1
        if i < n and selector[i] == "(":
            raise ValueError(f"functional pseudo-class in {selector!r}")
    return (ids, classes, types)


def rule(selector: str) -> Rule:
    """The one rule written with exactly this selector text.

    Phase 2's `@media (max-width: 640px)` block legitimately repeats a few
    selectors that already had a top-level rule — `body`, `.nav`, and
    `.day-roster td` all now have one rule outside the block and a second,
    narrower-purpose one inside it (padding for the fixed tab bar, hiding
    the desktop nav, an auto width for the day view's cells below the
    breakpoint). `rule()` and `declares()` still assume one match per
    selector, so calling either on any of those three raises "expected
    exactly one rule" — not a bug, just this helper not knowing which of
    the two you mean. Use `_rules_for()` (test_responsive_nav.py) or filter
    RULES directly by `.media` when a test needs one of them.
    """
    found = [r for r in RULES if r.selector == selector]
    assert len(found) == 1, (
        f"expected exactly one rule for {selector!r}, found {found}"
    )
    return found[0]


def declares(selector: str, prop: str) -> str:
    """The value `selector` gives `prop`; fails if the pairing is not there."""
    target = rule(selector)
    assert prop in target.declarations, (
        f"{target} does not declare {prop!r}; it declares "
        f"{sorted(target.declarations)}"
    )
    return target.declarations[prop]


def assert_outranks(winner: str, loser: str, prop: str) -> None:
    """`winner` must beat `loser` for `prop` on an element both of them match.

    Strict specificity is what is asserted, not merely "wins today": all six
    of these are contests the comments in the CSS claim are won outright,
    "whatever the order". A tie broken by source order would still paint
    correctly now and break the moment the sheets are re-ordered or a rule is
    moved, which is precisely the refactor these tests exist to trip.
    """
    assert prop in rule(loser).declarations, (
        f"{loser!r} no longer declares {prop!r} — the contest this asserts has "
        f"moved; re-check what {winner!r} now has to beat"
    )
    assert prop in rule(winner).declarations, f"{winner!r} does not set {prop!r}"
    assert specificity(winner) > specificity(loser), (
        f"{winner!r} {specificity(winner)} does not out-rank {loser!r} "
        f"{specificity(loser)} for {prop!r}"
    )


# --------------------------------------------------------------------------
# the reader itself
# --------------------------------------------------------------------------

def test_stylesheet_order_matches_base_html():
    """SHEETS is the tie-breaker for equal specificity, so it has to be the
    order the browser actually loads them in."""
    base = (ROOT / "templates" / "base.html").read_text()
    linked = re.findall(r"static '?css/([a-z]+\.css)'?", base)
    assert [s for s in linked if s in SHEETS] == SHEETS, linked


@pytest.mark.parametrize("selector,expected", [
    ("*", (0, 0, 0)),
    ("a", (0, 0, 1)),
    (".grid-day", (0, 1, 0)),
    (".table td", (0, 1, 1)),
    (".table-grid thead th", (0, 1, 2)),
    (".table td.empty", (0, 2, 1)),
    (".table-grid .grid-clin", (0, 2, 0)),
    (".table-grid thead th.closed", (0, 2, 2)),
    (".table-grid tr.mine .grid-clin", (0, 3, 1)),
    ("#modal", (1, 0, 0)),
    (".btn:hover", (0, 2, 0)),
])
def test_specificity_scores_the_documented_selectors(selector, expected):
    """Self-check on the scorer. Every number here is one the comments in
    components.css already state; if the scorer and the comments disagree,
    the tests below are measuring nothing."""
    assert specificity(selector) == expected


def test_parser_found_both_sheets():
    for sheet in SHEETS:
        assert any(r.sheet == sheet for r in RULES), sheet


# --------------------------------------------------------------------------
# 1. a closed day reads as closed in the header it is named in
# --------------------------------------------------------------------------

def test_closed_wins_on_a_grid_day_header():
    """`.closed` alone is inert on a <th class="grid-day closed">: the header
    background comes from `.table-grid thead th` and the colour from
    screens.css's `.grid-day`, and both out-rank a bare class."""
    assert declares(".table-grid thead th.closed", "background") == "var(--sunken)"
    assert declares(".table-grid thead th.closed", "color") == "var(--muted)"
    assert_outranks(".table-grid thead th.closed", ".table-grid thead th", "background")
    assert_outranks(".table-grid thead th.closed", ".grid-day", "color")


def test_the_closed_header_matches_the_closed_treatment_elsewhere():
    """A header closed day and a body closed cell have to look like the same
    state, so the restatement must not drift from `.closed` itself."""
    for prop in ("background", "color"):
        assert declares(".table-grid thead th.closed", prop) == declares(".closed", prop)


# --------------------------------------------------------------------------
# 2. an empty state inside a report table
# --------------------------------------------------------------------------

@pytest.mark.parametrize("table", [".table", ".report"])
def test_empty_wins_inside_a_table_cell(table):
    """`<td class="empty">` is a real pairing (report_leave / report_staffing /
    report_trainees / my_schedule). The cell rule sets padding and
    text-align: left on every td, so bare `.empty` lost both and only its
    colour survived."""
    cell_state = f"{table} td.empty"
    assert declares(cell_state, "text-align") == "center"
    assert declares(cell_state, "padding") == "var(--sp-6)"
    assert_outranks(cell_state, f"{table} td", "text-align")
    assert_outranks(cell_state, f"{table} td", "padding")


def test_the_table_empty_state_matches_the_standalone_one():
    """Same empty state, table row or not — `<p class="empty">` on the inbox
    and `<td class="empty">` in a report must not diverge."""
    for prop in ("text-align", "padding"):
        assert declares(".table td.empty", prop) == declares(".empty", prop)


# --------------------------------------------------------------------------
# 3. the signed-in clinician's row highlight
# --------------------------------------------------------------------------

def test_mine_wins_on_the_clinician_cell():
    """`.grid-clin` is sticky and therefore opaque — it paints --surface over
    the `.mine` row background at exactly the cell where the pre-branch design
    put the highlight."""
    assert declares(".table-grid tr.mine .grid-clin", "background") == "var(--accent-soft)"
    assert declares(".table-grid tr.mine .grid-clin", "background") == declares(".mine", "background")
    assert_outranks(".table-grid tr.mine .grid-clin", ".table-grid .grid-clin", "background")


def test_the_clinician_cell_is_still_sticky_and_opaque():
    """The highlight above must not have been won by dropping what makes the
    column work: it is opaque *because* it is sticky, and a transparent sticky
    column shows the rows sliding under it."""
    assert declares(".table-grid .grid-clin", "position") == "sticky"
    assert declares(".table-grid .grid-clin", "left") == "0"
    assert declares(".table-grid .grid-clin", "background") == "var(--surface)"


# --------------------------------------------------------------------------
# 4. .main has a definite width
# --------------------------------------------------------------------------

def test_main_has_an_explicit_width():
    """body is a flex column and `.main` has `margin: 0 auto`, so per Flexbox
    §9.6 step 11 it is not stretched to the line's cross size — without an
    explicit width it sizes fit-content. The two declarations only make sense
    together, so both are pinned."""
    assert declares(".main", "width") == "100%"
    assert declares(".main", "margin") == "0 auto"
    assert declares(".main", "max-width") == "1280px"


# --------------------------------------------------------------------------
# 5. the grid's column widths
# --------------------------------------------------------------------------

def test_the_grid_uses_fixed_table_layout():
    """Under auto layout one 300-char day note sizes its whole column, and
    `.chip`'s ellipsis can never fire because white-space: nowrap sets the
    cell's min-content width to the chip's full text."""
    assert declares(".table-grid", "table-layout") == "fixed"
    assert declares(".table-grid", "width") == "100%"


def test_only_the_clinician_column_is_given_a_width():
    """The regression that motivated the min-width below. Fixed layout splits
    surplus table width proportionally among columns that have a width, and
    equally among those that do not (CSS 2.2 §17.5.2.1). With a width on both
    `.grid-clin` and `.grid-day` there were no auto columns left, so a 560px
    surplus on a 1080p screen went out 88/648 to the initials column — pushing
    a two-letter initial to ~164px — instead of splitting evenly over the ten
    session columns. Leaving the day columns auto is the whole fix, so any
    rule that re-introduces a width on one fails here."""
    assert declares(".table-grid .grid-clin", "width") == "5.5rem"
    offenders = [
        r for r in RULES
        if re.search(r"\.grid-(day|part)\b", r.selector)
        and {"width", "min-width", "max-width"} & set(r.declarations)
    ]
    assert not offenders, (
        f"day/session columns must stay auto-width, but {offenders} size them"
    )


def test_the_grid_has_its_horizontal_floor_on_the_table():
    """With the day columns auto there is no per-column floor left, so the
    floor moves to the table: `.grid-wrap` is `overflow: auto`, and a table
    wider than it scrolls sideways inside it. min-width on the *cells* would
    be inert — it is not an input to the fixed-layout algorithm — so the
    declaration has to be on `.table-grid` itself and in a length that does
    not resolve against the wrapper it is supposed to overflow."""
    floor = declares(".table-grid", "min-width")
    assert re.fullmatch(r"[\d.]+rem", floor), floor
    assert float(floor.removesuffix("rem")) >= 40, floor
    wrap = rule(".grid-wrap")
    assert wrap.declarations.get("overflow") == "auto", wrap.declarations


# --------------------------------------------------------------------------
# 6. the pinned header is opaque
# --------------------------------------------------------------------------

def test_the_sticky_header_is_backed_on_both_the_thead_and_its_cells():
    """`position: sticky` does not create a paint layer that hides anything —
    rows scroll *under* the pinned header and show through any transparent
    part of it. border-spacing: 2px leaves a gap between the two header rows
    that the th backgrounds do not cover, so <thead> carries one too."""
    assert declares(".table-grid thead", "position") == "sticky"
    assert declares(".table-grid thead", "background") == "var(--surface)"
    assert declares(".table-grid thead th", "background") == "var(--surface)"


def test_the_header_background_token_is_opaque_in_every_theme():
    """"Has a background" is only half the requirement — a translucent token
    would satisfy the assertion above and still let rows show through. All
    three theme blocks are checked because a token defined in only one of them
    is this project's other standing failure mode."""
    tokens = _strip_comments((CSS_DIR / "tokens.css").read_text())
    values = re.findall(r"--surface:\s*([^;]+);", tokens)
    assert len(values) == 3, values  # :root, prefers-color-scheme, [data-theme]
    for value in values:
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()), value


# --------------------------------------------------------------------------
# the parser itself
# --------------------------------------------------------------------------

def test_parser_reads_rules_inside_a_media_block():
    """Phase 2 adds the first @media block to these sheets.

    The parser used to refuse at-rules outright, on the grounds that a naive
    brace-matcher would read `@media (max-width: 640px) {` as a selector and
    score the cascade wrong. It now reads them properly: rules inside the
    block are real rules, tagged with the query they sit under.
    """
    css = ".a { color: red; }\n@media (max-width: 640px) {\n  .b { color: blue; }\n}\n.c { color: green; }"
    rules, _ = _parse(css, "fake.css", 0)
    by_selector = {r.selector: r for r in rules}

    assert set(by_selector) == {".a", ".b", ".c"}
    assert by_selector[".a"].media is None
    assert by_selector[".b"].media == "(max-width: 640px)"
    assert by_selector[".c"].media is None, "a rule after the block is top-level again"
    assert by_selector[".b"].declarations == {"color": "blue"}


def test_rules_are_numbered_in_document_order_across_a_media_block():
    """order IS the cascade. A rule after the block must out-rank one inside
    it, and one before the block must be out-ranked by both."""
    css = ".a{color:red}\n@media (max-width: 640px){.b{color:blue}}\n.c{color:green}"
    rules, _ = _parse(css, "fake.css", 0)
    order = {r.selector: r.order for r in rules}
    assert order[".a"] < order[".b"] < order[".c"]
