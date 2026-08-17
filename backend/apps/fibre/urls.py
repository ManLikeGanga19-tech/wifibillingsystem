from rest_framework.routers import SimpleRouter

from .views import FibrePointViewSet, FibreSpanViewSet

router = SimpleRouter()
router.register("points", FibrePointViewSet, basename="fibre-point")
router.register("spans", FibreSpanViewSet, basename="fibre-span")

urlpatterns = [*router.urls]
