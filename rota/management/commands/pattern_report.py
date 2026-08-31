"""Show each clinician's pattern history, and flag what looks like damage.

The bulk editor used to post a stale `effective_from` — normally today — so a
pattern meant for a future date overwrote the live one, and a second save at
the same date updated the first in place. The original values are gone; this
reports what is there so it can be re-entered through the fixed editor.

Read-only by design. A repair would be inventing data.
"""

from datetime import date

from django.core.management.base import BaseCommand

from rota.models import Clinician, PatternSlot

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Command(BaseCommand):
    help = "Report each clinician's pattern history and flag likely damage."

    def handle(self, *args, **options):
        today = date.today()
        flagged = 0

        for clinician in Clinician.objects.order_by("name"):
            rows = list(PatternSlot.objects.filter(
                clinician=clinician).order_by("effective_from", "weekday", "part"))

            self.stdout.write(f"\n{clinician.name} ({clinician.initials})")

            if not rows:
                flagged += 1
                self.stdout.write(self.style.WARNING(
                    "  no pattern rows — cannot be scheduled, and approving "
                    "leave will write nothing"))
                continue

            by_date = {}
            for row in rows:
                by_date.setdefault(row.effective_from, []).append(row)

            for eff, day_rows in sorted(by_date.items()):
                sessions = ", ".join(
                    f"{WEEKDAYS[r.weekday]} {r.part}{'' if r.works else ' off'}"
                    for r in day_rows)
                marker = "  <- today" if eff == today else ""
                self.stdout.write(f"  {eff}  {sessions}{marker}")

            notes = []
            if len(by_date) == 1:
                notes.append("entire history sits at a single date")
            if today in by_date:
                notes.append("has rows dated today")
            if notes:
                flagged += 1
                self.stdout.write(self.style.WARNING(
                    "  suspect: " + "; ".join(notes)))

        self.stdout.write(
            f"\n{flagged} clinician(s) flagged. Nothing has been changed."
        )
