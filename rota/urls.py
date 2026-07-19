from django.urls import path

from rota.views import edit, fill, grid, my_schedule, requests as requests_views

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
    path("rota/fill/", fill.fill, name="fill"),
    path("me/", my_schedule.my_schedule, name="my-schedule"),
    path("me/leave/new/", requests_views.leave_new, name="leave-new"),
    path("requests/", requests_views.inbox, name="inbox"),
    path("requests/leave/<int:pk>/approve/", requests_views.leave_approve,
         name="leave-approve"),
    path("requests/leave/<int:pk>/decline/", requests_views.leave_decline,
         name="leave-decline"),
    path("me/swap/new/", requests_views.swap_new, name="swap-new"),
    path("me/swap/<int:pk>/accept/", requests_views.swap_accept, name="swap-accept"),
    path("me/swap/<int:pk>/decline/", requests_views.swap_colleague_decline,
         name="swap-colleague-decline"),
    path("requests/swap/<int:pk>/approve/", requests_views.swap_approve,
         name="swap-approve"),
    path("requests/swap/<int:pk>/decline/", requests_views.swap_decline,
         name="swap-decline"),
]
