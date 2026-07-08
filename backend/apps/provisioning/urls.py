from rest_framework.routers import SimpleRouter

from .views import RouterViewSet, SessionViewSet

router = SimpleRouter()
router.register("routers", RouterViewSet, basename="router")
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = router.urls
