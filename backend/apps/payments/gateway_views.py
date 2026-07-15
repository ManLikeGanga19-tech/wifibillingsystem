"""Settings > Payments: which gateway an ISP collects through, and the webhook it uses.

The security shape:

  * Credentials go IN and never come OUT. A read reports which fields are SET, never their
    values. A stolen Daraja consumer secret lets somebody collect money in the ISP's name —
    these are the most dangerous secrets in the system.
  * The webhook URL carries a per-tenant secret that both NAMES the operator (so we never
    trust the body to tell us whose sale it is) and AUTHENTICATES the call (a random POST
    is a 404, not a free WiFi session).
  * Switching gateway is a money decision — CanManageMoney, plus an audit line.
"""

import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.models import Operator
from apps.core.permissions import CanManageMoney, RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .gateways import ADAPTERS, catalog, get_gateway
from .models import GatewayCredential, Transaction

logger = logging.getLogger(__name__)


def webhook_url(operator, gateway_id: str) -> str:
    base = settings.DARAJA_CALLBACK_BASE_URL.rstrip("/")
    return f"{base}/api/v1/payments/hooks/{gateway_id}/{operator.webhook_token}/"


def _cards(operator) -> list[dict]:
    stored = {
        row.gateway: row.values
        for row in GatewayCredential.objects.filter(operator=operator)
    }
    active = operator.payment_gateway or catalog.MANAGED
    cards = []
    for g in catalog.GATEWAYS:
        values = stored.get(g.id, {})
        configured = g.managed or (
            bool(g.fields) and all(values.get(f.key) for f in g.fields if f.required)
        )
        cards.append(
            {
                "id": g.id,
                "name": g.name,
                "region": g.region,
                "methods": list(g.methods),
                "settles": g.settles,
                "settlement": g.settlement,
                "managed": g.managed,
                "note": g.note,
                "available": g.available and g.id in ADAPTERS,
                "active": g.id == active,
                "configured": configured,
                "fields": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "secret": f.secret,
                        "placeholder": f.placeholder,
                        "required": f.required,
                        "help": f.help,
                        "choices": [{"value": v, "label": lbl} for v, lbl in f.choices],
                        # A secret is never echoed. A plain field is, so the form is
                        # editable without retyping.
                        "value": "" if f.secret else values.get(f.key, ""),
                        "set": bool(values.get(f.key)),
                    }
                    for f in g.fields
                ],
                # Only meaningful for a gateway the ISP owns: this is the URL they must
                # register with Safaricom.
                "webhook_url": "" if g.managed else webhook_url(operator, g.id),
            }
        )
    return cards


def _state(operator) -> dict:
    return {
        "active": operator.payment_gateway or catalog.MANAGED,
        "gateways": _cards(operator),
    }


class PaymentGatewaysView(APIView):
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Payment gateways and their state")
    def get(self, request):
        return Response(_state(acting_tenant(request)))


class ConfigureGatewaySerializer(serializers.Serializer):
    credentials = serializers.DictField(child=serializers.CharField(allow_blank=True))
    activate = serializers.BooleanField(default=False)


class ConfigureGatewayView(APIView):
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=ConfigureGatewaySerializer,
        responses=OBJECT_RESPONSE,
        summary="Store credentials for a payment gateway (secrets are write-only)",
    )
    def post(self, request, gateway_id: str):
        gateway = catalog.lookup(gateway_id)
        if gateway is None or gateway_id not in ADAPTERS:
            return Response({"detail": "That gateway is not available."}, status=404)
        if gateway.managed:
            return Response(
                {"detail": "The WIFI.OS paybill needs no credentials — it is ours."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        s = ConfigureGatewaySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)

        row, _ = GatewayCredential.objects.get_or_create(
            operator=operator, gateway=gateway_id
        )
        values = dict(row.values)
        known = {f.key for f in gateway.fields}
        secrets = catalog.secret_keys(gateway_id)
        for key, value in s.validated_data["credentials"].items():
            if key not in known:
                continue  # no smuggling keys the catalog does not declare
            if value == "" and key in secrets:
                continue  # blank secret = keep the stored one
            values[key] = value

        missing = [f.label for f in gateway.fields if f.required and not values.get(f.key)]
        if missing:
            return Response(
                {"detail": f"Still needed: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        row.values = values
        row.save()

        if s.validated_data["activate"]:
            _activate(operator, gateway_id, request.user)

        audit(
            "payment_gateway_configured",
            operator=operator,
            actor=request.user,
            target=operator,
            gateway=gateway_id,  # the NAME, never a credential
            activated=s.validated_data["activate"],
        )
        return Response(_state(operator))


class ActivateGatewayView(APIView):
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(request=None, responses=OBJECT_RESPONSE, summary="Collect through this gateway")
    def post(self, request, gateway_id: str):
        gateway = catalog.lookup(gateway_id)
        if gateway is None or gateway_id not in ADAPTERS:
            return Response({"detail": "That gateway is not available."}, status=404)

        operator = acting_tenant(request)
        if not gateway.managed:
            values = _stored(operator, gateway_id)
            missing = [
                f.label for f in gateway.fields if f.required and not values.get(f.key)
            ]
            if missing:
                # Switching to a half-configured gateway would stop the ISP taking money at
                # all — every customer's STK push would fail at the door.
                return Response(
                    {"detail": f"Add its credentials first: {', '.join(missing)}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        _activate(operator, gateway_id, request.user)
        return Response(_state(operator))


class TestGatewaySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)


class TestGatewayView(APIView):
    """Prove the credentials work, by charging the ISP's own phone.

    Daraja will happily accept a shortcode whose passkey is wrong and fail later, at the
    customer. This makes it fail NOW, at the ISP, with Safaricom's own words — before a
    single subscriber is turned away.
    """

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]
    # Fires a real STK prompt — throttle it like every other STK-initiating endpoint.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "stk-push"

    @extend_schema(
        request=TestGatewaySerializer, responses=OBJECT_RESPONSE,
        summary="Send yourself a test STK prompt on this gateway",
    )
    def post(self, request, gateway_id: str):
        from apps.core.phone import InvalidPhoneError, normalize_msisdn
        from apps.plans.models import Plan

        from .gateways import GatewayError

        # The MANAGED gateway runs on OUR Daraja shortcode. A test charge there would let
        # any ISP owner fire real STK prompts at arbitrary phones on Danamo's account — a
        # cost and harassment vector — and it proves nothing (our credentials always work).
        # Only a bring-your-own gateway, which charges the ISP's OWN account, is testable.
        gateway = catalog.lookup(gateway_id)
        if gateway is None or gateway.managed or gateway_id not in ADAPTERS:
            return Response(
                {"detail": "This gateway cannot be test-charged."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        operator = acting_tenant(request)
        try:
            phone = normalize_msisdn(request.data.get("phone", ""))
        except InvalidPhoneError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        plan = Plan.objects.filter(operator=operator, is_active=True).first()
        if plan is None:
            return Response(
                {"detail": "Create a plan first — a test charge needs something to buy."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # KSh 1, on the ISP's own phone. Real money, deliberately: a test that does not
        # actually touch Safaricom proves nothing.
        tx = Transaction(
            operator=operator,
            plan=plan,
            phone=phone,
            amount=1,
            gateway=gateway_id,
            account_reference=operator.slug[:12].upper(),
        )
        try:
            result = get_gateway(operator, gateway_id).charge(tx)
        except GatewayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        audit(
            "payment_gateway_tested",
            operator=operator, actor=request.user, target=operator, gateway=gateway_id,
        )
        return Response(
            {"detail": f"KSh 1 prompt sent to {phone}. {result.instructions}"}
        )


@method_decorator(csrf_exempt, name="dispatch")
class GatewayWebhookView(View):
    """Where a gateway POSTs the result of a payment made on an ISP's OWN account.

    The token in the URL is the ISP's. It tells us WHOSE sale this is without trusting a
    single byte of the body, and a wrong token is a 404 — because a guessable webhook would
    let anyone forge a paid session and get free WiFi forever.

    Always answers 200. A webhook that 500s makes the gateway retry-storm us, and
    reconciliation is what actually guarantees the result anyway.
    """

    def post(self, request, gateway_id: str, token: str):
        operator = Operator.objects.filter(webhook_token=token).first()
        if operator is None or gateway_id not in ADAPTERS:
            raise Http404

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed %s webhook for %s", gateway_id, operator.slug)
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

        try:
            self._handle(operator, gateway_id, payload)
        except Exception:
            logger.exception("Webhook crashed; reconciliation will settle it")
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    def _handle(self, operator, gateway_id: str, payload: dict) -> None:
        from .services import process_stk_callback

        gateway = get_gateway(operator, gateway_id)
        event = gateway.parse_webhook(payload)
        if event is None or not event.reference:
            return

        # The transaction must belong to THIS operator. Without that check, an ISP who
        # learns another's checkout id could settle a stranger's payment through their own
        # webhook — attributing somebody else's sale to themselves.
        tx = Transaction.objects.filter(
            checkout_request_id=event.reference, operator=operator
        ).first()
        if tx is None:
            logger.warning(
                "%s webhook for unknown/foreign reference %s (operator %s)",
                gateway_id, event.reference, operator.slug,
            )
            return

        # M-Pesa gateways speak Daraja natively, so the existing (battle-tested, idempotent)
        # callback handler does the work. Non-Daraja gateways will normalise into it.
        process_stk_callback(payload)


def _stored(operator, gateway_id: str) -> dict:
    row = GatewayCredential.objects.filter(operator=operator, gateway=gateway_id).first()
    return row.values if row else {}


def _activate(operator, gateway_id: str, actor) -> None:
    previous = operator.payment_gateway
    operator.payment_gateway = gateway_id
    operator.save(update_fields=["payment_gateway", "updated_at"])
    audit(
        "payment_gateway_activated",
        operator=operator,
        actor=actor,
        target=operator,
        gateway=gateway_id,
        previous=previous,
    )
