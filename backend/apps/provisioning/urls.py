from django.urls import path
from rest_framework.routers import SimpleRouter

from .device_views import SessionDevicesView
from .views import RouterViewSet, SessionViewSet, router_enroll

router = SimpleRouter()
router.register("routers", RouterViewSet, basename="router")
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = [
    path("routers/enroll/", router_enroll, name="router-enroll"),
    # Portal: the paying device manages the session's other devices (tap-to-approve).
    path("portal/devices/", SessionDevicesView.as_view(), name="portal-devices"),
    *router.urls,
]
