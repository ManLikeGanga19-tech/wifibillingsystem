from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import RouterViewSet, SessionViewSet, router_enroll

router = SimpleRouter()
router.register("routers", RouterViewSet, basename="router")
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = [
    path("routers/enroll/", router_enroll, name="router-enroll"),
    *router.urls,
]
