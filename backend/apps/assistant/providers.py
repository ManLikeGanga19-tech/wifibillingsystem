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

#: Model per TIER. Free rides a cheap, fast model (a grounded Q&A answer is short, so this costs
#: the platform a fraction of a cent per question); Pro and BYO get a stronger model. Overridable
#: from settings so the platform can retune cost/quality without a deploy.
CLAUDE_MODEL_FREE = getattr(dj_settings, "AI_CLAUDE_MODEL_FREE", "claude-haiku-4-5")
CLAUDE_MODEL_PRO = getattr(dj_settings, "AI_CLAUDE_MODEL_PRO", "claude-sonnet-5")
OPENAI_MODEL_FREE = getattr(dj_settings, "AI_OPENAI_MODEL_FREE", "gpt-4o-mini")
OPENAI_MODEL_PRO = getattr(dj_settings, "AI_OPENAI_MODEL_PRO", "gpt-4o")
#: Free tier's monthly question budget per ISP. Hitting it prompts an upgrade / bring-your-own-key.
FREE_MONTHLY_LIMIT = int(getattr(dj_settings, "AI_FREE_MONTHLY_LIMIT", 100))
#: A dashboard answer, not an essay — keeps latency inside the request cycle and cost predictable.
MAX_TOKENS = 1024
#: Guard rails on what the console will accept, so a runaway client can't send us a novel.
MAX_MESSAGES = 40
MAX_CHARS = 8000


class AssistantUnavailable(Exception):
    """No usable key: the ISP supplied none and the platform default isn't configured."""


class AssistantError(Exception):
    """The provider was reached but the call failed (bad key, rate limit, provider down)."""


class AssistantQuotaExceeded(Exception):
    """A free-tier ISP has used its monthly question budget. Upgrade or add a key to continue."""


class AssistantRateLimited(Exception):
    """The shared platform key hit its platform-wide per-minute ceiling. Transient — try again."""


@dataclass
class ChatConfig:
    provider: str
    api_key: str
    model: str
    source: str    # "byo" | "platform"
    tier: str      # "free" | "pro" | "byo"
    unlimited: bool  # BYO and Pro aren't counted against the free monthly budget


def settings_for(operator) -> AISettings:
    row, _ = AISettings.objects.get_or_create(operator=operator)
    return row


def platform_default_provider() -> str:
    prov = getattr(dj_settings, "AI_DEFAULT_PROVIDER", Provider.CLAUDE)
    return Provider.OPENAI if prov == Provider.OPENAI else Provider.CLAUDE


def _platform_row():
    from .models import PlatformAISettings

    return PlatformAISettings.load()


def _platform_key_and_provider() -> tuple[str, str]:
    """The cross-tenant key + provider. The super-admin-managed DB row wins (so it can be rotated
    without a redeploy); the environment fallback covers a fresh install with nothing set yet."""
    row = _platform_row()
    if row.enabled and (row.api_key or "").strip():
        return row.api_key.strip(), row.provider
    provider = platform_default_provider()
    key = (getattr(dj_settings, "OPENAI_API_KEY", "") if provider == Provider.OPENAI
           else getattr(dj_settings, "ANTHROPIC_API_KEY", ""))
    return key, provider


def platform_key_configured() -> bool:
    """True if the platform has a usable cross-tenant key (DB row or environment fallback)."""
    key, _ = _platform_key_and_provider()
    return bool(key)


def platform_rate_ok() -> bool:
    """Platform-wide per-minute rate limit on the SHARED key — one counter for all tenants, so a
    simultaneous spike across ISPs can't run up Danamo's bill. 0 = no extra limit."""
    import time

    from django.core.cache import cache

    limit = _platform_row().rate_limit_per_min
    if limit <= 0:
        return True
    bucket = f"ai_platform_rate:{int(time.time() // 60)}"
    cache.add(bucket, 0, timeout=120)  # create the window if absent
    try:
        return cache.incr(bucket) <= limit
    except ValueError:
        # Race: the key expired between add and incr — treat as the first hit of a new window.
        cache.set(bucket, 1, timeout=120)
        return True


def _model_for(provider: str, pro: bool) -> str:
    if provider == Provider.OPENAI:
        return OPENAI_MODEL_PRO if pro else OPENAI_MODEL_FREE
    return CLAUDE_MODEL_PRO if pro else CLAUDE_MODEL_FREE


def resolve_config(operator) -> ChatConfig:
    row = settings_for(operator)
    byo = (row.api_key or "").strip()
    if byo:
        # Their key, their bill — give them the stronger model and never count them against the
        # free budget.
        return ChatConfig(provider=row.provider, api_key=byo,
                          model=_model_for(row.provider, pro=True),
                          source="byo", tier="byo", unlimited=True)

    key, provider = _platform_key_and_provider()
    if not key:
        raise AssistantUnavailable(
            "The AI assistant isn't set up yet. Add your own provider API key in "
            "Settings > AI Assistant to switch it on."
        )
    pro = bool(getattr(row, "pro_ai", False))
    return ChatConfig(provider=provider, api_key=key, model=_model_for(provider, pro),
                      source="platform", tier="pro" if pro else "free", unlimited=pro)


def _month_start():
    from django.utils import timezone

    now = timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_question_count(operator) -> int:
    from .models import AssistantQuestion

    return AssistantQuestion.objects.filter(
        operator=operator, created_at__gte=_month_start()
    ).count()


def usage_status(operator) -> dict:
    """The assistant tier + this month's usage for an ISP — drives the widget's meter and the
    'upgrade / add your key' prompt. Computed WITHOUT needing a working key, so the console can
    always show where the ISP stands."""
    row = settings_for(operator)
    byo = bool((row.api_key or "").strip())
    pro = bool(getattr(row, "pro_ai", False))
    tier = "byo" if byo else ("pro" if pro else "free")
    unlimited = byo or pro
    used = monthly_question_count(operator)
    return {
        "tier": tier,
        "unlimited": unlimited,
        "used": used,
        "limit": None if unlimited else FREE_MONTHLY_LIMIT,
        "remaining": None if unlimited else max(FREE_MONTHLY_LIMIT - used, 0),
        # The Pro price, so the console can show "Upgrade to Pro (KES X/mo)" without a second call.
        "pro_monthly_fee": str(getattr(dj_settings, "AI_PRO_MONTHLY_FEE", "")),
    }


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


def _docs_context(passages: list[dict]) -> str:
    """Format retrieved doc passages as grounding the model must answer from."""
    if not passages:
        return (
            "No documentation passage matched this question. If it is about how WIFI.OS works "
            "and you are not sure, say you don't have that in the docs rather than guessing. If it "
            "is unrelated to this ISP or to WIFI.OS, say you can only help with their ISP and how "
            "WIFI.OS works."
        )
    blocks = "\n\n".join(
        f"[{p['title']}{' — ' + p['heading'] if p['heading'] else ''}]\n{p['content']}"
        for p in passages
    )
    return (
        "Answer how-to questions using ONLY the documentation excerpts below. If they don't cover "
        "it, say so plainly instead of inventing steps. Cite the page name you used.\n\n"
        f"DOCUMENTATION:\n{blocks}"
    )


def _system_prompt(operator, passages: list[dict]) -> str:
    return (
        f"You are the AI assistant inside {_company_name(operator)}'s WIFI.OS dashboard. "
        "WIFI.OS is a billing and management platform for Kenyan WISPs (internet providers): "
        "customers buy WiFi via M-Pesa on a captive hotspot or as fixed-line PPPoE subscribers, "
        "and the ISP manages plans, payments, routers (MikroTik), vouchers, and messaging here. "
        f"{_snapshot(operator)}\n\n"
        "SCOPE: only help with THIS ISP and how WIFI.OS works. Politely decline anything else. "
        "Be concise and practical — give the answer directly, in a sentence or two, without "
        "preamble unless asked. You cannot take actions (you can't move money, change plans, or "
        "suspend anyone); when asked to do something, say where in the console they do it. Never "
        "invent figures; if you don't have a number, say so.\n\n"
        f"{_docs_context(passages)}"
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


def chat(operator, messages) -> dict:
    """Run one assistant turn for an operator, grounded in the product docs.

    Returns {reply, grounded, top_score, sources}: the answer plus the retrieval signal the view
    logs for the docs-gaps analytics and renders as citations.
    """
    cleaned = _clean(messages)
    cfg = resolve_config(operator)

    # Free-tier budget: enforced BEFORE we spend a token. BYO and Pro are unlimited.
    if not cfg.unlimited and monthly_question_count(operator) >= FREE_MONTHLY_LIMIT:
        raise AssistantQuotaExceeded(
            f"You've used your {FREE_MONTHLY_LIMIT} free AI questions this month. Upgrade to Pro "
            "or add your own API key in Settings > AI Assistant for unlimited use."
        )

    # Platform-wide rate limit on the shared key (BYO uses the tenant's own key, so it's exempt).
    if cfg.source == "platform" and not platform_rate_ok():
        raise AssistantRateLimited(
            "The AI assistant is busy right now. Please try again in a moment."
        )

    question = cleaned[-1]["content"]

    # Retrieval is best-effort: if the vector store is empty or errors, we still answer (the
    # model just gets the "no passage matched" grounding and leans on scope + refusal).
    try:
        from .rag import retrieve

        passages = retrieve(question)
    except Exception as exc:
        logger.warning("RAG retrieval failed: %s", exc)
        passages = []

    system = _system_prompt(operator, passages)
    try:
        if cfg.provider == Provider.OPENAI:
            reply, tokens_in, tokens_out = _openai_chat(cfg, system, cleaned)
        else:
            reply, tokens_in, tokens_out = _claude_chat(cfg, system, cleaned)
    except (AssistantUnavailable, AssistantError):
        raise
    except Exception as exc:  # provider SDKs raise their own error types — normalise them
        logger.warning("AI assistant call failed (%s): %s", cfg.provider, exc)
        raise AssistantError(
            "The AI provider couldn't be reached. Check your API key in Settings > AI Assistant."
        ) from exc

    # Topic tag for analytics: the doc a question is ABOUT — the grounded page when we had one,
    # else the NEAREST page (below threshold) so an unanswered question still says which docs to
    # improve. Non-identifying (a page slug), safe to aggregate across tenants.
    if passages:
        topic = passages[0]["slug"]
    else:
        try:
            from .rag import retrieve

            near = retrieve(question, k=1, min_score=0.0)
            topic = near[0]["slug"] if near else ""
        except Exception:
            topic = ""

    return {
        "reply": reply,
        "grounded": bool(passages),
        "top_score": passages[0]["score"] if passages else None,
        "sources": [
            {"slug": p["slug"], "title": p["title"], "heading": p["heading"]} for p in passages
        ],
        "topic": topic,
        "tier": cfg.tier,
        "model": cfg.model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def _claude_chat(cfg: ChatConfig, system: str, messages: list[dict]) -> tuple[str, int, int]:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.api_key)
    resp = client.messages.create(
        model=cfg.model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    usage = getattr(resp, "usage", None)
    return text, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0


def _openai_chat(cfg: ChatConfig, system: str, messages: list[dict]) -> tuple[str, int, int]:
    import openai

    client = openai.OpenAI(api_key=cfg.api_key)
    resp = client.chat.completions.create(
        model=cfg.model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": system}, *messages],
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    t_in = getattr(usage, "prompt_tokens", 0) or 0
    t_out = getattr(usage, "completion_tokens", 0) or 0
    return text, t_in, t_out
