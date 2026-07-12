"""The safety net for a lost M-Pesa callback.

The failure this exists for, seen live: the callback URL was a dead ngrok tunnel, so
EVERY payment's callback vanished and was only confirmed minutes later by reconciliation
— long after the portal gave up and the customer's phone stopped trying to log in. The
voucher path worked because it never needed a callback.

So reconciliation is not housekeeping; it is what connects a paying customer when the
callback is lost, and it has to fire while they are still standing at the hotspot. These
tests pin that behaviour: fast enough to matter, and it actually provisions.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.payments.models import Transaction
from apps.payments.tasks import RECONCILE_AFTER_SECONDS, reconcile_pending_transactions
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session

from .factories import RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db


def _age(tx, seconds):
    """Backdate a transaction so the reconcile cutoff sees it (or not)."""
    Transaction.objects.filter(pk=tx.pk).update(
        created_at=timezone.now() - timedelta(seconds=seconds)
    )


def _query_returns(mocker, result_code="0"):
    mocker.patch(
        "apps.payments.daraja.DarajaClient.__init__", return_value=None
    )
    mocker.patch(
        "apps.payments.daraja.DarajaClient.stk_query",
        return_value={"ResultCode": result_code, "ResultDesc": "ok"},
    )


class TestFastEnoughToMatter:
    def test_a_lost_callback_is_rescued_within_the_portal_window(self):
        """The whole point: ~25s, not 2 minutes. A customer watching a spinner must
        be connected while they are still watching it."""
        assert RECONCILE_AFTER_SECONDS <= 45, (
            "Reconciliation must fire inside the portal's ~2-min poll window, or a "
            "lost callback strands a paid customer."
        )

    def test_a_pending_payment_older_than_the_window_is_settled_and_provisioned(
        self, mocker, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, status=Transaction.Status.PENDING)
        _age(tx, RECONCILE_AFTER_SECONDS + 5)
        _query_returns(mocker, "0")  # Daraja confirms it was paid

        with django_capture_on_commit_callbacks(execute=True):
            settled = reconcile_pending_transactions()

        assert settled == 1
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.RECONCILED
        # ...and crucially it CONNECTED them — reconciliation must provision, or the
        # money is confirmed but the phone still has no internet.
        session = Session.objects.get(transaction=tx)
        assert session.status == Session.Status.ACTIVE
        assert ("activate", tx.phone) in DummyAdapter.calls

    def test_a_too_fresh_payment_is_left_alone(self, mocker):
        """Don't query a prompt the customer may still be entering their PIN into."""
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, status=Transaction.Status.PENDING)
        _age(tx, 5)  # only 5s old
        q = mocker.patch("apps.payments.daraja.DarajaClient.stk_query")

        reconcile_pending_transactions()

        q.assert_not_called()
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.PENDING

    def test_still_processing_keeps_it_pending_without_burning_attempts(self, mocker):
        """The customer is still on the PIN prompt. We retry next tick; we do not use
        up their reconciliation attempts waiting for them."""
        from apps.payments.daraja import DarajaError

        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, status=Transaction.Status.PENDING)
        _age(tx, RECONCILE_AFTER_SECONDS + 5)
        mocker.patch("apps.payments.daraja.DarajaClient.__init__", return_value=None)
        mocker.patch(
            "apps.payments.daraja.DarajaClient.stk_query",
            side_effect=DarajaError("500.001.1001 still processing"),
        )

        reconcile_pending_transactions()

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.PENDING
        assert tx.reconcile_attempts == 0  # not burned

    def test_a_cancelled_payment_is_marked_failed_not_reconciled(self, mocker):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, status=Transaction.Status.PENDING)
        _age(tx, RECONCILE_AFTER_SECONDS + 5)
        _query_returns(mocker, "1032")  # cancelled by user

        reconcile_pending_transactions()

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.FAILED
        assert not Session.objects.filter(transaction=tx).exists()
