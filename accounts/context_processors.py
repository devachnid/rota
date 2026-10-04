from . import recent_auth


def signed_in_recently(request):
    """For the "add a passkey" offer in base.html, which is made only in the
    minutes after signing in — the one time adding a passkey needs no
    password (accounts/recent_auth.py). Later, the Account page adds one,
    and asks for the password there."""
    user = getattr(request, "user", None)
    return {"signed_in_recently": bool(user and user.is_authenticated
                                       and recent_auth.is_recent(request))}
