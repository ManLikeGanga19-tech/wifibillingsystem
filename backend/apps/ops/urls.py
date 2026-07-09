from rest_framework.routers import SimpleRouter

from .views import EquipmentViewSet, ExpenseViewSet, LeadViewSet, TicketViewSet

router = SimpleRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("leads", LeadViewSet, basename="lead")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("equipment", EquipmentViewSet, basename="equipment")

urlpatterns = router.urls
