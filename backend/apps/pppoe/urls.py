from rest_framework.routers import SimpleRouter

from .views import (
    AccessPointViewSet,
    ClientViewSet,
    InvoiceViewSet,
    ServicePlanViewSet,
    TowerViewSet,
)

router = SimpleRouter()
router.register("plans", ServicePlanViewSet, basename="pppoe-plan")
router.register("clients", ClientViewSet, basename="pppoe-client")
router.register("invoices", InvoiceViewSet, basename="pppoe-invoice")
router.register("towers", TowerViewSet, basename="pppoe-tower")
router.register("access-points", AccessPointViewSet, basename="pppoe-ap")

urlpatterns = router.urls
