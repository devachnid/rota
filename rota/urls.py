from django.urls import path

from rota.views import grid

urlpatterns = [
    path("rota/", grid.grid, name="grid"),
]
