from django.apps import AppConfig


class DeveloperConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.developer"

    def ready(self):
        # Registers the OpenAPI description of ApiTokenAuthentication. Without this
        # import the extension is never discovered and the generated schema would
        # claim every token-authenticated endpoint is unauthenticated.
        from . import schema  # noqa: F401
