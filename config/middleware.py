from django.utils.cache import add_never_cache_headers


class PrivatePagesMiddleware:
    """Signed-in pages are not kept by the browser, and signing out clears
    what it kept.

    The rota is used on shared surgery PCs. A page served with no
    Cache-Control could be shown again from the back button or history after
    the person who opened it had signed out: their schedule, their swap
    messages, the Account page with their email. So every response to a
    signed-in request gets Django's never-cache headers (no-store, private)
    unless the view set its own policy — sw.js and the manifest do. Static
    files never reach here: WhiteNoise answers them earlier in the stack.

    Signing out — the app's logout or the admin's — adds Clear-Site-Data:
    "cache", so a copy stored before this change, or by a browser that kept
    one anyway, goes too. Sits after AuthenticationMiddleware, which gives
    it request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        signed_in = request.user.is_authenticated
        response = self.get_response(request)
        if signed_in and not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        if signed_in and not request.user.is_authenticated:
            response["Clear-Site-Data"] = '"cache"'
        return response
