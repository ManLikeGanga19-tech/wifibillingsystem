from rest_framework import serializers

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.plans.models import Plan
from apps.provisioning.models import Router

from .models import Transaction


class STKPushRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    plan_id = serializers.IntegerField()
    mac = serializers.CharField(max_length=17, required=False, allow_blank=True, default="")
    router_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_phone(self, value):
        try:
            return normalize_msisdn(value)
        except InvalidPhoneError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        # Fail closed: resolve the tenant from the subdomain OR the router the
        # customer is connected to. Without one, we do not accept a plan from an
        # arbitrary ISP.
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
        router = None
        if attrs.get("router_id"):
            router = Router.objects.filter(pk=attrs["router_id"], is_active=True).first()
        if tenant is None and router is not None:
            tenant = router.operator
        if tenant is None:
            raise serializers.ValidationError(
                {"detail": "Cannot determine the ISP. Open the payment page from the WiFi login."}
            )

        # THE MONEY GATE, at the point where money would actually be taken. A
        # customer must never be able to pay an ISP we have not verified — that
        # money lands on OUR paybill, and we would be holding funds collected by an
        # unchecked business. Refuse before the STK prompt, not after.
        if not tenant.can_transact:
            raise serializers.ValidationError(
                {"detail": "This WiFi hotspot is not live yet. Please try again later."}
            )

        plans = Plan.objects.filter(
            is_active=True, plan_type=Plan.PlanType.HOTSPOT, operator=tenant
        )
        try:
            attrs["plan"] = plans.get(pk=attrs["plan_id"])
        except Plan.DoesNotExist as exc:
            raise serializers.ValidationError({"plan_id": "Unknown or inactive plan"}) from exc
        # The router (if given) must belong to the same tenant as the plan.
        attrs["router"] = router if (router and router.operator_id == tenant.id) else None
        return attrs


class TransactionStatusSerializer(serializers.ModelSerializer):
    session_active = serializers.SerializerMethodField()
    session = serializers.SerializerMethodField()
    #: THE FIELD THAT ENDS THE INFINITE SPINNER. The portal used to poll only
    #: session_active and had no way to tell "still connecting" from "failed forever",
    #: so a paid customer whose provisioning failed span until they gave up. This says
    #: which it is: connecting | active | failed (or pending, before payment lands).
    provisioning = serializers.SerializerMethodField()
    provision_message = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "public_id",
            "status",
            "amount",
            "mpesa_receipt",
            "result_desc",
            "session_active",
            "session",
            "provisioning",
            "provision_message",
        ]

    def _active_session(self, obj):
        session = getattr(obj, "session", None)
        if session and session.status == session.Status.ACTIVE:
            return session
        return None

    def _provisioning_state(self, obj) -> str:
        # Not paid yet: the STK prompt is still out, or it failed/timed out. The
        # portal reads `status` for that; provisioning has not begun.
        if obj.status not in Transaction.SUCCESS_STATUSES:
            return "pending"
        session = getattr(obj, "session", None)
        if session and session.status == session.Status.ACTIVE:
            return "active"
        # Paid, but the connection could not be built — either the session failed on
        # the router, or no session exists and the failure is recorded on the
        # transaction (no router at all). Both are terminal for the customer.
        if (session and session.status == session.Status.FAILED) or obj.provision_error:
            return "failed"
        # Paid, session being built. The portal keeps polling — but with a client-side
        # safety timeout, so even a stuck task never becomes a forever-spinner.
        return "connecting"

    def get_provisioning(self, obj) -> str:
        return self._provisioning_state(obj)

    def get_provision_message(self, obj) -> str:
        state = self._provisioning_state(obj)
        if state != "failed":
            return ""
        # What the customer reads. It must reassure them the MONEY is safe first —
        # that is their actual worry — then tell them what happens next.
        return (
            "We received your payment, but couldn't connect you automatically. "
            "Your payment is safe. We'll keep trying — tap retry, or ask the operator "
            "for help if it doesn't connect shortly."
        )

    def get_session_active(self, obj) -> bool:
        return self._active_session(obj) is not None

    def get_session(self, obj) -> dict | None:
        """Hotspot credentials for the paying device — the portal submits these to
        the MikroTik link-login-only endpoint to connect the customer automatically."""
        session = self._active_session(obj)
        if session is None:
            return None
        return {
            "hotspot_username": session.hotspot_username,
            "hotspot_password": session.hotspot_password,
            "expires_at": session.expires_at.isoformat(),
        }


class TransactionAdminSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "public_id",
            "phone",
            "plan_name",
            "amount",
            "status",
            "mpesa_receipt",
            "checkout_request_id",
            "result_code",
            "result_desc",
            "created_at",
            "callback_received_at",
        ]
