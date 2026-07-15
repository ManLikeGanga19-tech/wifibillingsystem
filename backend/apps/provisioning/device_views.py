"""Portal-facing device management — the "add your other devices" surface.

Public and anonymous (a WiFi customer, not a logged-in staffer), but every call is gated on
the session's device_token: the secret only the paying device holds. No token, or a token
whose session has ended, gets a flat 404 — we never reveal which. All the real work
(allowance, router push, rollback) lives in devices.py; this layer is auth + shape.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.public import PublicAPIView
from apps.core.schema import OBJECT_RESPONSE

from . import devices
from .models import Session, SessionDevice


def _state(session: Session, *, include_available: bool) -> dict:
    """What the portal renders: the slots, who's on, and (on demand) who could be added."""
    rows = list(session.devices.all().order_by("-is_paying_device", "approved_at"))
    payload = {
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
