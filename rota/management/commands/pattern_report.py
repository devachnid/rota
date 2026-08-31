"""Show each clinician's pattern history — an inspection aid, not a detector.

The bulk editor used to post a stale `effective_from` — normally today — so a
pattern meant for a future date overwrote the live one, and a second save at
the same date updated the first in place. The overwrite produced rows that
look entirely legitimate: the same shape as a deliberate change, and a
clinician whose pattern was set once and never revised looks exactly like a
healthy one. That is exactly why the original values are gone, and exactly
why this command cannot tell you which rows are damage — it can only show
you the history so a human can compare it against what the practice actually
does.

The one genuine signal it does surface: a date whose rows turn sessions off
(`works=False`). That is the shape an overwrite leaves on the sessions it
displaced — but a deliberate reduction looks identical, so it is a place to
look, not a verdict.

Read-only by design. A repair would be inventing data.
"""

from datetime import date

from django.core.management.base import BaseCommand

from rota.models import Clinician, PatternSlot

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Command(BaseCommand):
    help = ("Show each clinician's pattern history for manual review. "
            "Cannot identify damage automatically.")

    def handle(self, *args, **options):
        today = date.today()
        no_pattern = 0
        worth_checking = 0

        self.stdout.write(
            "This cannot identify damage automatically: an overwritten row "
            "looks exactly like a deliberate change, and a pattern set once "
            "and never revised looks exactly like a healthy one. Read each "
            "clinician's history below against what the practice actually "
            "does.\n"
        )

        for clinician in Clinician.objects.order_by("name"):
            rows = list(PatternSlot.objects.filter(
                clinician=clinician).order_by("effective_from", "weekday", "part"))

            self.stdout.write(f"\n{clinician.name} ({clinician.initials})")

            if not rows:
                no_pattern += 1
                self.stdout.write(self.style.WARNING(
                    "  no pattern rows — cannot be scheduled, and approving "
                    "leave will write nothing"))
                continue

            by_date = {}
            for row in rows:
                by_date.setdefault(row.effective_from, []).append(row)

            reducing_dates = []
            for eff, day_rows in sorted(by_date.items()):
                sessions = ", ".join(
                    f"{WEEKDAYS[r.weekday]} {r.part}{'' if r.works else ' off'}"
                    for r in day_rows)
                markers = []
                if eff == today:
                    markers.append("today")
                if any(not r.works for r in day_rows):
                    markers.append("turns sessions off")
                    reducing_dates.append(eff)
                marker = f"  <- {', '.join(markers)}" if markers else ""
                self.stdout.write(f"  {eff}  {sessions}{marker}")

            if reducing_dates:
                worth_checking += 1
                dates = ", ".join(str(d) for d in reducing_dates)
                self.stdout.write(self.style.WARNING(
                    f"  place to look: turns sessions off on {dates} — a "
                    f"deliberate reduction looks identical, so this is not "
                    f"a verdict"))

        self.stdout.write(
            f"\n{no_pattern} clinician(s) with no pattern rows. "
            f"{worth_checking} clinician(s) have a date that turns sessions "
            f"off and are worth checking by hand. Nothing has been changed."
        )
