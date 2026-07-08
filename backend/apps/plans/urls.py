from rest_framework.routers import SimpleRouter

from .views import PlanViewSet

router = SimpleRouter()
router.register("plans", PlanViewSet, basename="plan")

urlpatterns = router.urls
