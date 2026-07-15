"""Settings > Hotspot: the captive-portal look and the subscriber lifecycle.

The parts that carry weight and so get the hard tests:
  * a portal TEMPLATE can only be one the portal can render (validated against the registry);
  * a background image is customer bytes we serve on, so it is re-encoded, not stored raw;
  * timer_start_mode HOLDS the clock until first login — the expiry sweep must not cut a
    held session, and the usage sync must start it the moment the subscriber connects;
  * pruning deletes a customer record, so it is conservative and never touches someone
    recently active, currently online, or blocked;
  * one ISP's settings are theirs alone.
"""

import base64
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.branding import BrandingError, process_background
from apps.core.models import Branding, HotspotSettings
from apps.core.portal_templates import DEFAULT_TEMPLATE, TEMPLATE_IDS
from apps.provisioning.models import Session

from .factories import (
    OperatorFactory,
    PlanFactory,
    RouterFactory,
    SessionFactory,
    SubscriberFactory,
    TransactionFactory,
    UserFactory,
    VoucherFactory,
)

pytestmark = pytest.mark.django_db

BRANDING = "/api/v1/operator/branding/"
BACKGROUND = "/api/v1/operator/branding/background/"
HOTSPOT = "/api/v1/operator/hotspot/"
PUBLIC = "/api/v1/branding/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def a_jpeg(size=(200, 120), color=(30, 90, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


# --- the template registry --------------------------------------------------------------


class TestPortalTemplate:
    def test_the_registry_has_a_valid_default(self):
        assert DEFAULT_TEMPLATE in TEMPLATE_IDS
        assert len(TEMPLATE_IDS) == 19

    def test_a_known_template_is_accepted(self):
        op = OperatorFactory()
        resp = owner(op).patch(BRANDING, {"portal_template": "neon"}, format="json")
        assert resp.status_code == 200
        assert Branding.objects.get(operator=op).portal_template == "neon"

    def test_an_unknown_template_is_refused(self):
        op = OperatorFactory()
        resp = owner(op).patch(BRANDING, {"portal_template": "chartreuse"}, format="json")
        assert resp.status_code == 400
        # And nothing was written.
        assert not Branding.objects.filter(
            operator=op, portal_template="chartreuse"
        ).exists()

    def test_branding_get_exposes_the_look_and_the_catalogue(self):
        op = OperatorFactory()
        body = owner(op).get(BRANDING).json()
        assert body["portal_template"] == DEFAULT_TEMPLATE
        # The picker renders from this — [id, label] pairs, one per template.
        ids = {row[0] for row in body["portal_templates"]}
        assert ids == set(TEMPLATE_IDS)

    def test_public_endpoint_carries_the_look_to_the_portal(self):
        op = OperatorFactory()
        b = Branding.objects.create(
            operator=op, portal_template="vault", portal_language="en",
            post_purchase_redirect="https://x.co.ke",
        )
        b.save()
        client = APIClient()
        resp = client.get(PUBLIC, HTTP_HOST=f"{op.slug}.wifios.co.ke")
        # Tenant resolves by subdomain; if the test host isn't wired, fall back to ?router.
        body = resp.json()
        assert "portal_template" in body
        assert "background_image" in body
        assert "post_purchase_redirect" in body


# --- the background image ---------------------------------------------------------------


class TestBackground:
    def test_a_real_image_is_re_encoded_to_a_jpeg_data_uri(self):
        uri = process_background(a_jpeg())
        assert uri.startswith("data:image/jpeg;base64,")
        raw = base64.b64decode(uri.split(",", 1)[1])
        assert Image.open(io.BytesIO(raw)).format == "JPEG"

    def test_a_large_image_is_shrunk(self):
        uri = process_background(a_jpeg(size=(3000, 2000)))
        raw = base64.b64decode(uri.split(",", 1)[1])
        w, h = Image.open(io.BytesIO(raw)).size
        assert max(w, h) <= 1600

    def test_a_non_image_is_refused(self):
        with pytest.raises(BrandingError):
            process_background(b"definitely not an image")

    def test_upload_then_clear_through_the_api(self):
        op = OperatorFactory()
        c = owner(op)
        up = c.post(
            BACKGROUND,
            {"background": io.BytesIO(a_jpeg())},
            format="multipart",
        )
        assert up.status_code == 200
        assert Branding.objects.get(operator=op).background_image.startswith("data:image/jpeg")

        cleared = c.delete(BACKGROUND)
        assert cleared.status_code == 200
        assert Branding.objects.get(operator=op).background_image == ""


# --- lifecycle settings endpoint --------------------------------------------------------


class TestHotspotSettingsEndpoint:
    def test_defaults_and_choices(self):
        op = OperatorFactory()
        body = owner(op).get(HOTSPOT).json()
        assert body["timer_start_mode"] == "on_purchase"
        assert body["inactive_prune_days"] is None
        assert body["voucher_expiry_days"] == 0
        assert 30 in body["choices"]["prune_days"]

    def test_valid_patch_is_stored(self):
        op = OperatorFactory()
        resp = owner(op).patch(
            HOTSPOT,
            {
                "timer_start_mode": "on_login",
                "inactive_prune_days": 30,
                "username_prefix": "sm",
                "voucher_expiry_days": 45,
            },
            format="json",
        )
        assert resp.status_code == 200
        row = HotspotSettings.objects.get(operator=op)
        assert row.timer_start_mode == "on_login"
        assert row.inactive_prune_days == 30
        assert row.username_prefix == "sm"
        assert row.voucher_expiry_days == 45

    def test_a_prune_value_off_the_allow_list_is_refused(self):
        op = OperatorFactory()
        resp = owner(op).patch(HOTSPOT, {"inactive_prune_days": 11}, format="json")
        assert resp.status_code == 400

    def test_never_prune_is_allowed(self):
        op = OperatorFactory()
        resp = owner(op).patch(HOTSPOT, {"inactive_prune_days": None}, format="json")
        assert resp.status_code == 200
        assert HotspotSettings.objects.get(operator=op).inactive_prune_days is None

    def test_a_bad_prefix_is_refused(self):
        op = OperatorFactory()
        resp = owner(op).patch(HOTSPOT, {"username_prefix": "no spaces!"}, format="json")
        assert resp.status_code == 400

    def test_settings_are_tenant_isolated(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        owner(a).patch(HOTSPOT, {"username_prefix": "aa"}, format="json")
        owner(b).patch(HOTSPOT, {"username_prefix": "bb"}, format="json")
        assert HotspotSettings.objects.get(operator=a).username_prefix == "aa"
        assert HotspotSettings.objects.get(operator=b).username_prefix == "bb"


# --- timer_start_mode wiring ------------------------------------------------------------


class TestTimerStartMode:
    def test_default_starts_the_clock_at_purchase(self):
        from apps.provisioning.services import create_session_for_transaction

        op = OperatorFactory()
        RouterFactory(operator=op)
        tx = TransactionFactory(operator=op)
        session = create_session_for_transaction(tx)
        assert session.clock_started is True

    def test_on_login_holds_the_clock(self):
        from apps.provisioning.services import create_session_for_transaction

        op = OperatorFactory()
        HotspotSettings.objects.create(operator=op, timer_start_mode="on_login")
        RouterFactory(operator=op)
        tx = TransactionFactory(operator=op)
        session = create_session_for_transaction(tx)
        assert session.clock_started is False

    def test_the_expiry_sweep_never_cuts_a_held_clock(self):
        from apps.provisioning.tasks import expire_sessions

        op = OperatorFactory()
        # Held session whose provisional window is already in the past.
        session = SessionFactory(
            operator=op,
            clock_started=False,
            status=Session.Status.ACTIVE,
            starts_at=timezone.now() - timedelta(hours=2),
            expires_at=timezone.now() - timedelta(hours=1),
        )
        expire_sessions()
        session.refresh_from_db()
        assert session.status == Session.Status.ACTIVE  # untouched — the clock never started

    def test_first_login_starts_a_held_clock(self):
        from apps.provisioning.adapters.dummy import DummyAdapter
        from apps.provisioning.tasks import sync_hotspot_usage

        op = OperatorFactory()
        router = RouterFactory(operator=op)
        plan = PlanFactory(operator=op, duration=timedelta(hours=3))
        session = SessionFactory(
            operator=op,
            router=router,
            plan=plan,
            clock_started=False,
            status=Session.Status.ACTIVE,
        )
        # The subscriber connects: the router now lists them active.
        DummyAdapter.usage = {session.hotspot_username: (1024, 512)}
        sync_hotspot_usage()

        session.refresh_from_db()
        assert session.clock_started is True
        # The window now runs the full plan duration from this moment, not from purchase.
        assert session.expires_at > timezone.now() + timedelta(hours=2, minutes=50)


# --- pruning dormant subscribers --------------------------------------------------------


class TestPrune:
    def test_prune_deletes_dormant_but_spares_the_rest(self):
        from apps.provisioning.hotspot_lifecycle import prune_dormant_subscribers

        op = OperatorFactory()
        HotspotSettings.objects.create(operator=op, inactive_prune_days=30)
        old = timezone.now() - timedelta(days=90)

        # Dormant: created long ago, no sessions -> pruned.
        dormant = SubscriberFactory(operator=op)
        Subscriber_setattr_created(dormant, old)

        # Recently created -> kept (never delete a fresh row).
        SubscriberFactory(operator=op)

        # Blocked, even if dormant -> kept (deletion would lift the block).
        blocked = SubscriberFactory(operator=op, is_blocked=True)
        Subscriber_setattr_created(blocked, old)

        # Has a currently-live session -> kept.
        online = SubscriberFactory(operator=op)
        Subscriber_setattr_created(online, old)
        SessionFactory(
            operator=op, subscriber=online, status=Session.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        pruned = prune_dormant_subscribers()
        assert pruned == 1
        from apps.accounts.models import Subscriber

        remaining = set(Subscriber.objects.filter(operator=op).values_list("id", flat=True))
        assert dormant.id not in remaining
        assert blocked.id in remaining
        assert online.id in remaining

    def test_prune_is_off_by_default(self):
        from apps.provisioning.hotspot_lifecycle import prune_dormant_subscribers

        op = OperatorFactory()  # no HotspotSettings row / prune days unset
        old = timezone.now() - timedelta(days=400)
        s = SubscriberFactory(operator=op)
        Subscriber_setattr_created(s, old)
        assert prune_dormant_subscribers() == 0
        from apps.accounts.models import Subscriber

        assert Subscriber.objects.filter(id=s.id).exists()


# --- voucher expiry ---------------------------------------------------------------------


class TestVoucherExpiry:
    def test_old_unused_vouchers_expire_but_redeemed_are_untouched(self):
        from apps.vouchers.models import Voucher
        from apps.vouchers.services import expire_unused_vouchers

        op = OperatorFactory()
        HotspotSettings.objects.create(operator=op, voucher_expiry_days=30)
        old = timezone.now() - timedelta(days=60)

        stale = VoucherFactory(operator=op, status=Voucher.Status.UNUSED)
        _set_created(stale, old)
        redeemed = VoucherFactory(operator=op, status=Voucher.Status.REDEEMED)
        _set_created(redeemed, old)
        fresh = VoucherFactory(operator=op, status=Voucher.Status.UNUSED)  # created now

        assert expire_unused_vouchers() == 1
        assert Voucher.objects.get(id=stale.id).status == Voucher.Status.EXPIRED
        assert Voucher.objects.get(id=redeemed.id).status == Voucher.Status.REDEEMED
        assert Voucher.objects.get(id=fresh.id).status == Voucher.Status.UNUSED

    def test_zero_days_never_expires(self):
        from apps.vouchers.models import Voucher
        from apps.vouchers.services import expire_unused_vouchers

        op = OperatorFactory()
        HotspotSettings.objects.create(operator=op, voucher_expiry_days=0)
        v = VoucherFactory(operator=op, status=Voucher.Status.UNUSED)
        _set_created(v, timezone.now() - timedelta(days=999))
        assert expire_unused_vouchers() == 0
        assert Voucher.objects.get(id=v.id).status == Voucher.Status.UNUSED


def Subscriber_setattr_created(subscriber, when):
    """created_at is auto_now_add; bypass it with a direct UPDATE for the dormancy tests."""
    from apps.accounts.models import Subscriber

    Subscriber.objects.filter(pk=subscriber.pk).update(created_at=when)


def _set_created(voucher, when):
    from apps.vouchers.models import Voucher

    Voucher.objects.filter(pk=voucher.pk).update(created_at=when)
