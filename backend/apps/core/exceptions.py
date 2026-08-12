"""Project-wide DRF exception handling.

The one thing the default handler misses that we hit often: deleting a row something else
still points at. Postgres/Django raise ProtectedError (e.g. deleting a plan that still has
clients, or a router that still has sessions). Untouched, that surfaces as a 500. We turn it
into a clean 409 with a message the console can show, so a blocked delete reads as "move the
dependents first", not "the server broke".
"""

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


def drf_exception_handler(exc, context):
    response = drf_default_handler(exc, context)
    if response is None and isinstance(exc, ProtectedError):
        return Response(
            {
                "detail": "This can't be deleted while other records still depend on it — "
                "move or remove those first."
            },
            status=status.HTTP_409_CONFLICT,
        )
    return response
