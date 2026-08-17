from django.urls import path

from .views import FleetNearestView, FleetPingView, FleetView

urlpatterns = [
    path("ping/", FleetPingView.as_view(), name="fleet-ping"),
    path("nearest/", FleetNearestView.as_view(), name="fleet-nearest"),
    path("", FleetView.as_view(), name="fleet"),
]
