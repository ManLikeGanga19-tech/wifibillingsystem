from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.models import Role, Subscriber, User
from apps.core.models import Operator
from apps.payments.models import Transaction
from apps.plans.models import Plan
from apps.provisioning.models import Router, Session
from apps.vouchers.models import Voucher


class OperatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Operator
        django_get_or_create = ("slug",)

    # Names must be UNIQUE (case-insensitively) — Daniel: "no duplicate slugs or
    # company names". A hardcoded name here meant any test with two operators
    # tripped the constraint, which is the constraint working as intended.
    name = factory.Sequence(lambda n: f"Test WISP {n}")
    slug = "test-wisp"
    status = Operator.Status.ACTIVE

    # `can_transact` requires ACTIVE **and** a verified settlement account. The
    # default factory operator is a normal, live, trading ISP, so it has one.
    # A test that wants an unverified ISP passes settlement_verified_at=None.
    settlement_method = Operator.Settlement.PAYBILL
    settlement_paybill = factory.Sequence(lambda n: f"{600000 + n}")
    settlement_name = factory.LazyAttribute(lambda o: o.name)
    settlement_verified_at = factory.LazyFunction(timezone.now)


class UserFactory(factory.django.DjangoModelFactory):
    """Login accounts: platform staff and ISP staff."""

    class Meta:
        model = User

    operator = factory.SubFactory(OperatorFactory)
    phone = factory.Sequence(lambda n: f"2547{n:08d}")
    name = factory.Faker("name")
    role = Role.TENANT_OWNER


class SubscriberFactory(factory.django.DjangoModelFactory):
    """Customers: a phone that buys WiFi from one ISP."""

    class Meta:
        model = Subscriber

    operator = factory.SubFactory(OperatorFactory)
    phone = factory.Sequence(lambda n: f"2547{n + 50_000_000:08d}")
    name = factory.Faker("name")


class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan

    operator = factory.SubFactory(OperatorFactory)
    name = factory.Sequence(lambda n: f"Plan {n}")
    price = 30
    duration = timedelta(hours=1)
    download_kbps = 5120
    upload_kbps = 2048


class RouterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Router

    operator = factory.SubFactory(OperatorFactory)
    name = factory.Sequence(lambda n: f"Router {n}")
    management_host = "10.0.0.1"
    provisioning_backend = Router.Backend.DUMMY


class TransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Transaction

    operator = factory.SubFactory(OperatorFactory)
    subscriber = factory.SubFactory(
        SubscriberFactory, operator=factory.SelfAttribute("..operator")
    )
    plan = factory.SubFactory(PlanFactory, operator=factory.SelfAttribute("..operator"))
    phone = factory.LazyAttribute(lambda o: o.subscriber.phone)
    amount = factory.LazyAttribute(lambda o: o.plan.price)
    checkout_request_id = factory.Sequence(lambda n: f"ws_CO_test_{n:06d}")


class SessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Session

    operator = factory.SubFactory(OperatorFactory)
    subscriber = factory.SubFactory(
        SubscriberFactory, operator=factory.SelfAttribute("..operator")
    )
    plan = factory.SubFactory(PlanFactory, operator=factory.SelfAttribute("..operator"))
    router = factory.SubFactory(RouterFactory, operator=factory.SelfAttribute("..operator"))
    transaction = factory.SubFactory(
        TransactionFactory, operator=factory.SelfAttribute("..operator")
    )
    hotspot_username = factory.LazyAttribute(lambda o: o.subscriber.phone)
    hotspot_password = "123456"
    starts_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    status = Session.Status.ACTIVE


class ServicePlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "pppoe.ServicePlan"

    operator = factory.SubFactory(OperatorFactory)
    name = factory.Sequence(lambda n: f"Home {n}Mbps")
    price = 2000
    download_kbps = 10240
    upload_kbps = 5120
    mikrotik_profile = factory.Sequence(lambda n: f"plan-{n}")


class PppoeClientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "pppoe.Client"

    operator = factory.SubFactory(OperatorFactory)
    account_number = factory.Sequence(lambda n: f"TEST{n:05d}")
    full_name = factory.Faker("name")
    plan = factory.SubFactory(ServicePlanFactory, operator=factory.SelfAttribute("..operator"))
    router = factory.SubFactory(RouterFactory, operator=factory.SelfAttribute("..operator"))
    pppoe_username = factory.Sequence(lambda n: f"user{n}")
    pppoe_password = "secret123"
    status = "active"
    billing_day = 1


class VoucherFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Voucher

    operator = factory.SubFactory(OperatorFactory)
    plan = factory.SubFactory(PlanFactory)
    code = factory.Sequence(lambda n: f"TESTV{n:04d}")


def enrol_mfa(user) -> str:
    """Give a user a working authenticator and hand back the shared secret.

    Withdrawing needs a second factor now, so any test that moves money through the
    API has to hold one. Doing it through the real enrolment path (rather than poking
    a row into the DB) means these tests would notice if enrolment itself broke.
    """
    import pyotp

    from apps.accounts import mfa

    device = mfa.begin_enrolment(user)
    mfa.confirm_enrolment(user, pyotp.TOTP(device.secret).now())
    return device.secret


def mfa_code(secret: str) -> str:
    import pyotp

    return pyotp.TOTP(secret).now()
