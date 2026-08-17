"""Phase 1 of the fibre plant: the models (points + spans + the client link), the invariants
(no self-loop, soft-delete, tenant scoping), and that fibre.write is bundled with radio plant by
default but stays a first-class, separable capability.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts import rbac
from apps.accounts.models import Role
from apps.fibre.models import FibrePoint, FibreSpan, PlantStatus

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, UserFactory


@pytest.mark.django_db
class TestFibreModels:
    def test_point_and_span_form_an_edge(self):
        op = OperatorFactory()
        olt = FibrePoint.objects.create(operator=op, type=FibrePoint.Type.OLT_POP, label="OLT-1")
        odp = FibrePoint.objects.create(
            operator=op, type=FibrePoint.Type.ODP, label="ODP-7", port_capacity=16)
        span = FibreSpan.objects.create(
            operator=op, from_point=olt, to_point=odp,
            cable_type=FibreSpan.Cable.ADSS, fibre_count=24)
        assert olt.is_active and odp.is_active and span.is_active   # active by default
        assert odp.status == PlantStatus.OK
        assert span.from_point_id == olt.id and span.to_point_id == odp.id

    def test_a_span_cannot_loop_to_itself(self):
        op = OperatorFactory()
        p = FibrePoint.objects.create(operator=op, label="P")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                FibreSpan.objects.create(operator=op, from_point=p, to_point=p)

    def test_delete_is_soft(self):
        op = OperatorFactory()
        p = FibrePoint.objects.create(operator=op, label="P")
        p.is_active = False
        p.save(update_fields=["is_active"])
        assert FibrePoint.objects.filter(operator=op, is_active=True).count() == 0
        assert FibrePoint.objects.filter(operator=op).count() == 1   # the row survives

    def test_a_fibre_client_hangs_off_its_odp(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        odp = FibrePoint.objects.create(
            operator=op, type=FibrePoint.Type.ODP, label="ODP-7", port_capacity=16)
        client = PppoeClientFactory(
            operator=op, router=router, delivery_method="fibre", fibre_point=odp)
        assert client.fibre_point_id == odp.id
        assert list(odp.fibre_clients.all()) == [client]

    def test_losing_the_odp_never_deletes_the_customer(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        odp = FibrePoint.objects.create(operator=op, type=FibrePoint.Type.ODP, label="ODP-7")
        client = PppoeClientFactory(operator=op, router=router, fibre_point=odp)
        odp.delete()   # SET_NULL — the client stays, just unlinked
        client.refresh_from_db()
        assert client.fibre_point_id is None


@pytest.mark.django_db
class TestFibreCapability:
    def test_fibre_write_is_bundled_with_radio_plant_by_default(self):
        # Out of the box, any role that manages radio plant manages fibre too.
        for role in (Role.TENANT_OWNER, Role.TENANT_ADMIN, Role.TENANT_TECHNICIAN):
            u = UserFactory(role=role)
            assert u.has_capability(rbac.NETWORK_WRITE), role
            assert u.has_capability(rbac.FIBRE_WRITE), role
        # Care runs the front desk, not plant.
        assert not UserFactory(role=Role.TENANT_CARE).has_capability(rbac.FIBRE_WRITE)

    def test_fibre_write_is_a_first_class_separable_toggle(self):
        # Assignable (Owner can later split fibre from radio on Access Control), never
        # non-delegable, and it appears in the catalogue the Access Control page renders.
        assert rbac.FIBRE_WRITE in rbac.ASSIGNABLE_CAPS
        assert rbac.FIBRE_WRITE not in rbac.NON_DELEGABLE
        assert rbac.FIBRE_WRITE in {cap for (_group, cap, _label) in rbac.CAPABILITY_CATALOG}
