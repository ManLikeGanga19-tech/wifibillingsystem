"""Enrol, confirm, and remove an authenticator app.

The QR code is rendered SERVER-SIDE into a data URI. The alternative — shipping a QR
library to the browser — would mean the console fetching a script from a CDN, which our
CSP forbids for good reason, or bundling one to draw a picture of a secret the server
already has.
"""

import base64
import io

import qrcode
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.schema import OBJECT_RESPONSE

from . import mfa
from .mfa import MfaError


class CodeSerializer(serializers.Serializer):
    #: Long enough for a recovery code (xxxx-xxxx), which is also accepted here.
    code = serializers.CharField(max_length=32)


def _qr_data_uri(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class _Base(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def handle_exception(self, exc):
        if isinstance(exc, MfaError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)


@extend_schema(responses=OBJECT_RESPONSE, summary="Is an authenticator set up?")
class MfaStatusView(_Base):
    def get(self, request):
        device = getattr(request.user, "mfa_device", None)
        return Response(
            {
                "enrolled": mfa.is_enrolled(request.user),
                "confirmed_at": device.confirmed_at if device else None,
                "recovery_codes_left": (
                    device.recovery_codes.filter(used_at__isnull=True).count()
                    if device and device.is_active
                    else 0
                ),
                "why": (
                    "Your authenticator signs the actions that move money — withdrawing, "
                    "and changing where we pay you. It is what stops somebody who gets "
                    "into your console from emptying your wallet."
                ),
            }
        )


@extend_schema(request=None, responses=OBJECT_RESPONSE,
               summary="Begin enrolment — returns a QR code to scan")
class MfaSetupView(_Base):
    def post(self, request):
        device = mfa.begin_enrolment(request.user)
        uri = device.provisioning_uri()
        return Response(
            {
                "qr": _qr_data_uri(uri),
                "uri": uri,
                # For anyone who cannot scan (a desktop authenticator, say).
                "secret": device.secret,
                "detail": "Scan this with Google Authenticator, then enter the 6-digit code.",
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(request=CodeSerializer, responses=OBJECT_RESPONSE,
               summary="Confirm enrolment — returns the recovery codes ONCE")
class MfaConfirmView(_Base):
    def post(self, request):
        s = CodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        codes = mfa.confirm_enrolment(request.user, s.validated_data["code"])
        return Response(
            {
                "detail": "Your authenticator is on. Your wallet is now protected.",
                "recovery_codes": codes,
                "warning": (
                    "Save these somewhere safe and offline. They are the ONLY way back "
                    "into your money if you lose your phone, and we cannot show them "
                    "to you again."
                ),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(request=CodeSerializer, responses=OBJECT_RESPONSE,
               summary="Issue a fresh set of recovery codes (invalidates the old ones)")
class MfaRecoveryCodesView(_Base):
    def post(self, request):
        s = CodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        codes = mfa.regenerate_recovery_codes(request.user, s.validated_data["code"])
        return Response({"recovery_codes": codes, "detail": "Your old codes no longer work."})


@extend_schema(request=CodeSerializer, responses=OBJECT_RESPONSE,
               summary="Remove the authenticator (needs a current code)")
class MfaDisableView(_Base):
    def post(self, request):
        s = CodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        mfa.disable(request.user, s.validated_data["code"])
        return Response(
            {
                "detail": (
                    "Authenticator removed. You will be asked to set one up again the "
                    "next time you move money."
                )
            }
        )
