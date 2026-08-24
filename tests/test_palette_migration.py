import pytest

from rota import palette
from rota.models import SessionType
from tests.factories import make_session_type

pytestmark = pytest.mark.django_db


def test_colour_field_accepts_a_tint_key():
    st = make_session_type("Duty")
    st.colour = "teal-strong"
    st.full_clean()
    st.save()
    st.refresh_from_db()
    assert st.colour == "teal-strong"


def test_colour_field_rejects_raw_hex():
    st = make_session_type("Duty")
    st.colour = "#8ecae6"
    with pytest.raises(Exception):
        st.full_clean()


def test_tint_property_resolves():
    st = make_session_type("Duty")
    st.colour = "teal-strong"
    assert st.tint.bg == palette.TINTS["teal-strong"].bg
    assert st.tint.fg == palette.TINTS["teal-strong"].fg


def test_tint_property_falls_back_for_unknown_key():
    st = make_session_type("Duty")
    SessionType.objects.filter(pk=st.pk).update(colour="not-a-tint")
    st.refresh_from_db()
    assert st.tint is palette.TINTS[palette.DEFAULT_TINT]


def test_factory_default_is_a_valid_tint():
    st = make_session_type("Routine")
    assert st.colour in palette.TINTS


def test_legacy_hex_maps_to_a_sensible_tint():
    """The mapping function the data migration uses, exercised directly.

    Exact keys, derived from the OKLCH hue angle of each input against the
    declared angles in palette.HUES. This test used to accept any of five
    adjacent families per input — a 72 deg window, wide enough to pass while
    the function was off by 43 deg and never looked at hue at all.
    """
    # #c1121f is H=25.9: red(18) is 7.9 away, vermilion(36) is 10.1.
    assert palette.nearest_tint("#c1121f") == "red-strong"
    # #2d6a4f is H=162.2: jade(162) is 0.2 away, teal(180) is 17.8.
    assert palette.nearest_tint("#2d6a4f") == "jade-strong"


def _migration(name, *attrs):
    return __import__(f"rota.migrations.{name}", fromlist=list(attrs))


def test_migration_round_trips_awkward_values():
    """Forward then reverse restores any row that carried a real value.

    Awkward inputs included: a normal hex, a hex with no leading '#', and a
    malformed string. The genuinely-blank row is deliberately excluded — see
    test_reverse_cannot_restore_an_originally_blank_colour.
    """
    from django.apps import apps as django_apps
    m = _migration("0015_map_legacy_colours", "to_tints", "back_to_hex")

    # Pre-migration colour was max_length=7, so values are constrained to that.
    st1 = SessionType.objects.create(name="Normal", code="NRM", category="CLINICAL", colour="#ff0000")
    st2 = SessionType.objects.create(name="NoHash", code="NOH", category="CLINICAL", colour="8ecae6")
    st3 = SessionType.objects.create(name="Malformed", code="MAL", category="CLINICAL", colour="badval")
    originals = {st1.pk: "#ff0000", st2.pk: "8ecae6", st3.pk: "badval"}

    m.to_tints(django_apps, None)
    m.back_to_hex(django_apps, None)

    for st in (st1, st2, st3):
        st.refresh_from_db()
        assert st.colour == originals[st.pk], \
            f"Row {st.pk} did not round-trip: expected {originals[st.pk]!r}, got {st.colour!r}"


def test_reverse_preserves_rows_the_forward_migration_never_captured():
    """The reverse must not blank rows it has no legacy hex for.

    `to_tints` skips rows already holding a tint key and, on a fresh install,
    runs against an empty table — so every row created afterwards has
    legacy_colour="". Assigning that unconditionally set colour="" on all of
    them, which is not even a valid choice for the field.
    """
    from django.apps import apps as django_apps
    m = _migration("0015_map_legacy_colours", "to_tints", "back_to_hex")

    # A row created *after* the forward migration ran.
    m.to_tints(django_apps, None)
    st = SessionType.objects.create(
        name="Added later", code="LATER", category="CLINICAL", colour="teal-strong"
    )
    assert st.legacy_colour == ""

    m.back_to_hex(django_apps, None)

    st.refresh_from_db()
    assert st.colour == "teal-strong"


def test_reverse_cannot_restore_an_originally_blank_colour():
    """The one case the reverse is honestly lossy about, pinned deliberately.

    legacy_colour="" is ambiguous: it means either "this row's original colour
    was blank" or "this row was never captured". 0015 did not record enough to
    tell them apart and that information is unrecoverable from an already
    migrated database, so the reverse has to pick one reading.

    It picks "never captured", because the alternative blanks the colour of
    every session type added since deploy. A formerly blank row is left at the
    tint the forward pass gave it — which for a blank input is DEFAULT_TINT,
    the field's own default, and "" was never a valid value for the post-0014
    field anyway. That is the cheaper of the two errors, not a free one.
    """
    from django.apps import apps as django_apps
    m = _migration("0015_map_legacy_colours", "to_tints", "back_to_hex")

    st = SessionType.objects.create(name="Empty", code="EMP", category="CLINICAL", colour="")

    m.to_tints(django_apps, None)
    m.back_to_hex(django_apps, None)

    st.refresh_from_db()
    assert st.colour == palette.DEFAULT_TINT


def test_repair_recomputes_colour_from_legacy_hex():
    """0016 replays the mapping with the corrected nearest_tint.

    #eb4034 is H=28.7, so vermilion(36) at 7.3 deg beats red(18) at 10.7. The
    broken function put it on amber-strong — H=72, a 43 deg miss — which is
    the value sitting in the practice's database right now.
    """
    from django.apps import apps as django_apps
    repair = _migration("0016_repair_legacy_colour_mapping", "repair").repair

    st = SessionType.objects.create(
        name="Duty", code="DUTY", category="CLINICAL",
        colour="amber-strong", legacy_colour="#eb4034",
    )

    repair(django_apps, None)

    st.refresh_from_db()
    assert st.colour == "vermilion-strong"


def test_repair_leaves_rows_without_a_legacy_hex_alone():
    """An empty legacy_colour means the colour was chosen deliberately."""
    from django.apps import apps as django_apps
    repair = _migration("0016_repair_legacy_colour_mapping", "repair").repair

    st = SessionType.objects.create(
        name="Chosen", code="CHOSE", category="CLINICAL",
        colour="lime-soft", legacy_colour="",
    )

    repair(django_apps, None)

    st.refresh_from_db()
    assert st.colour == "lime-soft"


def test_repair_is_idempotent():
    """Running it twice must land on the same keys and not touch legacy_colour."""
    from django.apps import apps as django_apps
    repair = _migration("0016_repair_legacy_colour_mapping", "repair").repair

    rows = [
        SessionType.objects.create(name="Duty", code="DUTY", category="CLINICAL",
                                   colour="amber-strong", legacy_colour="#eb4034"),
        SessionType.objects.create(name="Routine", code="RTN", category="CLINICAL",
                                   colour="cyan-strong", legacy_colour="#8ecae6"),
        SessionType.objects.create(name="Junk", code="JUNK", category="CLINICAL",
                                   colour="slate-soft", legacy_colour="badval"),
    ]

    repair(django_apps, None)
    once = {st.pk: (st.colour, st.legacy_colour)
            for st in SessionType.objects.filter(pk__in=[r.pk for r in rows])}

    repair(django_apps, None)
    twice = {st.pk: (st.colour, st.legacy_colour)
             for st in SessionType.objects.filter(pk__in=[r.pk for r in rows])}

    assert once == twice
    assert once[rows[0].pk] == ("vermilion-strong", "#eb4034")
    assert once[rows[1].pk] == ("azure-strong", "#8ecae6")
    assert once[rows[2].pk] == (palette.DEFAULT_TINT, "badval")


def test_repair_reverse_is_a_documented_no_op():
    """Reversing 0016 must not invent data, and must leave 0015 able to work.

    It cannot restore the broken keys without re-implementing the bug, and it
    does not need to: legacy_colour is untouched, so reversing on past 0015
    still recovers the original hex.
    """
    from django.apps import apps as django_apps
    m = _migration("0016_repair_legacy_colour_mapping", "repair", "unrepair")

    st = SessionType.objects.create(
        name="Duty", code="DUTY", category="CLINICAL",
        colour="amber-strong", legacy_colour="#eb4034",
    )

    m.repair(django_apps, None)
    m.unrepair(django_apps, None)

    st.refresh_from_db()
    assert st.colour == "vermilion-strong"
    assert st.legacy_colour == "#eb4034"

    # And 0015's reverse still gets all the way back to the original hex.
    _migration("0015_map_legacy_colours", "back_to_hex").back_to_hex(django_apps, None)
    st.refresh_from_db()
    assert st.colour == "#eb4034"


def test_repair_fixes_every_row_in_the_practice_database():
    """End to end over the practice's actual pre-migration values.

    These are the nine rows as they exist in db.sqlite3, with the keys 0015's
    broken mapping wrote. Expected keys derived from each input's hue angle.
    """
    from django.apps import apps as django_apps
    repair = _migration("0016_repair_legacy_colour_mapping", "repair").repair

    real = [
        # name,           legacy hex,  broken key,     corrected key
        ("Routine",       "#8ecae6", "cyan-strong",  "azure-strong"),
        ("Duty",          "#eb4034", "amber-strong", "vermilion-strong"),
        ("Urgent",        "#eba134", "yellow-strong", "amber-strong"),
        ("Annual Leave",  "#eba134", "yellow-strong", "amber-strong"),
        ("VTS",           "#8ecae6", "cyan-strong",  "azure-strong"),
    ]
    for i, (name, legacy, broken, _) in enumerate(real):
        SessionType.objects.create(name=name, code=f"C{i}", category="CLINICAL",
                                   colour=broken, legacy_colour=legacy)

    repair(django_apps, None)

    for name, _, _, corrected in real:
        assert SessionType.objects.get(name=name).colour == corrected, name

    # Duty and Annual Leave were one hue family apart before; now they are two,
    # which is the complaint that started this.
    duty = SessionType.objects.get(name="Duty").colour.rsplit("-", 1)[0]
    leave = SessionType.objects.get(name="Annual Leave").colour.rsplit("-", 1)[0]
    angles = dict(palette.HUES)
    assert palette.hue_distance(angles[duty], angles[leave]) >= 36
