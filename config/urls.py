from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from config.views import manifest

urlpatterns = [
    path("admin/", admin.site.urls),
    # Root-level and unauthenticated on purpose: a browser fetches the
    # manifest before anyone has signed in.
    path("manifest.webmanifest", manifest, name="manifest"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("rota.urls")),
    path("", RedirectView.as_view(url="/rota/", permanent=False)),
]
