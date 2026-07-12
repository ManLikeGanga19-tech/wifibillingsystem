"""The 5-step signup API.

Every endpoint here is ANONYMOUS (PublicAPIView => authentication_classes = []).
The draft is identified by an httpOnly cookie the server sets — never by anything
the client stores. `GET /signup/state/` is what makes a refresh resume: the SERVER
says which step you are on.
"""

from django.conf import settings
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.public import PublicAPIView
from apps.core.schema import OBJECT_RESPONSE

from .models import TOS_VERSION, SignupApplication
from .services import (
    RateLimited,
    SignupError,
    complete_signup,
    find_console,
    name_available,
    resend_code,
    set_company,
    set_details,
    slug_available,
    start_signup,
    suggest_slug,
    verify_code,
)

SIGNUP_COOKIE = "wifios_signup"

#: Kenya's 47 counties — the only valid answers for step 4.
COUNTIES = [
    "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu", "Garissa",
    "Homa Bay", "Isiolo", "Kajiado", "Kakamega", "Kericho", "Kiambu", "Kilifi",
    "Kirinyaga", "Kisii", "Kisumu", "Kitui", "Kwale", "Laikipia", "Lamu", "Machakos",
    "Makueni", "Mandera", "Marsabit", "Meru", "Migori", "Mombasa", "Murang'a",
    "Nairobi", "Nakuru", "Nandi", "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu",
    "Siaya", "Taita-Taveta", "Tana River", "Tharaka-Nithi", "Trans Nzoia", "Turkana",
    "Uasin Gishu", "Vihiga", "Wajir", "West Pokot",
]

REFERRAL_SOURCES = [
    "Google search", "Social media", "A friend or colleague", "An existing WIFI.OS ISP",
    "An event or conference", "Other",
]


def _ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


def _set_cookie(response, draft: SignupApplication):
    """httpOnly: the draft id is a bearer capability for an in-flight signup, so JS
    must not be able to read it — and there is nothing for the client to store."""
    response.set_cookie(
        SIGNUP_COOKIE,
        str(draft.id),
        max_age=48 * 3600,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
        path="/",
    )
    return response


def _get_draft(request) -> SignupApplication | None:
    raw = request.COOKIES.get(SIGNUP_COOKIE)
    if not raw:
        return None
    draft = SignupApplication.objects.filter(pk=raw).first()
    if draft is None or draft.is_expired:
        return None
    return draft


class _Base(PublicAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    def draft_or_400(self, request):
        draft = _get_draft(request)
        if draft is None:
            raise SignupError("Your signup session has expired. Please start again.")
        return draft

    def handle_exception(self, exc):
        if isinstance(exc, RateLimited):
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if isinstance(exc, SignupError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)


# ---- serializers -------------------------------------------------------------


class StartSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=120)
    email = serializers.EmailField()


class VerifySerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)


class CompanySerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=40)


class DetailsSerializer(serializers.Serializer):
    county = serializers.ChoiceField(choices=[(c, c) for c in COUNTIES])
    phone = serializers.CharField(max_length=20)
    referral_source = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate_phone(self, value):
        try:
            return normalize_msisdn(value)
        except InvalidPhoneError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class FindConsoleSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CompleteSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    accept_tos = serializers.BooleanField()

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        if not attrs["accept_tos"]:
            raise serializers.ValidationError(
                {"accept_tos": "You must accept the Terms of Service."}
            )
        return attrs


# ---- endpoints ---------------------------------------------------------------


@extend_schema(request=StartSerializer, responses=OBJECT_RESPONSE,
               summary="Step 1: name + email, sends a verification code")
class StartView(_Base):
    def post(self, request):
        s = StartSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        draft = start_signup(
            full_name=s.validated_data["full_name"],
            email=s.validated_data["email"],
            ip=_ip(request),
        )
        # DELIBERATELY identical whether or not the email already has an account.
        # Confirming "that email is taken" is an account-enumeration oracle.
        resp = Response(
            {
                "detail": "If that address is valid, we've sent a 6-digit code to it.",
                "step": draft.current_step,
                "email": draft.email,
            },
            status=status.HTTP_201_CREATED,
        )
        return _set_cookie(resp, draft)


@extend_schema(request=VerifySerializer, responses=OBJECT_RESPONSE,
               summary="Step 2: verify the emailed code")
class VerifyView(_Base):
    def post(self, request):
        draft = self.draft_or_400(request)
        s = VerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        verify_code(draft, s.validated_data["code"])
        return Response({"detail": "Email verified.", "step": draft.current_step})


@extend_schema(request=None, responses=OBJECT_RESPONSE, summary="Step 2: resend the code")
class ResendView(_Base):
    def post(self, request):
        draft = self.draft_or_400(request)
        resend_code(draft)
        return Response({"detail": "A new code is on its way."})


@extend_schema(responses=OBJECT_RESPONSE,
               summary="Which step am I on? (this is how a refresh resumes)")
class StateView(_Base):
    """The whole reason the wizard needs no browser storage: the SERVER remembers.

    Returns only what the applicant already told us — never the code, never a hash.
    """

    def get(self, request):
        draft = _get_draft(request)
        if draft is None:
            return Response({"step": 1, "known": {}, "counties": COUNTIES,
                             "referral_sources": REFERRAL_SOURCES,
                             "tos_version": TOS_VERSION})
        return Response(
            {
                "step": draft.current_step,
                "known": {
                    "full_name": draft.full_name,
                    "email": draft.email,
                    "email_verified": bool(draft.email_verified_at),
                    "company_name": draft.company_name,
                    "slug": draft.slug,
                    "county": draft.county,
                    "phone": draft.phone,
                    "referral_source": draft.referral_source,
                },
                "resend_available_in": draft.resend_available_in,
                "counties": COUNTIES,
                "referral_sources": REFERRAL_SOURCES,
                "tos_version": TOS_VERSION,
                "complete": draft.is_complete,
                "console_url": (
                    f"https://{draft.slug}.wifios.co.ke" if draft.is_complete else None
                ),
            }
        )


@extend_schema(responses=OBJECT_RESPONSE,
               summary="Step 3: is this company name / subdomain free?")
class AvailabilityView(_Base):
    """Live check as they type. ADVISORY ONLY — the DB unique constraint is what
    actually decides, at the moment of creation."""

    throttle_scope = "signup-check"

    def get(self, request):
        draft = _get_draft(request)
        name = (request.query_params.get("name") or "").strip()
        slug = (request.query_params.get("slug") or "").strip().lower()
        if not slug and name:
            slug = suggest_slug(name)

        body = {"slug": slug, "suggestion": None}
        if name:
            body["name_available"] = name_available(name, exclude_draft=draft)
        if slug:
            body["slug_available"] = slug_available(slug, exclude_draft=draft)
            body["domain"] = f"{slug}.wifios.co.ke"
            if not body["slug_available"]:
                # Offer something they can actually take, rather than a dead end.
                for i in range(2, 12):
                    candidate = slugify(f"{slug}-{i}")[:40]
                    if slug_available(candidate, exclude_draft=draft):
                        body["suggestion"] = candidate
                        break
        return Response(body)


@extend_schema(request=CompanySerializer, responses=OBJECT_RESPONSE,
               summary="Step 3: name your ISP and claim a subdomain")
class CompanyView(_Base):
    def post(self, request):
        draft = self.draft_or_400(request)
        s = CompanySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        set_company(
            draft,
            company_name=s.validated_data["company_name"],
            slug=s.validated_data["slug"],
        )
        return Response({"detail": "Saved.", "step": draft.current_step,
                         "domain": f"{draft.slug}.wifios.co.ke"})


@extend_schema(request=DetailsSerializer, responses=OBJECT_RESPONSE,
               summary="Step 4: where you operate")
class DetailsView(_Base):
    def post(self, request):
        draft = self.draft_or_400(request)
        s = DetailsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        set_details(
            draft,
            county=s.validated_data["county"],
            phone=s.validated_data["phone"],
            referral_source=s.validated_data.get("referral_source", ""),
        )
        return Response({"detail": "Saved.", "step": draft.current_step})


@extend_schema(request=CompleteSerializer, responses=OBJECT_RESPONSE,
               summary="Step 5: set a password and create the ISP")
class CompleteView(_Base):
    def post(self, request):
        draft = self.draft_or_400(request)
        s = CompleteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = complete_signup(
            draft, password=s.validated_data["password"], ip=_ip(request)
        )
        resp = Response(
            {
                "detail": "Your ISP is ready.",
                "step": SignupApplication.Step.DONE,
                "slug": operator.slug,
                "console_url": f"https://{operator.slug}.wifios.co.ke",
                "next": (
                    "Add your settlement account to switch payments on. Until then you "
                    "can configure everything else — your first month is free."
                ),
            },
            status=status.HTTP_201_CREATED,
        )
        # The draft is spent. Drop the cookie so a refresh doesn't re-enter the wizard.
        resp.delete_cookie(SIGNUP_COOKIE, path="/")
        return resp


@extend_schema(request=FindConsoleSerializer, responses=OBJECT_RESPONSE,
               summary="Email me the address of my console")
class FindConsoleView(_Base):
    """Every ISP signs in at their own subdomain, so there is no shared front door to
    put a "Sign in" button on. This is the door instead: tell us your email, and the
    link goes to your inbox.

    The response NEVER changes. Registered or not, the caller is told the same thing —
    a lookup that answers "yes, that ISP banks with us" is an enumeration oracle
    wearing a helpful face.
    """

    throttle_scope = "signup-check"

    def post(self, request):
        s = FindConsoleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        find_console(email=s.validated_data["email"], ip=_ip(request))
        return Response(
            {
                "detail": (
                    "If that address has an account, we've emailed you the link to "
                    "your console."
                )
            }
        )
