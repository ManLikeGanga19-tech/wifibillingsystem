"""Editable SMS templates: the body of each automated customer message.

Every automated SMS the platform sends to an ISP's customers has a DEFAULT body defined
here, and an ISP may override it in Settings > Message templates. The registry is the single
source of truth: the settings page renders its editors and variable chips from it, and the
send path renders from it — so the UI and the sender can never drift.

Substitution is deliberately dumb and safe. Callers build a context dict of already-formatted
strings (a date is formatted by the caller, not here), and render() replaces the template's
ALLOW-LISTED `@variables` only. A token that isn't allow-listed is left untouched, and the
save-time validator refuses unknown tokens — so a typo like `@expiry_dat` can never reach a
customer as literal text, and an unresolved value renders empty rather than as `@expiry_date`.
"""

import re

# One @token, e.g. @package_name. Word chars only.
TOKEN_RE = re.compile(r"@(\w+)")


class Template:
    """A message template's identity, default wording, and its allow-listed variables.

    `variables` is an ordered list of (name, sample) — the sample drives the live preview and
    lets the console show the ISP what a real message looks like without touching a customer.
    """

    def __init__(self, *, key, group, label, description, category, default_body, variables):
        self.key = key
        self.group = group  # "Hotspot" | "PPPoE" | "Voucher" — how the console groups them
        self.label = label
        self.description = description
        self.category = category  # notifications.models.Message.Category value
        self.default_body = default_body
        self.variables = variables  # [(name, sample), ...]

    @property
    def allowed(self) -> set:
        return {name for name, _ in self.variables}

    @property
    def samples(self) -> dict:
        return {name: sample for name, sample in self.variables}


# Common variables reused across templates (kept identical so the ISP learns them once).
_COMPANY = ("company_name", "Acme WiFi")
_FIRST = ("first_name", "Jane")
_PACKAGE = ("package_name", "Daily Unlimited")
_EXPIRY = ("expiry_date", "16 Jul 21:00")
_DAYS = ("days_left", "2 days")
_AMOUNT = ("amount", "100")
_PAYBILL = ("paybill", "4109210")
_ACCOUNT = ("account_number", "SM4837")
_USERNAME = ("username", "254712345678")
_PASSWORD = ("password", "4821")
_PCT = ("bundle_percentage_used", "95")
_REMAIN = ("bundle_data_remaining", "1.2 GB")


TEMPLATES = {
    # --- Hotspot ------------------------------------------------------------------------
    "hotspot_online": Template(
        key="hotspot_online",
        group="Hotspot",
        label="Payment received (you're online)",
        description="Sent the moment a paid hotspot session goes active — the receipt.",
        category="payment",
        default_body=(
            "You're online with @company_name. Your @package_name is active until "
            "@expiry_date. Enjoy!"
        ),
        variables=[_COMPANY, _PACKAGE, _EXPIRY, _AMOUNT, _DAYS, _FIRST],
    ),
    "hotspot_expiring": Template(
        key="hotspot_expiring",
        group="Hotspot",
        label="Expiring soon",
        description="The renewal nudge, a few minutes before a hotspot session runs out.",
        category="expiry",
        default_body=(
            "Your @company_name WiFi (@package_name) runs out in @days_left. "
            "Reconnect and pay to stay online."
        ),
        variables=[_COMPANY, _PACKAGE, _DAYS, _EXPIRY, _FIRST],
    ),
    "hotspot_data_low": Template(
        key="hotspot_data_low",
        group="Hotspot",
        label="Data nearly used",
        description="Sent once on a capped hotspot plan when the customer is near the limit.",
        category="expiry",
        default_body=(
            "@first_name, you've used @bundle_percentage_used% of your @company_name data. "
            "@bundle_data_remaining left — reconnect and pay to keep browsing."
        ),
        variables=[_FIRST, _PCT, _REMAIN, _PACKAGE, _COMPANY],
    ),
    # --- PPPoE --------------------------------------------------------------------------
    "pppoe_welcome": Template(
        key="pppoe_welcome",
        group="PPPoE",
        label="Welcome + login details",
        description="Sent when a fixed-line client is created — their username and password.",
        category="pppoe",
        default_body=(
            "Dear @first_name, welcome to @company_name. Your @package_name is active. "
            "Username: @username, Password: @password. Renews on @expiry_date."
        ),
        variables=[
            _FIRST, _USERNAME, _PASSWORD, _PACKAGE, _EXPIRY, _AMOUNT, _ACCOUNT, _PAYBILL, _COMPANY
        ],
    ),
    "pppoe_expiring": Template(
        key="pppoe_expiring",
        group="PPPoE",
        label="Renewal reminder",
        description="Sent before a fixed-line subscription falls due.",
        category="pppoe",
        default_body=(
            "Dear @first_name, your @company_name @package_name is due on @expiry_date "
            "(@days_left). Pay via paybill @paybill, account @account_number to stay connected."
        ),
        variables=[_FIRST, _USERNAME, _PACKAGE, _EXPIRY, _DAYS, _PAYBILL, _ACCOUNT, _COMPANY],
    ),
    "pppoe_expired": Template(
        key="pppoe_expired",
        group="PPPoE",
        label="Expired (suspended)",
        description="Sent when a fixed-line client is suspended for non-payment.",
        category="pppoe",
        default_body=(
            "Dear @first_name, your @company_name @package_name has expired. "
            "Pay via paybill @paybill, account @account_number to reconnect."
        ),
        variables=[_FIRST, _USERNAME, _PACKAGE, _PAYBILL, _ACCOUNT, _COMPANY],
    ),
    "pppoe_data_low": Template(
        key="pppoe_data_low",
        group="PPPoE",
        label="Fair-use nearly reached",
        description="Sent when a fixed-line client nears their fair-use (FUP) data threshold.",
        category="pppoe",
        default_body=(
            "@first_name, you've used @bundle_percentage_used% of your @package_name data. "
            "@bundle_data_remaining left this cycle."
        ),
        variables=[_FIRST, _USERNAME, _PCT, _REMAIN, _PACKAGE, _COMPANY],
    ),
    # --- Voucher ------------------------------------------------------------------------
    "voucher_issued": Template(
        key="voucher_issued",
        group="Voucher",
        label="Voucher code",
        description="Sent when you text a prepaid voucher code to a customer.",
        category="payment",
        default_body=(
            "Your @company_name @package_name voucher: @code. "
            "Valid for @duration after activation."
        ),
        variables=[
            ("code", "AB4K9T2M"),
            _PACKAGE,
            ("duration", "1 day"),
            _AMOUNT,
            _COMPANY,
        ],
    ),
}

GROUP_ORDER = ["Hotspot", "PPPoE", "Voucher"]


def get_template(key: str) -> Template | None:
    return TEMPLATES.get(key)


def body_for(operator, key: str) -> str:
    """The body to send: the ISP's enabled override, else the built-in default. Returns ""
    if the ISP has explicitly disabled the message (caller must skip sending)."""
    from .models import MessageTemplate

    tpl = TEMPLATES[key]
    row = MessageTemplate.objects.filter(operator=operator, key=key).first()
    if row is not None:
        if not row.is_enabled:
            return ""  # ISP switched this message off
        if row.body.strip():
            return row.body
    return tpl.default_body  # no override, or blank-but-enabled -> never send an empty SMS


def render(operator, key: str, context: dict) -> str:
    """Render a template for sending: pick the body, substitute the allow-listed variables
    from `context` (already-formatted strings). Unknown/omitted variables render empty.
    Returns "" when the message is disabled — the caller then sends nothing."""
    body = body_for(operator, key)
    if not body:
        return ""
    allowed = TEMPLATES[key].allowed

    def repl(m):
        name = m.group(1)
        if name in allowed:
            return str(context.get(name, "") or "")
        return m.group(0)  # not one of ours — leave it exactly as written

    return TOKEN_RE.sub(repl, body).strip()


def unknown_tokens(key: str, body: str) -> list[str]:
    """@tokens in `body` that are not valid for this template — the save-time guard against a
    typo'd variable going out as literal text."""
    allowed = TEMPLATES[key].allowed
    return sorted({t for t in TOKEN_RE.findall(body) if t not in allowed})


def preview(key: str, body: str) -> str:
    """Render `body` with the template's sample values — what the console shows the ISP."""
    samples = TEMPLATES[key].samples
    return TOKEN_RE.sub(lambda m: samples.get(m.group(1), m.group(0)), body).strip()
