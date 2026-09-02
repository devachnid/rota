"""Pull leave from BreatheHR into the rota's overlay.

Run by deploy/rota-breathe.timer every fifteen minutes, and by the
"Refresh now" button on the Breathe sync admin page. --dry-run fetches and
counts without writing, which is how to check a real account's shape.
"""

from django.core.management.base import BaseCommand

from rota.services.breathe import client as breathe_client
from rota.services.breathe import sync


class Command(BaseCommand):
    help = "Read leave from BreatheHR into the overlay the rota displays."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="fetch and count, write nothing")

    def handle(self, *args, dry_run=False, **options):
        client = breathe_client.from_settings()
        if client is None:
            self.stdout.write("Breathe is not configured (BREATHE_API_KEY unset); nothing to do.")
            return
        run = sync.run(client, dry_run=dry_run)
        if not run.ok:
            self.stderr.write(f"Breathe sync failed: {run.error}")
            return
        self.stdout.write(
            f"Breathe sync ok{' (dry run)' if dry_run else ''}: "
            f"{run.n_requests} requests, {run.n_absences} absences, "
            f"{run.n_sicknesses} sicknesses -> {run.n_deduped} after dedup, "
            f"{run.n_unlinked} for unlinked employees")
