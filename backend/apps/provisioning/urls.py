from django.urls import path
from rest_framework.routers import SimpleRouter

from .device_views import RecoverDevicesView, SessionDevicesView
from .views import RouterViewSet, SessionViewSet, router_enroll

router = SimpleRouter()
router.register("routers", RouterViewSet, basename="router")
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = [
    path("routers/enroll/", router_enroll, name="router-enroll"),
    # Portal: the paying device manages the session's other devices (tap-to-approve).
    path("portal/devices/", SessionDevicesView.as_view(), name="portal-devices"),
    # Portal: SMS a 'manage devices' link to the phone that paid (closed-the-tab recovery).
    path("portal/devices/recover/", RecoverDevicesView.as_view(), name="portal-devices-recover"),
    *router.urls,
]
