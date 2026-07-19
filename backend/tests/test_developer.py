"""Settings > Developer: API tokens (management + authentication) and webhooks (management +
signed dispatch)."""

import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.developer.dispatch import emit_event
from apps.developer.models import ApiToken, Webhook, hash_token
from apps.developer.tasks import deliver_webhook, sign

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

TOKENS_URL = "/api/v1/developer/tokens/"
HOOKS_URL = "/api/v1/developer/webhooks/"
EVENTS_URL = "/api/v1/developer/webhook-events/"


def staff(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


# --------------------------------------------------------------------------------------
# API token management
# --------------------------------------------------------------------------------------


class TestTokenApi:
    def test_create_returns_plaintext_once_and_stores_only_a_hash(self):
        op = OperatorFactory()
        resp = staff(op).post(TOKENS_URL, {"name": "mpesa-reconciler"}, format="json")
        assert resp.status_code == 201, resp.content
        plaintext = resp.json()["token"]
        assert plaintext.startswith("wos_")
        row = ApiToken.objects.get(operator=op)
        # Only the hash is stored — the plaintext is nowhere in the DB.
        assert row.token_hash == hash_token(plaintext)
        assert plaintext not in (row.token_hash, row.prefix)

    def test_list_hides_the_secret_and_shows_only_active(self):
        op = OperatorFactory()
        c = staff(op)
        c.post(TOKENS_URL, {"name": "a"}, format="json")
        body = c.get(TOKENS_URL).json()
        rows = body["results"] if isinstance(body, dict) and "results" in body else body
        assert len(rows) == 1
        assert "token" not in rows[0] and "token_hash" not in rows[0]

    def test_revoke_drops_it_from_the_list(self):
        op = OperatorFactory()
        c = staff(op)
        tid = c.post(TOKENS_URL, {"name": "a"}, format="json").json()["id"]
        assert c.delete(f"{TOKENS_URL}{tid}/").status_code == 204
        body = c.get(TOKENS_URL).json()
        rows = body["results"] if isinstance(body, dict) else body
        assert rows == []
        # The row survives (audit trail) but is marked revoked.
        assert ApiToken.objects.get(pk=tid).revoked_at is not None

    def test_another_isp_cannot_see_my_tokens(self):
        mine, theirs = OperatorFactory(slug="mine"), OperatorFactory(slug="theirs")
        staff(mine).post(TOKENS_URL, {"name": "mine"}, format="json")
        body = staff(theirs).get(TOKENS_URL).json()
        rows = body["results"] if isinstance(body, dict) else body
        assert rows == []


# --------------------------------------------------------------------------------------
# API token authentication
# --------------------------------------------------------------------------------------


class TestTokenAuth:
    def _mint(self, op):
        return staff(op).post(TOKENS_URL, {"name": "ci"}, format="json").json()["token"]

    def test_token_authenticates_a_request(self):
        op = OperatorFactory()
        token = self._mint(op)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        resp = c.get(TOKENS_URL)
        assert resp.status_code == 200
        # It also stamps last_used_at.
        assert ApiToken.objects.get(operator=op).last_used_at is not None

    def test_revoked_token_is_rejected(self):
        op = OperatorFactory()
        token = self._mint(op)
        ApiToken.objects.filter(operator=op).update(revoked_at="2020-01-01T00:00:00Z")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        assert c.get(TOKENS_URL).status_code == 401

    def test_garbage_token_is_rejected(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Token wos_not-a-real-token")
        assert c.get(TOKENS_URL).status_code == 401


# --------------------------------------------------------------------------------------
# Webhook management
# --------------------------------------------------------------------------------------


class TestWebhookApi:
    def test_create_reveals_the_secret_once_then_masks_it(self):
        op = OperatorFactory()
        c = staff(op)
        resp = c.post(
            HOOKS_URL,
            {"label": "Slack", "url": "https://ex.com/hook", "events": ["payment.received"]},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        secret = resp.json()["secret"]
        assert secret.startswith("whsec_")  # auto-generated
        # On list it is only ever masked.
        body = c.get(HOOKS_URL).json()
        row = (body["results"] if isinstance(body, dict) else body)[0]
        assert row["secret_preview"] and secret not in str(row)

    def test_unknown_event_is_rejected(self):
        op = OperatorFactory()
        resp = staff(op).post(
            HOOKS_URL,
            {"label": "x", "url": "https://ex.com/h", "events": ["not.a.real.event"]},
            format="json",
        )
        assert resp.status_code == 400

    def test_delete_removes_it(self):
        op = OperatorFactory()
        c = staff(op)
        hid = c.post(
            HOOKS_URL,
            {"label": "x", "url": "https://ex.com/h", "events": ["voucher.redeemed"]},
            format="json",
        ).json()["id"]
        assert c.delete(f"{HOOKS_URL}{hid}/").status_code == 204
        assert not Webhook.objects.filter(pk=hid).exists()

    def test_events_catalog(self):
        op = OperatorFactory()
        keys = {e["key"] for e in staff(op).get(EVENTS_URL).json()["events"]}
        assert {"payment.received", "voucher.redeemed", "ticket.opened"} <= keys


# --------------------------------------------------------------------------------------
# Dispatch + signed delivery
# --------------------------------------------------------------------------------------


class TestDispatch:
    def _hook(self, op, events, **extra):
        return Webhook.objects.create(
            operator=op, label="h", url="https://ex.com/hook", events=events, **extra
        )

    def test_emit_queues_only_matching_active_hooks(
        self, monkeypatch, django_capture_on_commit_callbacks
    ):
        op = OperatorFactory()
        want = self._hook(op, ["payment.received"])
        self._hook(op, ["voucher.redeemed"])  # different event
        self._hook(op, ["payment.received"], is_active=False)  # inactive
        self._hook(OperatorFactory(slug="other"), ["payment.received"])  # other ISP

        queued = []
        monkeypatch.setattr(
            "apps.developer.tasks.deliver_webhook.delay", lambda hid, payload: queued.append(hid)
        )
        with django_capture_on_commit_callbacks(execute=True):
            emit_event(op, "payment.received", {"amount": "500"})
        assert queued == [want.pk]

    def test_emit_ignores_unknown_events(self, monkeypatch, django_capture_on_commit_callbacks):
        op = OperatorFactory()
        self._hook(op, ["payment.received"])
        queued = []
        monkeypatch.setattr(
            "apps.developer.tasks.deliver_webhook.delay", lambda *a: queued.append(a)
        )
        with django_capture_on_commit_callbacks(execute=True):
            emit_event(op, "not.an.event", {})
        assert queued == []

    def test_delivery_signs_the_body_and_records_status(self, monkeypatch):
        op = OperatorFactory()
        hook = self._hook(op, ["payment.received"])
        captured = {}

        class FakeResp:
            status_code = 200
            is_success = True

        def fake_post(url, content, headers, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = content
            return FakeResp()

        monkeypatch.setattr("apps.developer.tasks.httpx.post", fake_post)
        payload = {"event": "payment.received", "data": {"amount": "500"}}
        deliver_webhook(hook.pk, payload)

        # The signature is HMAC-SHA256 of the exact bytes we sent, with the hook's secret.
        expected = hmac.new(
            hook.secret.encode(), captured["body"], hashlib.sha256
        ).hexdigest()
        assert captured["headers"]["X-WIFIOS-Signature"] == f"sha256={expected}"
        assert captured["headers"]["X-WIFIOS-Event"] == "payment.received"
        assert captured["body"] == json.dumps(payload, separators=(",", ":")).encode()
        hook.refresh_from_db()
        assert hook.last_status == 200

    def test_sign_is_stable(self):
        assert sign("s3cret", b"{}") == hmac.new(b"s3cret", b"{}", hashlib.sha256).hexdigest()
