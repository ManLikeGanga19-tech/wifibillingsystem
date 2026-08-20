from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FibrePointViewSet, FibreRouteView, FibreSpanViewSet

router = SimpleRouter()
router.register("points", FibrePointViewSet, basename="fibre-point")
router.register("spans", FibreSpanViewSet, basename="fibre-span")

urlpatterns = [
    path("route/", FibreRouteView.as_view(), name="fibre-route"),
    *router.urls,
]
