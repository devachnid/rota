"""The login lockout's counting, changed in two places from axes' own.

axes records each failure against a (username, address) row and, by
default, counts two things: failures for the username, and failures from
the address. On a successful login it deletes every row matching the
username *or the address* (AXES_RESET_ON_SUCCESS). That second half was
the hole: anyone with an account could guess a colleague's password four
times, sign in to their own account from the same address — which deleted
the colleague's rows too — and go again, for ever.

So:

- A successful login clears the signed-in person's own rows, and nobody
  else's. Knowing your own password says nothing about anyone else's.

- The address counts *accounts*, not failures: an address is locked once
  failures against AXES_FAILURE_LIMIT different accounts are outstanding
  there. The address check exists to stop one source spraying many
  accounts, and that is what it now measures. It is also what keeps a
  practice behind one NAT address usable without the old blanket reset:
  one GP fumbling four times counts once there, and each person's own
  success clears their own failures, so the building only locks when five
  different people have failed and not yet got in.

Failures against one account still lock that account after the limit, from
any address — that half is unchanged.
"""

from axes.attempts import get_cool_off_threshold
from axes.handlers.database import AxesDatabaseHandler
from axes.helpers import get_client_username
from axes.models import AccessAttempt
from django.conf import settings
from django.db.models import Sum


class RotaAxesHandler(AxesDatabaseHandler):

    def _live(self, request):
        attempts = AccessAttempt.objects.all()
        if settings.AXES_COOLOFF_TIME is not None:
            attempts = attempts.filter(attempt_time__gte=get_cool_off_threshold(request))
        return attempts

    def get_failures(self, request, credentials=None) -> int:
        live = self._live(request)
        username = get_client_username(request, credentials)
        for_account = 0
        if username is not None:
            for_account = (live.filter(username=username)
                           .aggregate(n=Sum("failures_since_start"))["n"] or 0)
        accounts_from_address = (live.filter(ip_address=request.axes_ip_address)
                                 .values("username").distinct().count())
        return max(for_account, accounts_from_address)

    def reset_user_attempts(self, request, credentials=None) -> int:
        """Called on a successful login (AXES_RESET_ON_SUCCESS): this
        person's rows, from every address, and no one else's."""
        username = get_client_username(request, credentials)
        if username is None:
            return 0
        count, _ = AccessAttempt.objects.filter(username=username).delete()
        return count
