import pytest
from rest_framework.test import APIClient

from apps.notifications.providers.dummy import DummyProvider
from apps.provisioning.adapters.dummy import DummyAdapter

from .factories import OperatorFactory, RouterFactory, UserFactory


@pytest.fixture(autouse=True)
def _reset_dummies():
    DummyAdapter.calls = []
    DummyAdapter.usage = {}
    DummyAdapter.pppoe_active = {}
    DummyAdapter.portal_fails = False
    DummyProvider.sent = []
    yield


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_client(db):
    user = UserFactory(is_staff=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def operator(db):
    return OperatorFactory()


@pytest.fixture
def router(db, operator):
    return RouterFactory(operator=operator)
