"""The AI assistant's model access: pick the provider + key, ground it in the ISP's world, call it.

Key resolution (in order):
  1. the ISP's OWN key, if set — their provider, their account, their bill;
  2. otherwise the PLATFORM DEFAULT — Danamo's key + provider from the environment, never in code.
If neither exists we raise AssistantUnavailable so the console can say so honestly, rather than
500 or pretend.

We call each provider through its OFFICIAL SDK (anthropic / openai). The request is deliberately
minimal (system + messages + a tight max_tokens) so it stays fast and SDK-version-robust.
"""

import logging
from dataclasses import dataclass

from django.conf import settings as dj_settings

from .models import AISettings, Provider

logger = logging.getLogger(__name__)

#: Capable, current defaults. The platform picks the model per provider so we own the cost/quality
#: trade-off even when an ISP brings their own key.
CLAUDE_MODEL = "claude-opus-4-8"
OPENAI_MODEL = "gpt-4o"
#: A dashboard answer, not an essay — keeps latency inside the request cycle and cost predictable.
MAX_TOKENS = 1024
#: Guard rails on what the console will accept, so a runaway client can't send us a novel.
MAX_MESSAGES = 40
MAX_CHARS = 8000


class AssistantUnavailable(Exception):
    """No usable key: the ISP supplied none and the platform default isn't configured."""


class AssistantError(Exception):
    """The provider was reached but the call failed (bad key, rate limit, provider down)."""


@dataclass
class ChatConfig:
    provider: str
    api_key: str
    model: str
    source: str  # "byo" | "platform"


def settings_for(operator) -> AISettings:
    row, _ = AISettings.objects.get_or_create(operator=operator)
    return row


def platform_default_provider() -> str:
    prov = getattr(dj_settings, "AI_DEFAULT_PROVIDER", Provider.CLAUDE)
    return Provider.OPENAI if prov == Provider.OPENAI else Provider.CLAUDE


def platform_key_configured() -> bool:
    """True if the platform has a default key for its configured default provider."""
    if platform_default_provider() == Provider.OPENAI:
        return bool(getattr(dj_settings, "OPENAI_API_KEY", ""))
    return bool(getattr(dj_settings, "ANTHROPIC_API_KEY", ""))


def resolve_config(operator) -> ChatConfig:
    row = settings_for(operator)
    byo = (row.api_key or "").strip()
    if byo:
        model = CLAUDE_MODEL if row.provider == Provider.CLAUDE else OPENAI_MODEL
        return ChatConfig(provider=row.provider, api_key=byo, model=model, source="byo")

    provider = platform_default_provider()
    if provider == Provider.OPENAI:
        key, model = getattr(dj_settings, "OPENAI_API_KEY", ""), OPENAI_MODEL
    else:
        key, model = getattr(dj_settings, "ANTHROPIC_API_KEY", ""), CLAUDE_MODEL
    if not key:
        raise AssistantUnavailable(
            "The AI assistant isn't set up yet. Add your own provider API key in "
            "Settings > AI Assistant to switch it on."
        )
    return ChatConfig(provider=provider, api_key=key, model=model, source="platform")


def _snapshot(operator) -> str:
    """A cheap, live grounding line so the assistant can answer 'how's my business' truthfully."""
    from apps.pppoe.models import Client
    from apps.provisioning.models import Session

    pppoe = Client.objects.filter(operator=operator, status=Client.Status.ACTIVE).count()
    hotspot = Session.objects.filter(operator=operator, status=Session.Status.ACTIVE).count()
    return (
        f"Live snapshot for this ISP: {pppoe} active fixed-line (PPPoE) subscriber(s) and "
        f"{hotspot} active hotspot session(s)."
    )


def _company_name(operator) -> str:
    branding = getattr(operator, "branding", None)
    if branding:
        return getattr(branding, "name_for_customers", "") or operator.name
    return operator.name


def _system_prompt(operator) -> str:
    return (
        f"You are the AI assistant inside {_company_name(operator)}'s WIFI.OS dashboard. "
        "WIFI.OS is a billing and management platform for Kenyan WISPs (internet providers): "
        "customers buy WiFi via M-Pesa on a captive hotspot or as fixed-line PPPoE subscribers, "
        "and the ISP manages plans, payments, routers (MikroTik), vouchers, and messaging here. "
        f"{_snapshot(operator)}\n\n"
        "Help the operator run their ISP: answer how-to questions about the console, help draft "
        "customer messages, and reason about their numbers. Be concise and practical — give the "
        "answer directly, in a sentence or two, without preamble or step-by-step reasoning unless "
        "asked. You cannot take actions (you can't move money, change plans, or suspend anyone) — "
        "when asked to do something, explain where in the console they can do it themselves. "
        "Never invent figures; if you don't have a number, say so."
    )


def _clean(messages) -> list[dict]:
    """Coerce the client's messages into a safe {role, content} list. Raises ValueError on junk."""
    out = []
    for m in (messages or [])[-MAX_MESSAGES:]:
        role = (m or {}).get("role")
        content = (m or {}).get("content", "")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("Each message needs a role of 'user' or 'assistant' and text content.")
        content = content.strip()[:MAX_CHARS]
        if content:
            out.append({"role": role, "content": content})
    if not out or out[-1]["role"] != "user":
        raise ValueError("The conversation must end with a user message.")
    return out


def chat(operator, messages) -> str:
    """Run one assistant turn for an operator. Returns the assistant's reply text."""
    cleaned = _clean(messages)
    cfg = resolve_config(operator)
    system = _system_prompt(operator)
    try:
        if cfg.provider == Provider.OPENAI:
            return _openai_chat(cfg, system, cleaned)
        return _claude_chat(cfg, system, cleaned)
    except (AssistantUnavailable, AssistantError):
        raise
    except Exception as exc:  # provider SDKs raise their own error types — normalise them
        logger.warning("AI assistant call failed (%s): %s", cfg.provider, exc)
        raise AssistantError(
            "The AI provider couldn't be reached. Check your API key in Settings > AI Assistant."
        ) from exc


def _claude_chat(cfg: ChatConfig, system: str, messages: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.api_key)
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def _openai_chat(cfg: ChatConfig, system: str, messages: list[dict]) -> str:
    import openai

    client = openai.OpenAI(api_key=cfg.api_key)
    resp = client.chat.completions.create(
        model=cfg.model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": system}, *messages],
    )
    return (resp.choices[0].message.content or "").strip()
