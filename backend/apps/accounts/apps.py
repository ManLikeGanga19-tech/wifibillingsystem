from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"

    def ready(self):
        # Registers the OpenAPI description of CookieJWTAuthentication. Without
        # this import the extension is never discovered and the generated schema
        # would claim every endpoint is unauthenticated.
        from . import schema  # noqa: F401
