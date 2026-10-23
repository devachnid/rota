"""Pull time off from FindMyShift into the rota's overlay.

Run by deploy/rota-findmyshift.timer every fifteen minutes, and by the
"Refresh now" button on the FindMyShift sync admin page. --dry-run fetches
and counts without writing; --inspect prints the shape of what the account
sends — field names and the reasons in use, never a value — which is how to
check a real account before the first sync.
"""

from django.core.management.base import BaseCommand

from rota.services.findmyshift import client as fms_client
from rota.services.findmyshift import sync


class Command(BaseCommand):
    help = "Read time off from FindMyShift into the overlay the rota displays."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="fetch and count, write nothing")
        parser.add_argument("--inspect", action="store_true",
                            help="print the field names and reasons the account "
                                 "sends, write nothing")

    def handle(self, *args, dry_run=False, inspect=False, **options):
        client = fms_client.from_settings()
        if client is None:
            self.stdout.write("FindMyShift is not configured (FINDMYSHIFT_API_KEY unset); "
                              "nothing to do.")
            return
        if inspect:
            try:
                self.stdout.write(sync.inspect(client))
            except Exception as e:  # the point is to see what went wrong
                self.stderr.write(f"inspect failed: {sync._redacted(f'{type(e).__name__}: {e}')}")
            return
        run = sync.run(client, dry_run=dry_run)
        if not run.ok:
            self.stderr.write(f"FindMyShift sync failed: {run.error}")
            return
        self.stdout.write(
            f"FindMyShift sync ok{' (dry run)' if dry_run else ''}: "
            f"{run.n_records} records from {run.n_teams} team{'s' if run.n_teams != 1 else ''}, "
            f"{run.n_approved} approved -> {run.n_deduped} after dedup, "
            f"{run.n_unlinked} for unlinked staff")
