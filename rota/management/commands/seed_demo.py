"""Seed the GP side of a shared fictional practice, for a STAGING box.

    manage.py seed_demo --email-base tom@example.org --yes-this-is-staging

Three fictional GPs, the practice setup the Setup card asks for, working
patterns, and published rota entries for this week and the next eight. The
HR system and Shift Central have seeds of their own for the same three
people; every login email here follows their rule, `<local>+<first>.<last>@
<domain>` with the first and last name lower-cased (tom@example.org gives
tom+priya.nair@example.org), because Shift Central matches the sessions feed
to people by email and all the mail lands in the one inbox.

Rules it keeps, because it is pointed at a database somebody cares about:

- It runs only when both `--email-base` and `--yes-this-is-staging` are given.
- It refuses, changing nothing, if the database holds any clinician outside
  the three (or if a cast member already has a login under another email).
- It only ever creates. Everything is found by name (or by its cell) first
  and left exactly as it is when it is there, so a second run with the same
  base changes nothing; a later run adds only the weeks that have come
  into the window since.
- It sends no email. Nothing it calls sends any (the logins get an unusable
  password and no invitation), and the mail backend is swapped for the
  in-memory one for the length of the run as well, so a relay named in
  EMAIL_* could not be reached even by a mistake.
- One transaction: all of it, or none.

It writes no trainees, commitments, personal requirements, locums or time off.
Leave belongs to Shift Central (docs/admin/shift-central.md). Never run it on
production; to clear it, delete the staging database.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.test.utils import override_settings

from accounts.models import User
from rota import palette
from rota.admin_dashboard import setup_steps
from rota.models import (ClosedDay, Clinician, ClinicianGroup, CoverageRule,
                         PatternSlot, PracticeSettings, RotaEntry, SessionType,
                         Site)
from rota.services import entries as entries_svc
from rota.services import patterns as patterns_svc

# Long enough ago to be in force for every day the rota shows.
PATTERN_FROM = date(2020, 1, 1)
WEEKS = 9  # this week and the next eight
SITE = "Main Surgery"
FILL_REASON = "demo data"
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"

AM, PM = "AM", "PM"
CLINICAL = SessionType.Category.CLINICAL
NON_CLINICAL = SessionType.Category.NON_CLINICAL
ABSENCE = SessionType.Category.ABSENCE


@dataclass(frozen=True)
class Gp:
    first: str
    last: str
    initials: str
    group: str
    order: int
    pattern: frozenset  # {(weekday, part)}, Monday = 0
    duty_weekday: int   # the day of the week this GP is duty doctor, when it is their week

    @property
    def name(self):
        return f"Dr {self.first} {self.last}"

    def email(self, base):
        local, domain = base.split("@")
        return f"{local}+{self.first.lower()}.{self.last.lower()}@{domain}"


def _slots(days, parts=(AM, PM)):
    return {(d, p) for d in days for p in parts}


# Priya: 8 sessions, Mon-Thu, all day. Callum: 6, with Thursday morning and
# Friday afternoon on their own. Helen: 5, Wednesday all day, Thursday
# afternoon, Friday all day. Between them every session has a clinician, and
# every one has two but Friday morning.
CAST = (
    Gp("Priya", "Nair", "PN", "Partners", 10, frozenset(_slots(range(0, 4))), 1),
    Gp("Callum", "Ross", "CR", "Salaried", 10,
       frozenset(_slots((0, 1)) | {(3, AM), (4, PM)}), 0),
    Gp("Helen", "Okafor", "HO", "Salaried", 20,
       frozenset(_slots((2, 4)) | {(3, PM)}), 2),
)

GROUPS = (  # name, display_order, is_locum_group
    ("Partners", 10, False),
    ("Salaried", 20, False),
    ("Locums", 90, True),
)

# key -> name, code, category, tint, extra fields. Codes are at most six
# characters, which is what the grid chip can print.
SESSION_TYPES = {
    "morning": ("Morning surgery", "MORN", CLINICAL, "sky-soft", {}),
    "afternoon": ("Afternoon surgery", "AFTN", CLINICAL, "sky-strong", {}),
    "duty": ("Duty doctor", "DUTY", CLINICAL, "orange-strong",
             {"fairness_tracked": True, "pin_on_day_view": True,
              "max_per_session": 1}),
    "admin": ("Admin", "ADMIN", NON_CLINICAL, palette.DEFAULT_TINT, {}),
    "home": ("Home visits", "HV", CLINICAL, "emerald-soft", {}),
}


def validate_base(base):
    """The base is `local@domain`, with no `+` already: the command adds the
    tag, and a second one would no longer match what the other seeds make."""
    if base.count("@") != 1:
        raise CommandError("--email-base must contain exactly one @, as in tom@example.org.")
    if "+" in base:
        raise CommandError("--email-base must not already contain a +; the command adds the +first.last tag itself.")
    local, domain = base.split("@")
    if not local or not domain or any(c.isspace() for c in base):
        raise CommandError("--email-base must look like local@domain, with no spaces.")
    try:
        for gp in CAST:
            validate_email(gp.email(base))
    except ValidationError:
        raise CommandError(f"--email-base {base!r} does not make valid email addresses.")


class Command(BaseCommand):
    help = ("Seed three fictional GPs, the practice setup and nine weeks of "
            "published rota, for a STAGING box. Sends no email.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--email-base",
            help="local@domain; each GP logs in as local+first.last@domain")
        parser.add_argument(
            "--yes-this-is-staging", action="store_true",
            help="confirm this is a staging database, never production")

    def handle(self, *args, email_base=None, yes_this_is_staging=False, **options):
        missing = []
        if not email_base:
            missing.append("--email-base")
        if not yes_this_is_staging:
            missing.append("--yes-this-is-staging")
        if missing:
            raise CommandError(
                f"Refusing to run without {' and '.join(missing)}. This command "
                "writes fictional people and a nine-week rota, and is for a "
                "staging database only: pass --email-base local@domain and "
                "--yes-this-is-staging. Nothing was changed.")
        validate_base(email_base)

        stranger_count = Clinician.objects.exclude(
            name__in=[gp.name for gp in CAST]).count()
        if stranger_count:
            raise CommandError(
                f"Refusing to run: the database already holds {stranger_count} "
                f"clinician{'s' if stranger_count != 1 else ''} outside the demo cast. "
                "This is a staging-only command for an empty or demo-only database. "
                "Nothing was changed.")

        # Nothing here sends mail, and this makes sure of it: whatever EMAIL_*
        # names, the backend for this run is the in-memory one.
        with override_settings(EMAIL_BACKEND=LOCMEM), transaction.atomic():
            self.seed(email_base)

    # ------------------------------------------------------------------

    def seed(self, base):
        made = {}

        def note(label, created):
            made.setdefault(label, [0, 0])[0 if created else 1] += 1

        self._check_logins(base)
        site = self._site(note)
        groups = self._groups(note)
        types = self._session_types(site, note)
        self._practice_settings(types["admin"], note)
        self._coverage_rules(types, note)
        clinicians = self._clinicians(base, groups, note)
        self._patterns(clinicians, note)
        self._rota(clinicians, types, site, note)

        self.stdout.write("Demo data for the staging box (created / already there):")
        for label, (created, existing) in made.items():
            self.stdout.write(f"  {label}: {created} / {existing}")
        self.stdout.write("Logins (unusable password, no invitation sent, no email sent):")
        for gp in CAST:
            self.stdout.write(f"  {gp.name}: {gp.email(base)}")
        self.stdout.write("Setup card:")
        for step in setup_steps()["steps"]:
            self.stdout.write(f"  [{'x' if step['done'] else ' '}] {step['title']}")

    # -- pre-flight ------------------------------------------------------

    def _check_logins(self, base):
        """A cast member who already has a login under another address means
        the box was seeded with another base; shifting it would break the
        match with the other seeds, and changing a login is not ours to do."""
        for gp in CAST:
            email = gp.email(base)
            clinician = Clinician.objects.filter(name=gp.name).select_related("user").first()
            if clinician and clinician.user and clinician.user.email.lower() != email.lower():
                raise CommandError(
                    f"{gp.name} already has a login under a different email "
                    "(this box was seeded with another --email-base). "
                    "Nothing was changed.")
            holder = User.objects.filter(email__iexact=email).select_related("clinician").first()
            owner = getattr(holder, "clinician", None) if holder else None
            if owner is not None and owner.name != gp.name:
                raise CommandError(
                    f"The login {email} already belongs to another clinician. "
                    "Nothing was changed.")

    # -- setup -----------------------------------------------------------

    def _site(self, note):
        site, created = Site.objects.get_or_create(name=SITE)
        note("sites", created)
        return site

    def _groups(self, note):
        groups = {}
        have_locum_group = ClinicianGroup.objects.filter(is_locum_group=True).exists()
        for name, order, is_locum in GROUPS:
            if is_locum and have_locum_group:
                note("clinician groups", False)  # exactly one may exist, and one does
                continue
            group, created = ClinicianGroup.objects.get_or_create(
                name=name, defaults={"display_order": order, "is_locum_group": is_locum})
            note("clinician groups", created)
            groups[name] = group
        return groups

    def _session_types(self, site, note):
        types = {}
        for key, (name, code, category, tint, extra) in SESSION_TYPES.items():
            st, created = SessionType.objects.get_or_create(
                name=name,
                defaults={"code": code, "category": category, "colour": tint,
                          "default_site": site, **extra})
            note("session types", created)
            types[key] = st
        # The Setup card wants an absence type. Migrations seed three; this
        # only matters on a database where they were deleted.
        if not SessionType.objects.filter(category=ABSENCE).exists():
            _, created = SessionType.objects.get_or_create(
                name="Annual leave",
                defaults={"code": "AL", "category": ABSENCE, "colour": "neutral-strong"})
            note("session types", created)
        return types

    def _practice_settings(self, admin_type, note):
        # Three GPs cannot put two clinical GPs in every session (that is 20
        # sessions for 10 slots, and they have 19), so a fresh practice
        # starts with a floor of one. A settings row somebody already has is
        # theirs: only its empty default-fill type is filled in.
        ps, created = PracticeSettings.objects.get_or_create(
            pk=1, defaults={"min_clinical_per_session": 1,
                            "default_fill_session_type": admin_type})
        if not created and ps.default_fill_session_type_id is None:
            ps.default_fill_session_type = admin_type
            ps.save(update_fields=["default_fill_session_type"])
            created = True
        note("practice settings", created)

    def _coverage_rules(self, types, note):
        # Per-slot rules are what the grid warns on, so they ask for one of
        # each surgery and no more. Duty is a quota (one full day a week),
        # which the grid does not warn on: three GPs cannot staff a duty
        # doctor in every session of every day.
        rules = (
            (types["duty"], dict(unit=CoverageRule.Unit.PER_DAY,
                                 frequency=CoverageRule.Frequency.PER_WEEK, parts="BOTH"),
             dict(count=2, priority=10, weekdays="0,1,2,3,4", preferred_weekdays="1,0,2")),
            (types["morning"], dict(unit=CoverageRule.Unit.PER_SESSION,
                                    frequency=CoverageRule.Frequency.PER_SLOT, parts=AM),
             dict(count=1, priority=50, weekdays="0,1,2,3,4")),
            (types["afternoon"], dict(unit=CoverageRule.Unit.PER_SESSION,
                                      frequency=CoverageRule.Frequency.PER_SLOT, parts=PM),
             dict(count=1, priority=60, weekdays="0,1,2,3,4")),
        )
        for st, key, defaults in rules:
            _, created = CoverageRule.objects.get_or_create(
                session_type=st, defaults=defaults, **key)
            note("coverage rules", created)

    # -- people ----------------------------------------------------------

    def _clinicians(self, base, groups, note):
        clinicians = {}
        for gp in CAST:
            email = gp.email(base)
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                # No password and no invitation: create_user with password None
                # stores an unusable one, and nothing is sent.
                user = User.objects.create_user(email=email, password=None)
                note("logins", True)
            else:
                note("logins", False)
            clinician = Clinician.objects.filter(name=gp.name).first()
            if clinician is None:
                clinician = Clinician.objects.create(
                    name=gp.name, initials=gp.initials, group=groups[gp.group],
                    display_order=gp.order, user=user)
                note("clinicians", True)
            else:
                if clinician.user_id is None:
                    clinician.user = user
                    clinician.save(update_fields=["user"])
                note("clinicians", False)
            clinicians[gp.first] = clinician
        return clinicians

    def _patterns(self, clinicians, note):
        for gp in CAST:
            clinician = clinicians[gp.first]
            # A clinician with any pattern at all has one somebody chose.
            if PatternSlot.objects.filter(clinician=clinician).exists():
                note("working patterns", False)
                continue
            patterns_svc.bulk_set_pattern(
                clinician, PATTERN_FROM, {slot: True for slot in gp.pattern})
            note("working patterns", True)

    # -- the rota --------------------------------------------------------

    def _rota(self, clinicians, types, site, note):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        closed = set(ClosedDay.objects.values_list("day", flat=True))
        for week in range(WEEKS):
            start = monday + timedelta(days=7 * week)
            # Whose duty week it is follows the calendar, not the day the
            # command ran, so a later run carries the rotation on.
            duty = CAST[(start.toordinal() // 7) % len(CAST)]
            for offset in range(7):
                day = start + timedelta(days=offset)
                if day in closed:
                    continue
                for gp in CAST:
                    clinician = clinicians[gp.first]
                    pattern = patterns_svc.current_pattern(clinician, day)
                    working = [p for p in (AM, PM) if pattern.get((day.weekday(), p))]
                    have = set(RotaEntry.objects.filter(
                        day=day, clinician=clinician).values_list("part", flat=True))
                    for _ in have.intersection(working):
                        note("rota entries", False)
                    mine = [p for p in working if p not in have]
                    if not mine:
                        continue
                    if (gp == duty and day.weekday() == gp.duty_weekday
                            and mine == [AM, PM]):
                        entries_svc.assign_full_day(
                            None, clinician, day, types["duty"], site=site,
                            published=True, fill_reason=FILL_REASON)
                        for _ in mine:
                            note("rota entries", True)
                        continue
                    for part in mine:
                        entries_svc.assign(
                            None, clinician, day, part,
                            types["morning"] if part == AM else types["afternoon"],
                            site=site, published=True, fill_reason=FILL_REASON)
                        note("rota entries", True)
