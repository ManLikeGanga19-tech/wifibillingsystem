"""OpenAPI description of the developer API-token auth.

`ApiTokenAuthentication` is ours, so drf-spectacular can't document it on its own —
without this every view that allows a developer token emits "could not resolve
authenticator" and the generated schema silently claims the endpoint is unauthenticated.
Registered from DeveloperConfig.ready() so the extension is discovered at load time.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiTokenScheme(OpenApiAuthenticationExtension):
    target_class = "apps.developer.auth.ApiTokenAuthentication"
    name = "apiTokenAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "Developer API token, sent as `Authorization: Token wos_…`. Create one "
                "under Settings → Developer. It acts as the user who created it, scoped "
                "to that user's tenant; platform-staff endpoints stay closed to it."
            ),
        }
