from django.urls import path

from rota.views import edit, grid

urlpatterns = [
    path("rota/", grid.grid, name="grid"),
    path("rota/cell/<int:clinician_id>/<str:day>/<str:part>/",
         edit.cell_form, name="cell-form"),
    path("rota/assign/", edit.assign, name="assign"),
    path("rota/clear/", edit.clear, name="clear"),
    path("rota/publish/", edit.publish, name="publish"),
    path("rota/daynote/save/", edit.daynote_save, name="daynote-save"),
    path("rota/daynote/<str:day>/", edit.daynote_form, name="daynote-form"),
    path("rota/locum/new/", edit.locum_new, name="locum-new"),
    path("rota/locum/<int:pk>/form/", edit.locum_form, name="locum-form"),
    path("rota/locum/save/", edit.locum_save, name="locum-save"),
]
