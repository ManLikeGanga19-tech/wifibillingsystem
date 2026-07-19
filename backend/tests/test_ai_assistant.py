"""Settings > AI Assistant: the settings API (provider + encrypted BYO key), the platform-default
resolution, and the chat endpoint."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.assistant.models import AISettings, Provider
from apps.assistant.providers import (
    AssistantError,
    AssistantUnavailable,
    chat,
    resolve_config,
)

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

SETTINGS_URL = "/api/v1/assistant/settings/"
CHAT_URL = "/api/v1/assistant/chat/"

CLAUDE_KEY = "sk-ant-test-abcd1234efgh5678"
OPENAI_KEY = "sk-test-abcd1234efgh5678ijkl"


def staff(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


# --------------------------------------------------------------------------------------
# Settings API
# --------------------------------------------------------------------------------------


class TestSettingsApi:
    def test_get_defaults(self):
        op = OperatorFactory()
        body = staff(op).get(SETTINGS_URL).json()
        assert body["provider"] == "claude"
        assert body["has_own_key"] is False
        assert body["key_preview"] == ""
        assert body["platform_default_provider"] == "claude"

    def test_patch_sets_provider(self):
        op = OperatorFactory()
        resp = staff(op).patch(SETTINGS_URL, {"provider": "openai"}, format="json")
        assert resp.status_code == 200, resp.content
        assert AISettings.objects.get(operator=op).provider == "openai"

    def test_patch_stores_key_but_never_returns_it(self):
        op = OperatorFactory()
        resp = staff(op).patch(SETTINGS_URL, {"api_key": CLAUDE_KEY}, format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["has_own_key"] is True
        # A hint, never the whole secret.
        assert CLAUDE_KEY not in str(body)
        assert body["key_preview"].startswith("sk-ant-") and body["key_preview"].endswith("5678")
        # Stored (decryptably) but not plaintext-in-the-clear via the API.
        assert AISettings.objects.get(operator=op).api_key == CLAUDE_KEY

    def test_patch_rejects_a_claude_key_without_ant_prefix(self):
        op = OperatorFactory()  # default provider claude
        resp = staff(op).patch(SETTINGS_URL, {"api_key": OPENAI_KEY}, format="json")
        assert resp.status_code == 400

    def test_patch_rejects_an_openai_key_with_ant_prefix(self):
        op = OperatorFactory()
        resp = staff(op).patch(
            SETTINGS_URL, {"provider": "openai", "api_key": CLAUDE_KEY}, format="json"
        )
        assert resp.status_code == 400

    def test_patch_clears_the_key(self):
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"api_key": CLAUDE_KEY})
        resp = staff(op).patch(SETTINGS_URL, {"api_key": ""}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["has_own_key"] is False
        assert AISettings.objects.get(operator=op).api_key == ""

    def test_patch_writes_an_audit_line_without_the_key(self):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        staff(op).patch(SETTINGS_URL, {"api_key": CLAUDE_KEY}, format="json")
        log = AuditLog.objects.filter(operator=op, action="ai_settings_updated").first()
        assert log is not None
        assert CLAUDE_KEY not in str(log.metadata)
        assert log.metadata["own_key"] is True


# --------------------------------------------------------------------------------------
# Provider / key resolution
# --------------------------------------------------------------------------------------


class TestResolveConfig:
    def test_byo_key_wins(self):
        op = OperatorFactory()
        AISettings.objects.update_or_create(
            operator=op, defaults={"provider": Provider.OPENAI, "api_key": OPENAI_KEY}
        )
        cfg = resolve_config(op)
        assert cfg.source == "byo"
        assert cfg.provider == "openai"
        assert cfg.api_key == OPENAI_KEY

    @override_settings(ANTHROPIC_API_KEY="sk-ant-platform-default", AI_DEFAULT_PROVIDER="claude")
    def test_falls_back_to_platform_default(self):
        op = OperatorFactory()  # no BYO key
        cfg = resolve_config(op)
        assert cfg.source == "platform"
        assert cfg.provider == "claude"
        assert cfg.api_key == "sk-ant-platform-default"

    @override_settings(ANTHROPIC_API_KEY="", OPENAI_API_KEY="")
    def test_unavailable_when_nothing_configured(self):
        op = OperatorFactory()
        with pytest.raises(AssistantUnavailable):
            resolve_config(op)


# --------------------------------------------------------------------------------------
# chat()
# --------------------------------------------------------------------------------------


class TestChat:
    def _byo(self, op):
        AISettings.objects.update_or_create(operator=op, defaults={"api_key": CLAUDE_KEY})

    def test_chat_returns_the_provider_reply(self, monkeypatch):
        op = OperatorFactory()
        self._byo(op)
        seen = {}

        def fake_claude(cfg, system, messages):
            seen["system"] = system
            seen["messages"] = messages
            return "Your ISP looks healthy."

        monkeypatch.setattr("apps.assistant.providers._claude_chat", fake_claude)
        reply = chat(op, [{"role": "user", "content": "How am I doing?"}])
        assert reply == "Your ISP looks healthy."
        # The system prompt is grounded in this ISP.
        assert op.name in seen["system"]
        assert seen["messages"][-1]["content"] == "How am I doing?"

    def test_chat_requires_a_trailing_user_message(self, monkeypatch):
        op = OperatorFactory()
        self._byo(op)
        monkeypatch.setattr("apps.assistant.providers._claude_chat", lambda *a: "hi")
        with pytest.raises(ValueError):
            chat(op, [{"role": "assistant", "content": "hello"}])

    def test_chat_normalises_provider_errors(self, monkeypatch):
        op = OperatorFactory()
        self._byo(op)

        def boom(cfg, system, messages):
            raise RuntimeError("401 unauthorized")

        monkeypatch.setattr("apps.assistant.providers._claude_chat", boom)
        with pytest.raises(AssistantError):
            chat(op, [{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------------------
# Chat endpoint
# --------------------------------------------------------------------------------------


class TestChatEndpoint:
    @override_settings(ANTHROPIC_API_KEY="", OPENAI_API_KEY="")
    def test_endpoint_503_when_not_configured(self):
        op = OperatorFactory()  # no key anywhere
        resp = staff(op).post(
            CHAT_URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json"
        )
        assert resp.status_code == 503
        assert resp.json()["code"] == "not_configured"

    def test_endpoint_returns_reply(self, monkeypatch):
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"api_key": CLAUDE_KEY})
        monkeypatch.setattr(
            "apps.assistant.providers._claude_chat", lambda *a: "Here's your answer."
        )
        resp = staff(op).post(
            CHAT_URL, {"messages": [{"role": "user", "content": "help"}]}, format="json"
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["reply"] == "Here's your answer."
