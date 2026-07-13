"""Branding endpoints: the ISP edits their brand; the captive portal reads it.

Editing is tenant-scoped to the acting operator. Reading is public — the portal is shown
to anonymous WiFi customers, so it fetches branding the same way it fetches plans (by the
router in front of them, or the subdomain).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .branding import BrandingError, clean_hex_color, process_logo
from .models import Branding
from .permissions import CanManageMoney, RequireTenant, TenantIsOperational
from .public import PublicAPIView
from .schema import OBJECT_RESPONSE
from .services import audit
from .tenancy import acting_tenant


def _branding_for(operator) -> Branding:
    branding, _ = Branding.objects.get_or_create(operator=operator)
    return branding


def _as_dict(b: Branding) -> dict:
    return {
        "display_name": b.display_name,
        "name_for_customers": b.name_for_customers,
        "tagline": b.tagline,
        "logo": b.logo,
        "primary_color": b.primary_color,
        "accent_color": b.accent_color,
        "support_phone": b.support_phone,
        "support_email": b.support_email,
    }


class BrandingSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    tagline = serializers.CharField(max_length=120, required=False, allow_blank=True)
    primary_color = serializers.CharField(max_length=9, required=False, allow_blank=True)
    accent_color = serializers.CharField(max_length=9, required=False, allow_blank=True)
    support_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    support_email = serializers.EmailField(required=False, allow_blank=True)


class BrandingView(APIView):
    # Branding is part of the business identity — the OWNER shapes it (same bar as the
    # other operator-level settings). Read-only support can view, not change.
    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's branding")
    def get(self, request):
        return Response(_as_dict(_branding_for(acting_tenant(request))))

    @extend_schema(request=BrandingSerializer, responses=OBJECT_RESPONSE,
                   summary="Update this ISP's branding (name, tagline, colours, support)")
    def patch(self, request):
        s = BrandingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        branding = _branding_for(acting_tenant(request))

        try:
            if "primary_color" in data and data["primary_color"]:
                branding.primary_color = clean_hex_color(
                    data["primary_color"], field="Primary colour"
                )
            if "accent_color" in data and data["accent_color"]:
                branding.accent_color = clean_hex_color(
                    data["accent_color"], field="Accent colour"
                )
        except BrandingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        for field in ("display_name", "tagline", "support_phone", "support_email"):
            if field in data:
                setattr(branding, field, data[field])
        branding.save()
        audit(
            "branding_updated", operator=branding.operator,
            actor=request.user, target=branding.operator,
        )
        return Response(_as_dict(branding))


class BrandingLogoView(APIView):
    """The logo, uploaded as a file. Validated and re-encoded server-side (see
    branding.process_logo) before it is ever stored or served."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request={"multipart/form-data": {"type": "object",
                 "properties": {"logo": {"type": "string", "format": "binary"}}}},
        responses=OBJECT_RESPONSE, summary="Upload a logo (PNG/JPG, re-encoded on the server)")
    def post(self, request):
        upload = request.FILES.get("logo")
        if upload is None:
            return Response({"detail": "Attach a logo file."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data_uri = process_logo(upload.read())
        except BrandingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        branding = _branding_for(acting_tenant(request))
        branding.logo = data_uri
        branding.save(update_fields=["logo", "updated_at"])
        audit(
            "branding_logo_set", operator=branding.operator,
            actor=request.user, target=branding.operator,
        )
        return Response({"logo": data_uri})

    @extend_schema(responses=OBJECT_RESPONSE, summary="Remove the logo")
    def delete(self, request):
        branding = _branding_for(acting_tenant(request))
        branding.logo = ""
        branding.save(update_fields=["logo", "updated_at"])
        return Response({"logo": ""})


@extend_schema(responses=OBJECT_RESPONSE,
               summary="Public: the branding the captive portal should wear")
class PublicBrandingView(PublicAPIView):
    """Anonymous — the captive portal fetches this to theme itself. Tenant comes from the
    subdomain or ?router=, exactly like the public plan list."""

    def get(self, request):
        from apps.provisioning.models import Router

        operator = getattr(request, "tenant", None)
        if operator is None:
            router_id = request.query_params.get("router", "")
            if router_id.isdigit():
                router = Router.objects.filter(pk=int(router_id), is_active=True).first()
                operator = router.operator if router else None
        if operator is None:
            # No tenant context: hand back the neutral WIFI.OS defaults so the portal
            # still renders instead of erroring.
            return Response(
                {
                    "name_for_customers": "WIFI.OS",
                    "tagline": "",
                    "logo": "",
                    "primary_color": "#141414",
                    "accent_color": "#228B22",
                    "support_phone": "",
                    "support_email": "",
                }
            )
        b = _branding_for(operator)
        return Response(
            {
                "name_for_customers": b.name_for_customers,
                "tagline": b.tagline,
                "logo": b.logo,
                "primary_color": b.primary_color,
                "accent_color": b.accent_color,
                "support_phone": b.support_phone,
                "support_email": b.support_email,
            }
        )
