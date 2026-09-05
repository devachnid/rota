"""What is waiting for the signed-in person, for the nav: swaps awaiting
their answer as the colleague, and — for a rota admin — swaps awaiting
approval. Two small counts per page for a signed-in user, nothing for an
anonymous one. The login landing page is the week grid, so without these
nothing on it says a swap is waiting."""

from rota.models import Clinician, SwapRequest


def waiting(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    out = {}
    clinician_id = Clinician.objects.filter(user=user).values_list("id", flat=True).first()
    if clinician_id:
        out["swaps_for_me"] = SwapRequest.objects.filter(
            colleague_id=clinician_id, status=SwapRequest.Status.PROPOSED).count()
    if user.is_rota_admin:
        out["swaps_for_admin"] = SwapRequest.objects.filter(
            status=SwapRequest.Status.ACCEPTED).count()
    return out
