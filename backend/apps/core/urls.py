from django.urls import path

from .views import DashboardStatsView, NavCountsView

urlpatterns = [
    path("stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("nav/", NavCountsView.as_view(), name="nav-counts"),
]
