from django.urls import path

from .views import (
    AvailabilityView,
    CompanyView,
    CompleteView,
    DetailsView,
    FindConsoleView,
    ResendView,
    StartView,
    StateView,
    VerifyView,
)

urlpatterns = [
    # The whole wizard is anonymous; the draft lives in an httpOnly cookie.
    path("state/", StateView.as_view(), name="signup-state"),
    path("start/", StartView.as_view(), name="signup-start"),
    path("verify/", VerifyView.as_view(), name="signup-verify"),
    path("resend/", ResendView.as_view(), name="signup-resend"),
    path("availability/", AvailabilityView.as_view(), name="signup-availability"),
    path("company/", CompanyView.as_view(), name="signup-company"),
    path("details/", DetailsView.as_view(), name="signup-details"),
    path("complete/", CompleteView.as_view(), name="signup-complete"),
    # Not part of the wizard: the way BACK IN for an ISP who forgot their subdomain.
    path("find-console/", FindConsoleView.as_view(), name="signup-find-console"),
]
