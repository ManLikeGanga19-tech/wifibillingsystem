from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    EquipmentViewSet,
    ExpenseViewSet,
    LeadViewSet,
    PlatformFeesView,
    TicketViewSet,
)

router = SimpleRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("leads", LeadViewSet, basename="lead")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("equipment", EquipmentViewSet, basename="equipment")

urlpatterns = [
    path("platform-fees/", PlatformFeesView.as_view(), name="platform-fees"),
    *router.urls,
]
