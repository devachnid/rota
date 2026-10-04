from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .recent_auth import on_login
        user_logged_in.connect(on_login, dispatch_uid="accounts.recent_auth")
