"""The RAG assistant: grounding, scope refusal, and docs-gaps analytics.

The embedding model and the LLM provider are always mocked — the suite must never download a
model or need an API key. We assert our own logic: retrieval feeds grounding, an unmatched
question is logged as a gap, and every turn is recorded tenant-scoped.
"""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.assistant.models import AISettings, AssistantQuestion, PlatformAISettings
from apps.assistant.providers import ChatConfig, Provider, _system_prompt

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/assistant/chat/"
PLATFORM_URL = "/api/v1/platform/ai-settings/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def platform_owner():
    c = APIClient()
    c.force_authenticate(UserFactory(operator=None, is_staff=True, is_superuser=True,
                                     role=Role.PLATFORM_OWNER))
    return c


def _mock_provider(monkeypatch, passages):
    """Wire chat() to skip the real model + LLM: retrieval returns `passages`, the provider
    echoes a canned reply."""
    monkeypatch.setattr("apps.assistant.rag.retrieve", lambda q, **kw: passages)
    monkeypatch.setattr(
        "apps.assistant.providers.resolve_config",
        lambda op: ChatConfig(provider=Provider.CLAUDE, api_key="x", model="m", source="byo",
                              tier="byo", unlimited=True),
    )
    monkeypatch.setattr(
        "apps.assistant.providers._claude_chat", lambda cfg, system, msgs: ("Here's how.", 12, 5)
    )


class TestGroundingAndScope:
    def test_system_prompt_embeds_retrieved_docs(self):
        passages = [{"title": "Fibre plant", "heading": "Blast radius", "slug": "fibre-plant",
                     "content": "It shows every customer a fault takes offline."}]
        prompt = _system_prompt(OperatorFactory(), passages)
        assert "Blast radius" in prompt and "takes offline" in prompt
        assert "ONLY the documentation excerpts" in prompt

    def test_no_passage_prompt_tells_it_to_refuse(self):
        prompt = _system_prompt(OperatorFactory(), [])
        assert "only help with their ISP" in prompt


class TestChatEndpoint:
    def test_grounded_answer_returns_sources_and_logs_it(self, monkeypatch):
        op = OperatorFactory()
        passages = [{"title": "Fleet", "heading": "How location sharing works",
                     "content": "Only while signed in.", "slug": "fleet", "score": 0.79}]
        _mock_provider(monkeypatch, passages)

        r = owner(op).post(URL, {"messages": [
            {"role": "user", "content": "how does location sharing work?"}]}, format="json")
        assert r.status_code == 200, r.content
        body = r.json()
        assert body["reply"] == "Here's how."
        assert body["sources"][0]["slug"] == "fleet"

        row = AssistantQuestion.objects.get(operator=op)
        assert row.grounded is True
        assert row.topic == "fleet"           # non-identifying doc-page tag
        assert row.top_score == 0.79

    def test_unmatched_question_is_logged_as_a_gap(self, monkeypatch):
        op = OperatorFactory()
        _mock_provider(monkeypatch, [])        # retrieval found nothing

        r = owner(op).post(URL, {"messages": [
            {"role": "user", "content": "something the docs don't cover"}]}, format="json")
        assert r.status_code == 200
        assert r.json()["sources"] == []

        row = AssistantQuestion.objects.get(operator=op)
        assert row.grounded is False
        assert row.topic == ""                 # the empty tag IS the gap signal
        assert row.top_score is None

    def test_analytics_is_tenant_scoped(self, monkeypatch):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        _mock_provider(monkeypatch, [])
        owner(a).post(URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json")
        assert AssistantQuestion.objects.filter(operator=a).count() == 1
        assert AssistantQuestion.objects.filter(operator=b).count() == 0

    def test_requires_auth(self):
        assert APIClient().post(URL, {"messages": [
            {"role": "user", "content": "hi"}]}, format="json").status_code in (401, 403)


class TestRating:
    def _q(self, op):
        return AssistantQuestion.objects.create(operator=op, question="q", grounded=True)

    def test_thumbs_up_records_the_rating(self):
        op = OperatorFactory()
        row = self._q(op)
        r = owner(op).post(f"/api/v1/assistant/questions/{row.id}/rate/",
                           {"rating": 1}, format="json")
        assert r.status_code == 200
        row.refresh_from_db()
        assert row.rating == 1

    def test_zero_clears_the_rating(self):
        op = OperatorFactory()
        row = self._q(op)
        row.rating = -1
        row.save()
        owner(op).post(f"/api/v1/assistant/questions/{row.id}/rate/", {"rating": 0}, format="json")
        row.refresh_from_db()
        assert row.rating is None

    def test_cannot_rate_another_tenants_question(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        row = self._q(a)
        r = owner(b).post(f"/api/v1/assistant/questions/{row.id}/rate/",
                          {"rating": 1}, format="json")
        assert r.status_code == 404  # invisible across tenants


class TestTiering:
    """Free tier is capped and runs the cheap model; BYO and Pro are unlimited."""

    def _mock(self, monkeypatch, settings, limit):
        settings.ANTHROPIC_API_KEY = "platform-key"   # so the platform tier has a usable key
        monkeypatch.setattr("apps.assistant.providers.FREE_MONTHLY_LIMIT", limit)
        monkeypatch.setattr("apps.assistant.rag.retrieve", lambda q, **kw: [])
        monkeypatch.setattr("apps.assistant.providers._claude_chat", lambda *a: ("ok", 3, 2))

    def _ask(self, client):
        return client.post(URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json")

    def test_free_tier_blocks_after_the_monthly_limit(self, monkeypatch, settings):
        self._mock(monkeypatch, settings, limit=2)
        c = owner(OperatorFactory())
        assert self._ask(c).status_code == 200   # 1st
        assert self._ask(c).status_code == 200   # 2nd
        r = self._ask(c)                          # 3rd — over budget
        assert r.status_code == 402
        assert r.json()["code"] == "quota_exceeded"

    def test_byo_key_is_unlimited(self, monkeypatch, settings):
        self._mock(monkeypatch, settings, limit=1)
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"api_key": "sk-ant-xyz"})
        c = owner(op)
        for _ in range(3):  # well past the free cap
            assert self._ask(c).status_code == 200

    def test_pro_tier_is_unlimited(self, monkeypatch, settings):
        self._mock(monkeypatch, settings, limit=1)
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"pro_ai": True})
        c = owner(op)
        for _ in range(3):
            assert self._ask(c).status_code == 200

    def test_usage_endpoint_reports_tier_and_count(self):
        op = OperatorFactory()
        AssistantQuestion.objects.create(operator=op, question="q", grounded=True)
        body = owner(op).get("/api/v1/assistant/usage/").json()
        assert body["tier"] == "free"
        assert body["used"] == 1
        assert body["unlimited"] is False
        assert body["limit"] == 100 and body["remaining"] == 99

    def test_tokens_are_recorded(self, monkeypatch, settings):
        self._mock(monkeypatch, settings, limit=10)
        op = OperatorFactory()
        self._ask(owner(op))
        row = AssistantQuestion.objects.filter(operator=op).latest("id")
        assert row.tokens_in == 3 and row.tokens_out == 2


class TestConversations:
    """Saved, named chat threads — private to each staff member, transcript on the server."""

    CONVOS = "/api/v1/assistant/conversations/"

    def _mock(self, monkeypatch, settings):
        settings.ANTHROPIC_API_KEY = "platform-key"
        monkeypatch.setattr("apps.assistant.providers.FREE_MONTHLY_LIMIT", 1000)
        monkeypatch.setattr("apps.assistant.rag.retrieve", lambda q, **kw: [])
        monkeypatch.setattr("apps.assistant.providers._claude_chat", lambda *a: ("Answer.", 4, 2))

    def test_message_persists_the_transcript_and_titles_the_thread(self, monkeypatch, settings):
        self._mock(monkeypatch, settings)
        c = owner(OperatorFactory())
        convo = c.post(self.CONVOS, {}, format="json").json()
        r = c.post(f"{self.CONVOS}{convo['id']}/messages/",
                   {"content": "how do vouchers work?"}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["message"]["content"] == "Answer."

        detail = c.get(f"{self.CONVOS}{convo['id']}/").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert detail["title"] == "how do vouchers work?"     # auto-titled from the first message

    def test_conversations_are_private_to_each_user(self, monkeypatch, settings):
        self._mock(monkeypatch, settings)
        op = OperatorFactory()
        u1, u2 = owner(op), owner(op)   # two different staff of the same ISP
        mine = u1.post(self.CONVOS, {}, format="json").json()
        # u2 sees none of u1's threads, and can't open one
        assert u2.get(self.CONVOS).json()["results"] == []
        assert u2.get(f"{self.CONVOS}{mine['id']}/").status_code == 404

    def test_rename_and_delete(self, monkeypatch, settings):
        self._mock(monkeypatch, settings)
        c = owner(OperatorFactory())
        convo = c.post(self.CONVOS, {}, format="json").json()
        assert c.patch(f"{self.CONVOS}{convo['id']}/",
                       {"title": "Billing questions"}, format="json").status_code == 200
        assert c.delete(f"{self.CONVOS}{convo['id']}/").status_code == 204
        assert c.get(self.CONVOS).json()["results"] == []


class TestPlatformKey:
    """The cross-tenant key: owner-only to manage, and platform-wide rate limited on the shared
    key so a spike across ISPs can't run up the platform bill."""

    def test_a_tenant_cannot_reach_platform_settings(self):
        assert owner(OperatorFactory()).get(PLATFORM_URL).status_code == 403

    def test_platform_owner_sets_the_key_and_rate_limit(self):
        r = platform_owner().patch(
            PLATFORM_URL, {"api_key": "sk-ant-secret", "rate_limit_per_min": 30}, format="json")
        assert r.status_code == 200, r.content
        body = r.json()
        assert body["has_key"] is True
        assert body["rate_limit_per_min"] == 30
        assert "secret" not in str(body)         # the key itself is never returned

    def test_platform_wide_rate_limit_returns_429(self, monkeypatch, settings):
        cache.clear()
        settings.ANTHROPIC_API_KEY = "platform-key"
        monkeypatch.setattr("apps.assistant.providers.FREE_MONTHLY_LIMIT", 100)  # not the blocker
        monkeypatch.setattr("apps.assistant.rag.retrieve", lambda q, **kw: [])
        monkeypatch.setattr("apps.assistant.providers._claude_chat", lambda *a: ("ok", 1, 1))
        row = PlatformAISettings.load()
        row.rate_limit_per_min = 1
        row.save()

        c = owner(OperatorFactory())
        first = c.post(URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json")
        second = c.post(URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json")
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["code"] == "rate_limited"

    def test_docs_gaps_is_gated_to_platform_staff(self):
        assert owner(OperatorFactory()).get(
            "/api/v1/platform/ai-docs-gaps/").status_code == 403

    def test_docs_gaps_aggregates_across_tenants_anonymously(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        # Two answered about 'fibre-plant', one UNanswered nearest 'billing-payments'.
        AssistantQuestion.objects.create(
            operator=a, question="x", grounded=True, topic="fibre-plant")
        AssistantQuestion.objects.create(
            operator=b, question="y", grounded=True, topic="fibre-plant")
        AssistantQuestion.objects.create(
            operator=a, question="z", grounded=False, topic="billing-payments")

        body = platform_owner().get("/api/v1/platform/ai-docs-gaps/").json()
        assert body["total_questions"] == 3
        assert body["unanswered"] == 1
        # the gap is attributed to the doc it was nearest to
        assert body["gaps"][0] == {"topic": "billing-payments", "count": 1}
        top = {t["topic"]: t["count"] for t in body["top_topics"]}
        assert top["fibre-plant"] == 2
        # anonymised — rows are page slug + counts only, never the question text or the tenant
        assert set(body["gaps"][0]) == {"topic", "count"}
        assert set(body["top_topics"][0]) == {"topic", "count", "answered"}

    def test_byo_key_is_exempt_from_the_platform_rate_limit(self, monkeypatch):
        cache.clear()
        monkeypatch.setattr("apps.assistant.providers.FREE_MONTHLY_LIMIT", 100)
        monkeypatch.setattr("apps.assistant.rag.retrieve", lambda q, **kw: [])
        monkeypatch.setattr("apps.assistant.providers._claude_chat", lambda *a: ("ok", 1, 1))
        row = PlatformAISettings.load()
        row.rate_limit_per_min = 1
        row.save()
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"api_key": "sk-ant-own"})

        c = owner(op)
        for _ in range(3):  # their own key — the platform limit doesn't apply
            r = c.post(URL, {"messages": [{"role": "user", "content": "hi"}]}, format="json")
            assert r.status_code == 200
