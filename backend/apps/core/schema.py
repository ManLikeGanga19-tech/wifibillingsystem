"""Response schemas for our hand-rolled APIViews.

drf-spectacular can infer a serializer from a ModelViewSet, but not from an
APIView that assembles a dict by hand. Left alone it emits "unable to guess
serializer" and omits the endpoint from the schema entirely — so a client
generated from the schema simply would not know these endpoints exist. Since the
whole super-admin console runs on them, that is not acceptable.

`OBJECT_RESPONSE` documents "a JSON object" for endpoints whose body is genuinely
free-form or trivial. Anything a client actually models gets a real serializer.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers

#: For trivial/ack-shaped bodies ({"detail": ...}) and free-form payloads.
OBJECT_RESPONSE = OpenApiResponse(OpenApiTypes.OBJECT)

#: A POST body we do not model with a serializer. NOTE: spectacular needs BOTH a
#: request and a response for write endpoints — giving it only `responses` still
#: leaves it unable to guess, and it drops the endpoint from the schema.
OBJECT_REQUEST = OpenApiTypes.OBJECT


class DetailSerializer(serializers.Serializer):
    """The standard ack/error body."""

    detail = serializers.CharField()


class LoginRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(
        help_text=(
            "Phone OR email — whichever they remember. A Kenyan MSISDN in any form "
            "(0712…, +254712…, 712…) or the address they signed up with."
        )
    )
    password = serializers.CharField(write_only=True)


class LoginResponseSerializer(serializers.Serializer):
    """No token in the body — by design. Auth is an httpOnly cookie; the CSRF
    token is returned so the client can echo it on writes."""

    detail = serializers.CharField()
    csrf_token = serializers.CharField()
