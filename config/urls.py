from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from config.views import manifest, offline, service_worker

urlpatterns = [
    path("admin/", admin.site.urls),
    # Root-level and unauthenticated on purpose: a browser fetches the
    # manifest before anyone has signed in.
    path("manifest.webmanifest", manifest, name="manifest"),
    # The worker must sit at the root to control the whole site; the offline
    # page is what it precaches, on the login page before anyone signs in.
    path("sw.js", service_worker, name="service-worker"),
    path("offline/", offline, name="offline"),
    path("accounts/", include("accounts.urls")),
    path("feedback/", include("feedback.urls")),
    path("", include("rota.urls")),
    path("", RedirectView.as_view(url="/rota/", permanent=False)),
]
