from django.urls import path

from .views import BusinessLocationView, GeoSearchView, MapDataView

urlpatterns = [
    path("map/points/", MapDataView.as_view(), name="map-points"),
    path("map/business-location/", BusinessLocationView.as_view(), name="map-business-location"),
    path("map/search/", GeoSearchView.as_view(), name="map-search"),
]
