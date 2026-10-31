"""Read GP leave from Shift Central into the rota's time-off overlay.

Run by deploy/rota-shift-central.timer every fifteen minutes, and by the
"Refresh now" button on the sync admin page. --dry-run fetches and counts
without writing.
"""

from django.core.management.base import BaseCommand

from rota.services.shift_central import client as sc_client
from rota.services.shift_central import sync


class Command(BaseCommand):
    help = "Read GP leave from Shift Central into the overlay the rota displays."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="fetch and count, write nothing")

    def handle(self, *args, dry_run=False, **options):
        client = sc_client.from_settings()
        if client is None:
            self.stdout.write("Shift Central is not configured (SHIFT_CENTRAL_URL or "
                              "SHIFT_CENTRAL_TOKEN unset); nothing to do.")
            return
        run = sync.run(client, dry_run=dry_run)
        if not run.ok:
            self.stderr.write(f"Shift Central sync failed: {run.error}")
            return
        self.stdout.write(
            f"Shift Central sync ok{' (dry run)' if dry_run else ''}: "
            f"{run.n_records} records, {run.n_matched} clinicians matched, "
            f"{run.n_unmatched} emails unmatched, {run.n_outside} outside the window")
