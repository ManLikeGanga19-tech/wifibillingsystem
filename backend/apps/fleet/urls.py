from django.urls import path

from .views import FleetPingView, FleetView

urlpatterns = [
    path("ping/", FleetPingView.as_view(), name="fleet-ping"),
    path("", FleetView.as_view(), name="fleet"),
]
