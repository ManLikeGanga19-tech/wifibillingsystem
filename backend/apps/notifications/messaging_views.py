"""Communications settings: which gateway an ISP's messages leave on.

The security shape of this file, stated plainly:

  * Credentials go IN and never come OUT. A read reports `sms_api_key_configured: true`,
    never the key. You cannot leak what you do not serialise, and an ISP's SMS key is
    money — anyone who steals it can send on their account at their cost.
  * A blank secret on write means "leave it alone", so the console can save the form
    without asking the ISP to re-type a key it is not allowed to show them.
  * Switching a channel to `own` with no working credentials would silently strand every
    customer notification, so the serializer refuses it and the model falls back to the
    platform even if a bad row somehow lands (see MessagingSettings.uses_own).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import CanManageMoney, RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .models import (
    GATEWAY_MODE_CHOICES,
    WHATSAPP_MODE_CHOICES,
    Channel,
    MessagingSettings,
)
from .providers import ProviderError, get_provider, resolve_provider

# The secrets. Listed once, so "never return these" is a fact of the module rather than
# something each new field has to remember.
SECRET_FIELDS = ("sms_api_key", "smtp_password", "whatsapp_token")

PLAIN_FIELDS = (
    "sms_mode", "sms_username", "sms_sender_id",
    "email_mode", "smtp_host", "smtp_port", "smtp_username", "smtp_use_tls",
    "from_email", "from_name",
    "whatsapp_mode", "whatsapp_phone_number_id",
)


def _settings_for(operator) -> MessagingSettings:
    config, _ = MessagingSettings.objects.get_or_create(operator=operator)
    return config


def _as_dict(c: MessagingSettings) -> dict:
    data = {field: getattr(c, field) for field in PLAIN_FIELDS}
    # Whether a secret exists — never the secret itself.
    for field in SECRET_FIELDS:
        data[f"{field}_configured"] = bool(getattr(c, field))
    return data


class MessagingSettingsSerializer(serializers.Serializer):
    sms_mode = serializers.ChoiceField(choices=GATEWAY_MODE_CHOICES, required=False)
    sms_username = serializers.CharField(max_length=100, required=False, allow_blank=True)
    sms_api_key = serializers.CharField(required=False, allow_blank=True, write_only=True)
    sms_sender_id = serializers.CharField(max_length=11, required=False, allow_blank=True)

    email_mode = serializers.ChoiceField(choices=GATEWAY_MODE_CHOICES, required=False)
    smtp_host = serializers.CharField(max_length=200, required=False, allow_blank=True)
    smtp_port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    smtp_username = serializers.CharField(max_length=200, required=False, allow_blank=True)
    smtp_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    smtp_use_tls = serializers.BooleanField(required=False)
    from_email = serializers.EmailField(required=False, allow_blank=True)
    from_name = serializers.CharField(max_length=80, required=False, allow_blank=True)

    whatsapp_mode = serializers.ChoiceField(choices=WHATSAPP_MODE_CHOICES, required=False)
    whatsapp_phone_number_id = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )
    whatsapp_token = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def __init__(self, *args, current: MessagingSettings = None, **kwargs):
        # Validation needs to know what is ALREADY stored: "switch to own" is legitimate
        # when the key was saved on a previous visit and the form (correctly) can't show
        # it back to be re-submitted.
        self.current = current
        super().__init__(*args, **kwargs)

    def _will_have(self, data: dict, field: str) -> bool:
        """The value this field ends up with — the incoming one, else what's stored."""
        incoming = data.get(field)
        if incoming:
            return True
        return bool(getattr(self.current, field, ""))

    def validate(self, data):
        own = MessagingSettings.Mode.OWN
        errors = {}

        if data.get("sms_mode") == own:
            if not self._will_have(data, "sms_api_key"):
                errors["sms_api_key"] = "Required to send SMS on your own account."
            if not self._will_have(data, "sms_username"):
                errors["sms_username"] = "Your Africa's Talking username is required."

        if data.get("email_mode") == own:
            if not self._will_have(data, "smtp_host"):
                errors["smtp_host"] = "Required to send email from your own server."
            if not self._will_have(data, "from_email"):
                errors["from_email"] = "The address your customers see mail come from."

        if data.get("whatsapp_mode") == own:
            if not self._will_have(data, "whatsapp_token"):
                errors["whatsapp_token"] = "Required to send on WhatsApp."
            if not self._will_have(data, "whatsapp_phone_number_id"):
                errors["whatsapp_phone_number_id"] = "Your WhatsApp phone number ID is required."

        if errors:
            raise serializers.ValidationError(errors)
        return data


class MessagingSettingsView(APIView):
    """Read and update the ISP's gateways. Same bar as the other money-adjacent
    settings: SMS spends the ISP's credit and sets the sender name customers see."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's messaging gateways")
    def get(self, request):
        return Response(_as_dict(_settings_for(acting_tenant(request))))

    @extend_schema(
        request=MessagingSettingsSerializer,
        responses=OBJECT_RESPONSE,
        summary="Update the messaging gateways (SMS, email, WhatsApp)",
    )
    def patch(self, request):
        config = _settings_for(acting_tenant(request))
        s = MessagingSettingsSerializer(data=request.data, current=config)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        for field in PLAIN_FIELDS:
            if field in data:
                setattr(config, field, data[field])
        # A blank secret means "keep the one you already have" — the form cannot show it
        # back, so an empty box must not wipe a working key.
        for field in SECRET_FIELDS:
            if data.get(field):
                setattr(config, field, data[field])
        config.save()

        audit(
            "messaging_settings_updated",
            operator=config.operator,
            actor=request.user,
            target=config.operator,
            # Modes only. A secret must never reach an audit row.
            sms_mode=config.sms_mode,
            email_mode=config.email_mode,
            whatsapp_mode=config.whatsapp_mode,
        )
        return Response(_as_dict(config))


class TestSendSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=Channel.choices)
    to = serializers.CharField(max_length=120)


class MessagingTestView(APIView):
    """Send one real message to the ISP's own number/address.

    The whole point of this button: credentials that are wrong fail SILENTLY in
    production — an unapproved sender ID, a rejected SMTP password — and the ISP only
    learns when a customer says "I never got my code". This makes the failure happen
    now, to them, with the provider's own error message in front of them.
    """

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=TestSendSerializer,
        responses=OBJECT_RESPONSE,
        summary="Send a test message to yourself to prove the gateway works",
    )
    def post(self, request):
        s = TestSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        channel = s.validated_data["channel"]
        to = s.validated_data["to"].strip()

        operator = acting_tenant(request)
        config = _settings_for(operator)

        from .models import Message

        message = Message(
            operator=operator,
            channel=channel,
            category=Message.Category.OTHER,
            subject="Test message from WIFI.OS",
            body=(
                f"This is a test from {operator.name}. If you can read this, your "
                f"{channel} gateway is working."
            ),
        )
        if channel == Channel.EMAIL:
            message.to_email = to
        else:
            message.to_phone = to.lstrip("+")

        # When the ISP is testing THEIR OWN credentials, the send must be real — a dummy
        # "success" would prove nothing, which is the exact failure this button exists to
        # prevent. On the platform gateway, dev's dummy override still applies.
        try:
            provider = (
                resolve_provider(channel, operator)
                if config.uses_own(channel)
                else get_provider(channel, operator)
            )
        except ProviderError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        result = provider.send(message)
        message.status = Message.Status.SENT if result.ok else Message.Status.FAILED
        message.provider_ref = result.provider_ref
        message.error = result.error[:255]
        if result.ok:
            from django.utils import timezone

            message.sent_at = timezone.now()
        message.save()

        audit(
            "messaging_test_send",
            operator=operator,
            actor=request.user,
            target=operator,
            channel=channel,
            ok=result.ok,
        )
        if not result.ok:
            return Response(
                {"detail": result.error or "The gateway rejected the message."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": f"Test {channel} sent to {to}."})
