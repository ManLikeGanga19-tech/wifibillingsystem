from django.urls import path

from .views import MapDataView

urlpatterns = [
    path("map/points/", MapDataView.as_view(), name="map-points"),
]
