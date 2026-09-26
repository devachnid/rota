"""What is waiting for the signed-in person, for the nav: swaps awaiting
their answer as the colleague, and — for a rota admin — swaps awaiting
approval. Two small counts per page for a signed-in user, nothing for an
anonymous one. The login landing page is the week grid, so without these
nothing on it says a swap is waiting.

It also names who is signed in, for the account menu in the header. The
clinician row is read here anyway, so the name costs no query of its own.
A login with no clinician — a practice manager, say — is named by the part
of its email before the @: the whole address is 25-plus characters that
pushed a rota admin's header to wrap below 1080px, and it is shown in full
inside the menu."""

from rota.models import Clinician, SwapRequest


def waiting(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    out = {}
    clinician_id, name = (Clinician.objects.filter(user=user)
                          .values_list("id", "name").first() or (None, None))
    out["signed_in_as"] = name or user.email.split("@")[0]
    if clinician_id:
        out["swaps_for_me"] = SwapRequest.objects.filter(
            colleague_id=clinician_id, status=SwapRequest.Status.PROPOSED).count()
    if user.is_rota_admin:
        out["swaps_for_admin"] = SwapRequest.objects.filter(
            status=SwapRequest.Status.ACCEPTED).count()
    return out
