"""Branding: how an ISP makes WIFI.OS look like their own business.

The parts that carry real weight: the logo is customer-supplied bytes we then serve to
other people, so it must be validated and re-encoded (not stored raw), and colours land
in CSS on the portal, so they must be exactly colours. And — as always — one ISP's
branding is theirs alone.
"""

import base64
import io

import pytest
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.branding import BrandingError, clean_hex_color, process_logo
from apps.core.models import Branding

from .factories import OperatorFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db

TENANT = "/api/v1/operator/branding/"
LOGO = "/api/v1/operator/branding/logo/"
PUBLIC = "/api/v1/branding/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def a_png(size=(64, 64), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class TestLogoSafety:
    def test_a_real_image_is_accepted_and_re_encoded_to_a_png_data_uri(self):
        uri = process_logo(a_png())
        assert uri.startswith("data:image/png;base64,")
        # It decodes back to a valid PNG (proof it was really re-encoded, not passed through).
        raw = base64.b64decode(uri.split(",", 1)[1])
        assert Image.open(io.BytesIO(raw)).format == "PNG"

    def test_a_big_image_is_shrunk(self):
        uri = process_logo(a_png(size=(2000, 2000)))
        raw = base64.b64decode(uri.split(",", 1)[1])
        w, h = Image.open(io.BytesIO(raw)).size
        assert max(w, h) <= 512

    def test_a_non_image_is_refused(self):
        with pytest.raises(BrandingError):
            process_logo(b"<svg onload=alert(1)>not really an image</svg>")

    def test_empty_is_refused(self):
        with pytest.raises(BrandingError):
            process_logo(b"")


class TestColourValidation:
    def test_shorthand_and_case_are_normalised(self):
        assert clean_hex_color("#FFF", field="x") == "#ffffff"
        assert clean_hex_color("228B22", field="x") == "#228b22"

    def test_junk_is_refused(self):
        for bad in ("red", "#12", "#gggggg", "rgb(0,0,0)", "#141414;background:url()"):
            with pytest.raises(BrandingError):
                clean_hex_color(bad, field="x")


class TestTheIspEditsTheirBrand:
    def test_defaults_exist_before_they_touch_anything(self):
        op = OperatorFactory(name="Acme Networks")
        body = owner(op).get(TENANT).json()
        assert body["name_for_customers"] == "Acme Networks"  # falls back to the operator name
        assert body["primary_color"] == "#141414"

    def test_update_name_tagline_and_colours(self):
        op = OperatorFactory()
        resp = owner(op).patch(
            TENANT,
            {"display_name": "Acme WiFi", "tagline": "Fast internet, fair prices",
             "accent_color": "#0af"},
            format="json",
        )
        assert resp.status_code == 200
        b = Branding.objects.get(operator=op)
        assert b.display_name == "Acme WiFi"
        assert b.accent_color == "#00aaff"  # shorthand normalised

    def test_a_bad_colour_is_rejected_cleanly(self):
        op = OperatorFactory()
        resp = owner(op).patch(TENANT, {"primary_color": "notacolour"}, format="json")
        assert resp.status_code == 400

    def test_logo_upload_stores_a_data_uri(self):
        op = OperatorFactory()
        from django.core.files.uploadedfile import SimpleUploadedFile

        resp = owner(op).post(
            LOGO, {"logo": SimpleUploadedFile("l.png", a_png(), content_type="image/png")}
        )
        assert resp.status_code == 200
        assert resp.json()["logo"].startswith("data:image/png;base64,")
        assert Branding.objects.get(operator=op).logo

    def test_read_only_support_cannot_edit(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.PLATFORM_SUPPORT)
        )
        assert c.patch(TENANT, {"display_name": "Hijack"}, format="json").status_code == 403


class TestTheCaptivePortalReadsIt:
    def test_public_branding_by_router(self):
        op = OperatorFactory(name="Acme Networks")
        Branding.objects.create(operator=op, display_name="Acme WiFi", accent_color="#00aaff")
        router = RouterFactory(operator=op)

        body = APIClient().get(f"{PUBLIC}?router={router.id}").json()
        assert body["name_for_customers"] == "Acme WiFi"
        assert body["accent_color"] == "#00aaff"

    def test_no_context_returns_neutral_defaults_not_an_error(self):
        resp = APIClient().get(PUBLIC)
        assert resp.status_code == 200
        assert resp.json()["name_for_customers"] == "WIFI.OS"

    def test_one_isp_never_sees_anothers_brand(self):
        a = OperatorFactory(slug="isp-a", name="Alpha")
        b = OperatorFactory(slug="isp-b", name="Bravo")
        Branding.objects.create(operator=a, display_name="Alpha WiFi")
        Branding.objects.create(operator=b, display_name="Bravo WiFi")
        router_b = RouterFactory(operator=b)

        body = APIClient().get(f"{PUBLIC}?router={router_b.id}").json()
        assert body["name_for_customers"] == "Bravo WiFi"
