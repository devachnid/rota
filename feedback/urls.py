from django.urls import path

from . import views

urlpatterns = [
    path("form/", views.feedback_form, name="feedback-form"),
    path("send/", views.feedback_send, name="feedback-send"),
]
