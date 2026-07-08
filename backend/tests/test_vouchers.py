import pytest

from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session
from apps.vouchers.models import Voucher
from apps.vouchers.services import VoucherError, generate_batch, redeem

from .factories import PlanFactory, VoucherFactory

pytestmark = pytest.mark.django_db


def test_generate_batch_codes_are_unique_and_unambiguous(operator):
    plan = PlanFactory(operator=operator)
    vouchers = generate_batch(operator=operator, plan=plan, count=50, prefix="KIB")
    codes = [v.code for v in vouchers]
    assert len(set(codes)) == 50
    for code in codes:
        assert code.startswith("KIB")
        assert not any(c in code[3:] for c in "01OI")  # ambiguous chars excluded


def test_redeem_creates_active_session(router, django_capture_on_commit_callbacks):
    voucher = VoucherFactory(operator=router.operator)
    with django_capture_on_commit_callbacks(execute=True):
        session = redeem(code=voucher.code, mac="AA:BB:CC:DD:EE:FF")

    voucher.refresh_from_db()
    session.refresh_from_db()
    assert voucher.status == Voucher.Status.REDEEMED
    assert session.status == Session.Status.ACTIVE
    assert session.hotspot_username == voucher.code
    assert ("activate", voucher.code) in DummyAdapter.calls


def test_redeem_is_single_use(router):
    voucher = VoucherFactory(operator=router.operator)
    redeem(code=voucher.code)
    with pytest.raises(VoucherError, match="already redeemed"):
        redeem(code=voucher.code)
    assert Session.objects.filter(voucher=voucher).count() == 1


def test_redeem_is_case_insensitive(router):
    voucher = VoucherFactory(operator=router.operator, code="ABCD2345")
    session = redeem(code="abcd2345")
    assert session.voucher_id == voucher.id


def test_invalid_code_rejected(router):
    with pytest.raises(VoucherError, match="Invalid"):
        redeem(code="NOPE9999")


def test_redeem_endpoint(api_client, router):
    voucher = VoucherFactory(operator=router.operator)
    resp = api_client.post(
        "/api/v1/vouchers/redeem/", {"code": voucher.code, "mac": "AA:BB:CC:DD:EE:FF"}
    )
    assert resp.status_code == 201
    assert resp.json()["hotspot_username"] == voucher.code
    # second redemption via API fails cleanly
    resp2 = api_client.post("/api/v1/vouchers/redeem/", {"code": voucher.code})
    assert resp2.status_code == 400
