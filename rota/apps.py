from django.apps import AppConfig


class RotaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rota'

    def ready(self):
        from . import checks  # noqa: F401  (registers the deploy checks)
