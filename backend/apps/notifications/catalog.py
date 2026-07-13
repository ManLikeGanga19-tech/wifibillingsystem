"""The gateways an ISP can send through, declared once.

This is the single source of truth for BOTH the console (which renders a card per entry
and a form from `fields`) and the send path (which builds an adapter from the stored
credentials). Adding a provider means adding an entry here and an adapter — not touching
the UI, the serializer or the settings model.

One provider is active per channel at a time. An ISP may keep credentials for several
and switch between them; only the active one sends.

A NOTE ON THE MANAGED GATEWAY: `wifios` runs on OUR account and OUR key. The ISP never
sees a credential because there is nothing of theirs to see — they buy SMS credits and we
meter them. That is the entire point of "managed": zero setup.

WhatsApp has no managed option. We hold no Meta business identity on an ISP's behalf, so
offering one would be a lie; every WhatsApp provider here is bring-your-own.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    secret: bool = False
    placeholder: str = ""
    required: bool = True


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    #: Shown under the name on the card — where this provider is a sensible choice.
    region: str
    fields: list[Field] = field(default_factory=list)
    #: True only for the WIFI.OS gateway: no credentials, billed in credits.
    managed: bool = False
    #: What the ISP is told before they commit to it.
    note: str = ""


# --- SMS ------------------------------------------------------------------------------

SMS_PROVIDERS: list[Provider] = [
    Provider(
        id="wifios",
        name="WIFI.OS SMS",
        region="Kenya · managed by us",
        managed=True,
        note=(
            "Nothing to set up. Messages go out on our gateway and are paid for with SMS "
            "credits you top up from your wallet."
        ),
    ),
    Provider(
        id="africastalking",
        name="Africa's Talking",
        region="Pan-African",
        fields=[
            Field("username", "Username", placeholder="your-at-username"),
            Field("api_key", "API key", secret=True),
            Field("sender_id", "Sender ID", placeholder="ACMEWIFI", required=False),
        ],
    ),
    Provider(
        id="mobilesasa",
        name="MobileSasa",
        region="Kenya",
        fields=[
            Field("api_token", "API token", secret=True),
            Field("sender_id", "Sender ID", placeholder="ACMEWIFI"),
        ],
    ),
    Provider(
        id="bongasms",
        name="Bonga SMS",
        region="Kenya",
        fields=[
            Field("client_id", "API client ID"),
            Field("api_key", "API key", secret=True),
            Field("api_secret", "API secret", secret=True),
            Field("service_id", "Service ID"),
        ],
    ),
    Provider(
        id="blessedtexts",
        name="BlessedTexts",
        region="Kenya",
        fields=[
            Field("api_key", "API key", secret=True),
            Field("sender_id", "Sender ID", placeholder="ACMEWIFI"),
        ],
    ),
    Provider(
        id="hostpinnacle",
        name="BulkSMS (Host Pinnacle)",
        region="Kenya",
        fields=[
            Field("user_id", "User ID"),
            Field("password", "Password", secret=True),
            Field("sender_id", "Sender ID", placeholder="ACMEWIFI"),
        ],
    ),
    Provider(
        id="twilio",
        name="Twilio",
        region="Global",
        fields=[
            Field("account_sid", "Account SID"),
            Field("auth_token", "Auth token", secret=True),
            Field("from_number", "From number", placeholder="+1..."),
        ],
    ),
    Provider(
        id="infobip",
        name="Infobip",
        region="Global",
        fields=[
            Field("base_url", "Base URL", placeholder="xxxxx.api.infobip.com"),
            Field("api_key", "API key", secret=True),
            Field("sender_id", "Sender", placeholder="ACMEWIFI", required=False),
        ],
    ),
]


# --- WhatsApp -------------------------------------------------------------------------

WHATSAPP_PROVIDERS: list[Provider] = [
    Provider(
        id="apiwap",
        name="Apiwap",
        region="WhatsApp Business · Kenya",
        fields=[
            Field("api_key", "API key", secret=True),
            Field("sender", "Sender number", placeholder="2547XXXXXXXX"),
        ],
    ),
    Provider(
        id="notiva",
        name="Notiva",
        region="WhatsApp Business · Kenya",
        fields=[
            Field("api_key", "API key", secret=True),
            Field("sender", "Sender number", placeholder="2547XXXXXXXX"),
        ],
    ),
    Provider(
        id="twilio",
        name="Twilio",
        region="Global",
        fields=[
            Field("account_sid", "Account SID"),
            Field("auth_token", "Auth token", secret=True),
            Field("from_number", "WhatsApp sender", placeholder="whatsapp:+1..."),
        ],
    ),
    Provider(
        id="infobip",
        name="Infobip",
        region="Global",
        fields=[
            Field("base_url", "Base URL", placeholder="xxxxx.api.infobip.com"),
            Field("api_key", "API key", secret=True),
            Field("sender", "WhatsApp sender", placeholder="2547XXXXXXXX"),
        ],
    ),
]

WHATSAPP_NOTE = (
    "Meta only allows free-text messages within 24 hours of a customer writing to you. "
    "Outside that window you must use a template they have approved — so keep SMS as the "
    "fallback for reminders."
)

MANAGED_SMS = "wifios"


def by_channel(channel: str) -> list[Provider]:
    return SMS_PROVIDERS if channel == "sms" else WHATSAPP_PROVIDERS


def lookup(channel: str, provider_id: str) -> Provider | None:
    return next((p for p in by_channel(channel) if p.id == provider_id), None)


def secret_keys(channel: str, provider_id: str) -> set[str]:
    provider = lookup(channel, provider_id)
    return {f.key for f in provider.fields if f.secret} if provider else set()
