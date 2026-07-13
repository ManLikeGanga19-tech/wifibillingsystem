"""Communications settings: the gateway an ISP's messages leave on.

The security shape of this file, stated plainly:

  * Credentials go IN and never come OUT. A read reports WHICH fields are set, never what
    they are. You cannot leak what you do not serialise, and a bulk-SMS key is money —
    anyone who steals it sends on the ISP's account at the ISP's cost.
  * A blank secret on write means "leave it alone", so the console can save a form
    without asking an ISP to re-type a key it is not allowed to show them.
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

from . import catalog
from .models import (
    GATEWAY_MODE_CHOICES,
    Channel,
    MessagingSettings,
    ProviderCredential,
)
from .providers import ProviderError, get_provider, resolve_provider

CHANNELS = (Channel.SMS, Channel.WHATSAPP)


def _settings_for(operator) -> MessagingSettings:
    config, _ = MessagingSettings.objects.get_or_create(operator=operator)
    return config


def _cards(operator, channel: str, config: MessagingSettings) -> list[dict]:
    """The catalog, annotated with what THIS ISP has done with it — which provider is
    live, and which ones already hold credentials."""
    stored = {
        row.provider: row.values
        for row in ProviderCredential.objects.filter(operator=operator, channel=channel)
    }
    active = config.active_provider(channel)
    return [
        {
            "id": p.id,
            "name": p.name,
            "region": p.region,
            "managed": p.managed,
            "note": p.note,
            "active": p.id == active,
            # Configured = every REQUIRED field has a value. A half-filled provider must
            # not look ready, or the ISP activates it and their receipts stop.
            "configured": p.managed
            or all(stored.get(p.id, {}).get(f.key) for f in p.fields if f.required),
            "fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "secret": f.secret,
                    "placeholder": f.placeholder,
                    "required": f.required,
                    # For a secret we say only that one is stored. For a plain field we
                    # can safely echo the value back so the form is editable.
                    "value": "" if f.secret else stored.get(p.id, {}).get(f.key, ""),
                    "set": bool(stored.get(p.id, {}).get(f.key)),
                }
                for f in p.fields
            ],
        }
        for p in catalog.by_channel(channel)
    ]


class ProvidersView(APIView):
    """Every gateway an ISP may use on this channel, and where they stand with each."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="SMS/WhatsApp gateways and their state")
    def get(self, request, channel: str):
        if channel not in CHANNELS:
            return Response({"detail": "Unknown channel."}, status=status.HTTP_404_NOT_FOUND)
        operator = acting_tenant(request)
        config = _settings_for(operator)
        body = {
            "channel": channel,
            "active": config.active_provider(channel),
            "providers": _cards(operator, channel, config),
        }
        if channel == Channel.SMS:
            # The balance lives on the platform account now (billing.platform_account):
            # SMS is paid for by topping US up, not out of money we hold for them.
            from apps.billing.topup_views import _summary

            body["account"] = _summary(operator)
        else:
            body["note"] = catalog.WHATSAPP_NOTE
        return Response(body)


class ConfigureProviderSerializer(serializers.Serializer):
    #: {field_key: value}. A secret sent blank means "keep the stored one".
    credentials = serializers.DictField(child=serializers.CharField(allow_blank=True))
    #: Make this the live provider for the channel once it is configured.
    activate = serializers.BooleanField(default=False)


class ConfigureProviderView(APIView):
    """Save credentials for one gateway, and optionally make it the live one."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=ConfigureProviderSerializer,
        responses=OBJECT_RESPONSE,
        summary="Store credentials for a gateway (secrets are write-only)",
    )
    def post(self, request, channel: str, provider_id: str):
        provider = catalog.lookup(channel, provider_id) if channel in CHANNELS else None
        if provider is None:
            return Response({"detail": "Unknown gateway."}, status=status.HTTP_404_NOT_FOUND)
        if provider.managed:
            return Response(
                {"detail": "The WIFI.OS gateway needs no credentials — it runs on ours."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        s = ConfigureProviderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        incoming = s.validated_data["credentials"]

        operator = acting_tenant(request)
        row, _ = ProviderCredential.objects.get_or_create(
            operator=operator, channel=channel, provider=provider_id
        )
        values = dict(row.values)
        known = {f.key for f in provider.fields}
        for key, value in incoming.items():
            if key not in known:
                continue  # ignore anything not in the catalog — no smuggling extra keys
            if value == "" and key in catalog.secret_keys(channel, provider_id):
                continue  # blank secret = keep the stored one
            values[key] = value

        missing = [f.label for f in provider.fields if f.required and not values.get(f.key)]
        if missing:
            return Response(
                {"detail": f"Still needed: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        row.values = values
        row.save()

        config = _settings_for(operator)
        if s.validated_data["activate"]:
            _activate(config, channel, provider_id)

        audit(
            "messaging_provider_configured",
            operator=operator,
            actor=request.user,
            target=operator,
            channel=channel,
            provider=provider_id,  # the NAME of the gateway; never a credential
            activated=s.validated_data["activate"],
        )
        return Response({"providers": _cards(operator, channel, config),
                         "active": config.active_provider(channel)})


class ActivateProviderView(APIView):
    """Switch the live gateway. One is active per channel at a time."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(request=None, responses=OBJECT_RESPONSE, summary="Make a gateway the live one")
    def post(self, request, channel: str, provider_id: str):
        provider = catalog.lookup(channel, provider_id) if channel in CHANNELS else None
        if provider is None:
            return Response({"detail": "Unknown gateway."}, status=status.HTTP_404_NOT_FOUND)

        operator = acting_tenant(request)
        if not provider.managed:
            values = _stored(operator, channel, provider_id)
            missing = [f.label for f in provider.fields if f.required and not values.get(f.key)]
            if missing:
                # Activating a half-configured gateway would silently stop every receipt.
                return Response(
                    {"detail": f"Add its credentials first: {', '.join(missing)}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        config = _settings_for(operator)
        _activate(config, channel, provider_id)
        audit(
            "messaging_provider_activated",
            operator=operator, actor=request.user, target=operator,
            channel=channel, provider=provider_id,
        )
        return Response({"providers": _cards(operator, channel, config),
                         "active": config.active_provider(channel)})


class DisconnectProviderView(APIView):
    """Turn a channel off (WhatsApp), or drop stored credentials."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Disconnect a gateway")
    def delete(self, request, channel: str, provider_id: str):
        if channel not in CHANNELS:
            return Response({"detail": "Unknown channel."}, status=status.HTTP_404_NOT_FOUND)
        operator = acting_tenant(request)
        ProviderCredential.objects.filter(
            operator=operator, channel=channel, provider=provider_id
        ).delete()

        config = _settings_for(operator)
        if config.active_provider(channel) == provider_id:
            # SMS always has somewhere to fall back to (ours). WhatsApp does not, so it
            # simply goes quiet — which is the honest outcome of removing its only key.
            if channel == Channel.SMS:
                config.sms_provider = catalog.MANAGED_SMS
            else:
                config.whatsapp_provider = ""
            config.save()

        audit(
            "messaging_provider_disconnected",
            operator=operator, actor=request.user, target=operator,
            channel=channel, provider=provider_id,
        )
        return Response({"providers": _cards(operator, channel, config),
                         "active": config.active_provider(channel)})


# --- test send -------------------------------------------------------------------------


class TestSendSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=Channel.choices)
    to = serializers.CharField(max_length=120)


class MessagingTestView(APIView):
    """Send one real message to the ISP's own number/address.

    The whole point of this button: wrong credentials fail SILENTLY in production — an
    unapproved sender ID, a rejected password, an account with no balance — and the ISP
    only learns when a customer says "I never got my code". This makes the failure happen
    now, to them, with the gateway's own words in front of them.
    """

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=TestSendSerializer, responses=OBJECT_RESPONSE,
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

        # When the ISP is testing THEIR OWN gateway the send must be real — a dummy
        # "success" would prove nothing, which is the exact failure this exists to catch.
        # On our managed gateway, dev's dummy override still applies.
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
            operator=operator, actor=request.user, target=operator,
            channel=channel, ok=result.ok,
        )
        if not result.ok:
            return Response(
                {"detail": result.error or "The gateway rejected the message."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": f"Test {channel} sent to {to}."})


# --- email (unchanged shape: our mailer, or the ISP's own SMTP) -------------------------

EMAIL_FIELDS = (
    "email_mode", "smtp_host", "smtp_port", "smtp_username", "smtp_use_tls",
    "from_email", "from_name",
)


class EmailSettingsSerializer(serializers.Serializer):
    email_mode = serializers.ChoiceField(choices=GATEWAY_MODE_CHOICES, required=False)
    smtp_host = serializers.CharField(max_length=200, required=False, allow_blank=True)
    smtp_port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    smtp_username = serializers.CharField(max_length=200, required=False, allow_blank=True)
    smtp_password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    smtp_use_tls = serializers.BooleanField(required=False)
    from_email = serializers.EmailField(required=False, allow_blank=True)
    from_name = serializers.CharField(max_length=80, required=False, allow_blank=True)


def _email_dict(c: MessagingSettings) -> dict:
    data = {f: getattr(c, f) for f in EMAIL_FIELDS}
    data["smtp_password_configured"] = bool(c.smtp_password)
    return data


class EmailSettingsView(APIView):
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's email gateway")
    def get(self, request):
        return Response(_email_dict(_settings_for(acting_tenant(request))))

    @extend_schema(request=EmailSettingsSerializer, responses=OBJECT_RESPONSE,
                   summary="Update the email gateway")
    def patch(self, request):
        config = _settings_for(acting_tenant(request))
        s = EmailSettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        if data.get("email_mode") == "own":
            host = data.get("smtp_host") or config.smtp_host
            sender = data.get("from_email") or config.from_email
            if not host or not sender:
                return Response(
                    {"detail": "An SMTP host and a From address are needed to send your "
                               "own mail."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        for field in EMAIL_FIELDS:
            if field in data:
                setattr(config, field, data[field])
        if data.get("smtp_password"):  # blank = keep the stored one
            config.smtp_password = data["smtp_password"]
        config.save()

        audit("messaging_email_updated", operator=config.operator, actor=request.user,
              target=config.operator, email_mode=config.email_mode)
        return Response(_email_dict(config))


def _stored(operator, channel: str, provider_id: str) -> dict:
    row = ProviderCredential.objects.filter(
        operator=operator, channel=channel, provider=provider_id
    ).first()
    return row.values if row else {}


def _activate(config: MessagingSettings, channel: str, provider_id: str) -> None:
    if channel == Channel.SMS:
        config.sms_provider = provider_id
    else:
        config.whatsapp_provider = provider_id
    config.save()
