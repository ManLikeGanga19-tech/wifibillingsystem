from rest_framework.routers import SimpleRouter

from .views import CampaignViewSet, MessageViewSet

router = SimpleRouter()
router.register("campaigns", CampaignViewSet, basename="campaign")
router.register("messages", MessageViewSet, basename="message")

urlpatterns = router.urls
