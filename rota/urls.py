from django.urls import path

from rota.views import day, edit, fill, grid, my_schedule, reports, requests as requests_views

urlpatterns = [
    path("rota/", grid.grid, name="grid"),
    path("rota/day/", day.day_view, name="day"),
    path("rota/day/<str:day>/", day.day_view, name="day"),
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
    path("requests/", requests_views.inbox, name="inbox"),
    path("me/swap/new/", requests_views.swap_new, name="swap-new"),
    path("me/swap/<int:pk>/accept/", requests_views.swap_accept, name="swap-accept"),
    path("me/swap/<int:pk>/decline/", requests_views.swap_colleague_decline,
         name="swap-colleague-decline"),
    path("requests/swap/<int:pk>/approve/", requests_views.swap_approve,
         name="swap-approve"),
    path("requests/swap/<int:pk>/decline/", requests_views.swap_decline,
         name="swap-decline"),
    path("reports/fairness/", reports.report_fairness, name="report-fairness"),
    path("reports/staffing/", reports.report_staffing, name="report-staffing"),
    path("reports/trainees/", reports.report_trainees, name="report-trainees"),
]
