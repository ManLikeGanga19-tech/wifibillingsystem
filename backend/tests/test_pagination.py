"""The pagination foundation: a small default page, a hard cap the client can't exceed, and a
deterministic order even when a view forgets to set one."""

import pytest
from django.urls import reverse
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.models import Role
from apps.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, StandardPagination
from apps.provisioning.models import Router

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, UserFactory

rf = APIRequestFactory()


def owner(operator):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _req(query=""):
    return Request(rf.get(f"/x/{query}"))


def test_default_page_size_is_small():
    assert StandardPagination().get_page_size(_req()) == DEFAULT_PAGE_SIZE == 25


def test_client_can_pick_a_size_within_the_cap():
    assert StandardPagination().get_page_size(_req("?page_size=10")) == 10


def test_page_size_is_hard_capped():
    # No client can ask for the whole table — the cap is what bounds GET load at scale.
    assert StandardPagination().get_page_size(_req("?page_size=100000")) == MAX_PAGE_SIZE == 100


@pytest.mark.django_db
def test_unordered_queryset_is_made_deterministic():
    op = OperatorFactory()
    for _ in range(3):
        RouterFactory(operator=op)
    qs = Router.objects.filter(operator=op).order_by()  # explicitly strip any ordering
    assert qs.ordered is False

    page = StandardPagination().paginate_queryset(qs, _req())
    ids = [r.id for r in page]
    assert ids == sorted(ids, reverse=True)  # the safety net imposed -pk


@pytest.mark.django_db
class TestListFilteringSearchOrdering:
    """Server-side search / filter / sort on a representative list endpoint (clients)."""

    URL = reverse("pppoe-client-list")

    def _clients(self, op):
        PppoeClientFactory(operator=op, full_name="Alice Wanjiru", status="active")
        PppoeClientFactory(operator=op, full_name="Bob Otieno", status="suspended")
        PppoeClientFactory(operator=op, full_name="Carol Achieng", status="active")

    def test_search_matches_a_text_field(self):
        op = OperatorFactory()
        self._clients(op)
        r = owner(op).get(self.URL, {"search": "Wanjiru"})
        names = [c["full_name"] for c in r.json()["results"]]
        assert names == ["Alice Wanjiru"]

    def test_exact_filter_by_status(self):
        op = OperatorFactory()
        self._clients(op)
        r = owner(op).get(self.URL, {"status": "active"})
        assert {c["status"] for c in r.json()["results"]} == {"active"}
        assert r.json()["count"] == 2

    def test_ordering_by_a_whitelisted_field(self):
        op = OperatorFactory()
        self._clients(op)
        client = owner(op)

        def names(ordering):
            body = client.get(self.URL, {"ordering": ordering}).json()
            return [c["full_name"] for c in body["results"]]

        assert names("full_name") == ["Alice Wanjiru", "Bob Otieno", "Carol Achieng"]
        assert names("-full_name") == ["Carol Achieng", "Bob Otieno", "Alice Wanjiru"]

    def test_pagination_envelope(self):
        op = OperatorFactory()
        self._clients(op)
        body = owner(op).get(self.URL).json()
        assert set(body) >= {"count", "next", "previous", "results"}
        assert body["count"] == 3
