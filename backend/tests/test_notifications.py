import pytest

from apps.notifications.models import Campaign, Message
from apps.notifications.providers.dummy import DummyProvider
from apps.notifications.tasks import dispatch_campaign

from .factories import SessionFactory, UserFactory

pytestmark = pytest.mark.django_db


def _campaign(operator, audience=Campaign.Audience.ALL, **kwargs):
    return Campaign.objects.create(
        operator=operator,
        name="Test blast",
        channel="sms",
        audience=audience,
        body="Habari! Bei mpya ya wiki: KSh 300.",
        **kwargs,
    )


def test_dispatch_to_all_clients(operator):
    UserFactory.create_batch(3, operator=operator)
    UserFactory(operator=operator, is_staff=True)  # staff excluded
    campaign = _campaign(operator)

    assert dispatch_campaign(campaign.pk) == 3

    campaign.refresh_from_db()
    assert campaign.total_recipients == 3
    assert campaign.sent_count == 3  # eager celery -> dummy provider
    assert campaign.status == Campaign.Status.DONE
    assert len(DummyProvider.sent) == 3
    assert Message.objects.filter(status=Message.Status.SENT).count() == 3


def test_dispatch_to_active_only(operator, router):
    active_user = UserFactory(operator=operator)
    SessionFactory(user=active_user, operator=operator, router=router)
    UserFactory(operator=operator)  # no session -> excluded

    campaign = _campaign(operator, audience=Campaign.Audience.ACTIVE)
    assert dispatch_campaign(campaign.pk) == 1
    assert DummyProvider.sent[0][0] == active_user.phone


def test_campaign_api_queues_dispatch(
    admin_client, operator, django_capture_on_commit_callbacks
):
    UserFactory.create_batch(2, operator=operator)
    with django_capture_on_commit_callbacks(execute=True):
        resp = admin_client.post(
            "/api/v1/notifications/campaigns/",
            {"name": "Promo", "channel": "sms", "audience": "all", "body": "Karibu!"},
            format="json",
        )
    assert resp.status_code == 201, resp.content
    campaign = Campaign.objects.get(pk=resp.json()["id"])
    assert campaign.total_recipients == 2
