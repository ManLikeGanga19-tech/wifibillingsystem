from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Operator
from apps.payments.models import Transaction
from apps.plans.models import Plan
from apps.provisioning.models import Router, Session
from apps.vouchers.models import Voucher


class OperatorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Operator
        django_get_or_create = ("slug",)

    name = "Test WISP"
    slug = "test-wisp"
    status = Operator.Status.ACTIVE


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    operator = factory.SubFactory(OperatorFactory)
    phone = factory.Sequence(lambda n: f"2547{n:08d}")
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
    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    phone = factory.LazyAttribute(lambda o: o.user.phone)
    amount = factory.LazyAttribute(lambda o: o.plan.price)
    checkout_request_id = factory.Sequence(lambda n: f"ws_CO_test_{n:06d}")


class SessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Session

    operator = factory.SubFactory(OperatorFactory)
    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    router = factory.SubFactory(RouterFactory)
    transaction = factory.SubFactory(TransactionFactory)
    hotspot_username = factory.LazyAttribute(lambda o: o.user.phone)
    hotspot_password = "123456"
    starts_at = factory.LazyFunction(timezone.now)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
    status = Session.Status.ACTIVE


class VoucherFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Voucher

    operator = factory.SubFactory(OperatorFactory)
    plan = factory.SubFactory(PlanFactory)
    code = factory.Sequence(lambda n: f"TESTV{n:04d}")
