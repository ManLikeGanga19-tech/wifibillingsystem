from datetime import timedelta

import pytest
from django.utils import timezone

from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session
from apps.provisioning.tasks import expire_sessions

from .factories import SessionFactory

pytestmark = pytest.mark.django_db


def test_expired_sessions_are_cut_off():
    past = SessionFactory(expires_at=timezone.now() - timedelta(minutes=5))
    future = SessionFactory(expires_at=timezone.now() + timedelta(hours=1))

    assert expire_sessions() == 1

    past.refresh_from_db()
    future.refresh_from_db()
    assert past.status == Session.Status.EXPIRED
    assert future.status == Session.Status.ACTIVE
    assert ("suspend", past.hotspot_username) in DummyAdapter.calls
    assert ("suspend", future.hotspot_username) not in DummyAdapter.calls


def test_expiry_sweep_is_idempotent():
    session = SessionFactory(expires_at=timezone.now() - timedelta(minutes=5))
    assert expire_sessions() == 1
    assert expire_sessions() == 0  # second sweep finds nothing
    assert DummyAdapter.calls.count(("suspend", session.hotspot_username)) == 1


def test_non_active_sessions_ignored():
    SessionFactory(
        expires_at=timezone.now() - timedelta(minutes=5), status=Session.Status.SUSPENDED
    )
    assert expire_sessions() == 0
