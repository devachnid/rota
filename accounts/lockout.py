"""What a locked-out request gets back (AXES_LOCKOUT_CALLABLE).

axes swaps the view's response for its own once a request is locked out.
Its default is one template for everything, but the passkey endpoints are
called by the page's script and read JSON: an HTML page there reads as
"Something went wrong (HTTP 429)". So a JSON request gets JSON, in the
{"error": ...} shape every passkey endpoint answers with, and everything
else gets the page that says which ways in still work.
"""

from django.http import JsonResponse
from django.shortcuts import render

STATUS = 429


def lockout_response(request, original_response=None, credentials=None):
    if request.content_type == "application/json":
        return JsonResponse({"error": "Too many wrong attempts. Try again in an hour."},
                            status=STATUS)
    return render(request, "registration/locked_out.html", status=STATUS)
