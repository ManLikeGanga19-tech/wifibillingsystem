"""Portal-facing device management — the "add your other devices" surface.

Public and anonymous (a WiFi customer, not a logged-in staffer), but every call is gated on
the session's device_token: the secret only the paying device holds. No token, or a token
whose session has ended, gets a flat 404 — we never reveal which. All the real work
(allowance, router push, rollback) lives in devices.py; this layer is auth + shape.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.public import PublicAPIView
from apps.core.schema import OBJECT_RESPONSE

from . import devices
from .models import Router, Session, SessionDevice


def _portal_base(operator) -> str:
    """The TRUSTED base URL for this ISP's captive portal — never client-supplied, so a
    recovery link we SMS can't be pointed at a phishing host. PORTAL_BASE_URL wins (a single
    dev/staging portal); otherwise the ISP's subdomain."""
    base = (settings.PORTAL_BASE_URL or "").rstrip("/")
    if base:
        return base
    return f"https://{operator.slug}.{settings.TENANT_BASE_DOMAIN}"


def _state(session: Session, *, include_available: bool) -> dict:
    """What the portal renders: the slots, who's on, and (on demand) who could be added."""
    rows = list(session.devices.all().order_by("-is_paying_device", "approved_at"))
    payload = {
        # A summary so a RECOVERED session (magic link / URL) can show "online until X"
        # without a second round-trip.
        "session": {
            "username": session.hotspot_username,
            "expires_at": session.expires_at.isoformat(),
        },
        "allowance": {"general": session.general_slots, "tv": session.tv_slots},
        "used": {
            "general": sum(1 for d in rows if d.kind != SessionDevice.Kind.TV),
            "tv": sum(1 for d in rows if d.kind == SessionDevice.Kind.TV),
        },
        "devices": [
            {
                "mac_address": d.mac_address,
                "hostname": d.hostname,
                "kind": d.kind,
                "is_paying_device": d.is_paying_device,
            }
            for d in rows
        ],
    }
    if include_available:
        payload["available"] = devices.discover_devices(session)
    return payload


class SessionDevicesView(PublicAPIView):
    """GET  ?token=   -> slots, current devices, and devices available to add
    POST  {token, mac, kind?, hostname?} -> approve a device
    DELETE ?token=&mac= -> remove a device
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "device-mgmt"

    def _session_or_404(self, token: str):
        session = devices.session_for_token(token or "")
        return session

    @extend_schema(responses=OBJECT_RESPONSE, summary="Portal: this session's devices + additions")
    def get(self, request):
        session = self._session_or_404(request.query_params.get("token", ""))
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_state(session, include_available=True))

    @extend_schema(request=None, responses=OBJECT_RESPONSE, summary="Portal: add a device")
    def post(self, request):
        session = self._session_or_404(request.data.get("token", ""))
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        mac = request.data.get("mac", "")
        kind = request.data.get("kind", SessionDevice.Kind.OTHER)
        hostname = request.data.get("hostname", "")
        try:
            devices.approve_device(session, mac, kind=kind, hostname=hostname)
        except devices.DeviceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            # The router refused (unreachable, rejected the login). The slot was rolled
            # back, so the customer can simply try again.
            return Response(
                {"detail": "Couldn't add that device just now. Make sure it's connected to "
                           "the Wi-Fi and try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(_state(session, include_available=False), status=status.HTTP_201_CREATED)

    @extend_schema(responses=OBJECT_RESPONSE, summary="Portal: remove a device from this session")
    def delete(self, request):
        session = self._session_or_404(request.query_params.get("token", ""))
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        mac = request.query_params.get("mac", "")
        try:
            devices.remove_device(session, mac)
        except devices.DeviceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Couldn't remove that device just now. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(_state(session, include_available=False))


class RecoverDevicesView(PublicAPIView):
    """Text the paying phone a one-tap link back to its 'add devices' screen.

    The device_token lives only in the paying tab's memory (no browser storage), so a
    customer who closed it has no way back. This recovers it WITHOUT a second payment: they
    enter the phone that paid, and we SMS a link carrying the token — only to that number,
    which for an M-Pesa session IS the account, so only the real owner receives it.

    The response is deliberately the SAME whether or not a session was found, so the endpoint
    can't be used to discover who has an active plan. Tightly throttled — it sends SMS.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "device-recover"

    GENERIC = {
        "detail": "If that number has an active plan, we've texted it a link to manage its devices."
    }

    def _operator_for(self, request):
        operator = getattr(request, "tenant", None)
        if operator is None:
            rid = str(request.data.get("router", "")) or ""
            if rid.isdigit():
                router = Router.objects.filter(pk=int(rid), is_active=True).first()
                operator = router.operator if router else None
        return operator

    @extend_schema(request=None, responses=OBJECT_RESPONSE,
                   summary="Portal: SMS a 'manage devices' link to the phone that paid")
    def post(self, request):
        try:
            phone = normalize_msisdn(str(request.data.get("phone", "")))
        except InvalidPhoneError:
            phone = ""
        operator = self._operator_for(request)
        if not phone or operator is None:
            return Response(self.GENERIC)  # never reveal which part was missing

        session = (
            Session.objects.filter(
                operator=operator,
                status=Session.Status.ACTIVE,
                hotspot_username=phone,  # M-Pesa sessions log in as the phone number
            )
            .order_by("-created_at")
            .first()
        )
        if session and not (session.clock_started and session.expires_at <= _now()):
            from apps.notifications.models import Message
            from apps.notifications.services import send_sms

            rid = request.data.get("router", "")
            link = f"{_portal_base(operator)}/?manage={session.device_token}"
            if str(rid).isdigit():
                link += f"&router={rid}"
            send_sms(
                operator, phone,
                f"Manage your Wi-Fi devices: {link}",
                category=Message.Category.OTHER,
            )
        return Response(self.GENERIC)


def _now():
    from django.utils import timezone

    return timezone.now()
