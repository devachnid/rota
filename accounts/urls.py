"""The app's own routes under /accounts/. This replaces the
django.contrib.auth.urls include: same names, same paths, but the reset
views are ours (accounts/views.py) and every page is a template in the
app's design system. Django's reset/done page is dropped — setting a
password signs the person in and lands on the rota."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("passkeys/register/options/", views.passkey_register_options,
         name="passkey_register_options"),
    path("passkeys/register/", views.passkey_register, name="passkey_register"),
    path("passkeys/<int:pk>/remove/", views.passkey_remove, name="passkey_remove"),
    path("password_change/", views.ChangePasswordView.as_view(), name="password_change"),
    path("password_reset/", views.RequestPasswordLinkView.as_view(), name="password_reset"),
    path("password_reset/done/", auth_views.PasswordResetDoneView.as_view(),
         name="password_reset_done"),
    path("reset/<uidb64>/<token>/", views.SetPasswordFromLinkView.as_view(),
         name="password_reset_confirm"),
]
