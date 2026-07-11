"""Signup business logic — and the defences that make an anonymous write endpoint safe.

This is the only unauthenticated *write* surface in the system. Everything else
sits behind a login. Three rules drive the design:

1. **Never confirm whether an email is registered.** "Send me a code" must look
   identical for a stranger and for an existing customer. If it already has an
   account we email "you already have an account — sign in" INSTEAD of a code. An
   attacker learns nothing either way.
2. **Never let us be used as a weapon.** Sending an email to an address the caller
   chooses is an inbox cannon unless it is rate-limited per TARGET, not just per
   endpoint.
3. **The database is the referee, not the draft.** A slug reserved on a draft is a
   soft hold; the unique constraint decides. Two people typing "acme" at once must
   not both get it.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Role, User
from apps.core.models import Operator
from apps.core.services import audit

from .models import (
    MAX_CODE_ATTEMPTS,
    MAX_RESENDS,
    TOS_VERSION,
    SignupApplication,
    SignupThrottle,
)

logger = logging.getLogger(__name__)


class SignupError(Exception):
    """Something the applicant can fix; safe to show them."""


class RateLimited(SignupError):
    pass


# ---- step 1: start -----------------------------------------------------------


def start_signup(*, full_name: str, email: str, ip: str | None) -> SignupApplication:
    """Create (or reuse) a draft and send a verification code.

    ALWAYS succeeds from the caller's point of view — see rule 1. If the email
    already has an account we send a "you already have an account" mail instead of
    a code, and still return a draft so the response is indistinguishable.
    """
    email = email.strip().lower()

    if not SignupThrottle.hit(f"email:{email}", SignupThrottle.MAX_PER_EMAIL):
        raise RateLimited("Too many codes requested for this address. Try again later.")
    if ip and not SignupThrottle.hit(f"ip:{ip}", SignupThrottle.MAX_PER_IP):
        raise RateLimited("Too many signups from this network. Try again later.")

    # Reuse an unfinished draft for the same address rather than littering.
    draft = (
        SignupApplication.objects.filter(
            email=email, operator__isnull=True, expires_at__gt=timezone.now()
        )
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        draft = SignupApplication(email=email, ip_address=ip)
    draft.full_name = full_name.strip()

    if _email_taken(email):
        # Do NOT mint a code, and do NOT say so. Nudge them to sign in instead.
        draft.save()
        _send_already_registered(email)
        logger.info("Signup start for existing email %s — sent sign-in nudge", email)
        return draft

    code = draft.set_code()
    draft.save()
    _send_code(email, draft.full_name, code)
    return draft


def resend_code(draft: SignupApplication) -> None:
    if draft.email_verified_at:
        raise SignupError("This email is already verified.")
    wait = draft.resend_available_in
    if wait:
        raise RateLimited(f"Please wait {wait} seconds before requesting another code.")
    if draft.resends >= MAX_RESENDS:
        raise RateLimited("Too many codes sent. Start again later.")
    if not SignupThrottle.hit(f"email:{draft.email}", SignupThrottle.MAX_PER_EMAIL):
        raise RateLimited("Too many codes requested for this address. Try again later.")

    code = draft.set_code()
    draft.resends += 1
    draft.save()
    _send_code(draft.email, draft.full_name, code)


# ---- step 2: verify ----------------------------------------------------------


def verify_code(draft: SignupApplication, code: str) -> None:
    if draft.email_verified_at:
        return  # idempotent
    if draft.code_attempts_exhausted:
        raise SignupError("Too many incorrect codes. Request a new one.")

    if not draft.check_code(code):
        draft.attempts += 1
        draft.save(update_fields=["attempts", "updated_at"])
        left = max(0, MAX_CODE_ATTEMPTS - draft.attempts)
        if left == 0:
            raise SignupError("Too many incorrect codes. Request a new one.")
        raise SignupError(f"That code is not right. {left} attempt(s) left.")

    draft.email_verified_at = timezone.now()
    # Burn the code: it has done its job and must not be replayable.
    draft.code_hash = ""
    draft.code_expires_at = None
    draft.save(update_fields=["email_verified_at", "code_hash", "code_expires_at", "updated_at"])


# ---- step 3: company + slug --------------------------------------------------


def suggest_slug(company_name: str) -> str:
    return slugify(company_name)[:40]


def slug_available(slug: str, *, exclude_draft=None) -> bool:
    slug = (slug or "").strip().lower()
    if not slug or slug in Operator.RESERVED_SLUGS:
        return False
    if Operator.objects.filter(slug=slug).exists():
        return False
    # Someone else's live draft holding it (a soft reservation)
    held = SignupApplication.objects.filter(
        slug=slug, operator__isnull=True, expires_at__gt=timezone.now()
    )
    if exclude_draft is not None:
        held = held.exclude(pk=exclude_draft.pk)
    return not held.exists()


def name_available(name: str, *, exclude_draft=None) -> bool:
    """Daniel: 'no duplicate slugs OR company names'. Case-insensitive."""
    name = (name or "").strip()
    if not name:
        return False
    if Operator.objects.filter(name__iexact=name).exists():
        return False
    held = SignupApplication.objects.filter(
        company_name__iexact=name, operator__isnull=True, expires_at__gt=timezone.now()
    )
    if exclude_draft is not None:
        held = held.exclude(pk=exclude_draft.pk)
    return not held.exists()


def set_company(draft: SignupApplication, *, company_name: str, slug: str) -> None:
    _require_verified(draft)
    company_name = company_name.strip()
    slug = slug.strip().lower()

    if not name_available(company_name, exclude_draft=draft):
        raise SignupError("That company name is already taken.")
    if not slug_available(slug, exclude_draft=draft):
        raise SignupError("That subdomain is not available.")

    draft.company_name = company_name
    draft.slug = slug
    draft.save(update_fields=["company_name", "slug", "updated_at"])


# ---- step 4: details ---------------------------------------------------------


def set_details(
    draft: SignupApplication, *, county: str, phone: str, referral_source: str
) -> None:
    _require_verified(draft)
    if User.objects.filter(phone=phone).exists():
        # Same anti-enumeration instinct, but here we MUST block the duplicate —
        # phone is the login identity. Keep the wording neutral.
        raise SignupError(
            "We can't use that phone number. If it's yours, try signing in instead."
        )
    draft.county = county.strip()
    draft.phone = phone
    draft.referral_source = (referral_source or "").strip()[:40]
    draft.save(update_fields=["county", "phone", "referral_source", "updated_at"])


# ---- step 5: complete --------------------------------------------------------


@db_transaction.atomic
def complete_signup(draft: SignupApplication, *, password: str, ip: str | None) -> Operator:
    """Turn the draft into a real ISP.

    The ISP lands PENDING: they get their console immediately (explore, configure,
    add routers) but CANNOT take a shilling until their settlement account is
    verified. See docs/ONBOARDING_ARCHITECTURE.md — that gate is what protects us
    from onboarding an unvetted business onto our own paybill.
    """
    if draft.is_complete:
        return draft.operator  # idempotent: a double-submit must not make two ISPs
    _require_verified(draft)
    if not (draft.slug and draft.county and draft.phone):
        raise SignupError("Some details are missing. Go back and complete them.")

    try:
        operator = Operator.objects.create(
            name=draft.company_name,
            slug=draft.slug,
            status=Operator.Status.PENDING,
            owner_name=draft.full_name,
            contact_phone=draft.phone,
            contact_email=draft.email,
            county=draft.county,
            referral_source=draft.referral_source,
        )
        User.objects.create_user(
            phone=draft.phone,
            password=password,
            name=draft.full_name,
            email=draft.email,
            operator=operator,
            is_staff=True,
            role=Role.TENANT_OWNER,  # ISPs have exactly one role for now
        )
    except IntegrityError as exc:
        # The DB is the referee: someone took the slug/name/phone between step 3
        # and now. Bounce them back rather than half-creating an ISP.
        raise SignupError(
            "That name, subdomain or phone was just taken. Please go back and change it."
        ) from exc

    draft.operator = operator
    draft.tos_version = TOS_VERSION
    draft.tos_accepted_at = timezone.now()
    draft.ip_address = ip or draft.ip_address
    draft.save(
        update_fields=["operator", "tos_version", "tos_accepted_at", "ip_address", "updated_at"]
    )

    audit(
        "isp_signed_up",
        operator=operator,
        target=operator,
        ip=ip,
        slug=operator.slug,
        email=draft.email,
        tos_version=draft.tos_version,
        referral=draft.referral_source,
    )
    logger.info("New ISP signed up: %s (%s)", operator.name, operator.slug)
    _send_welcome(draft.email, draft.full_name, operator)
    return operator


# ---- helpers -----------------------------------------------------------------


def _require_verified(draft: SignupApplication) -> None:
    if not draft.email_verified_at:
        raise SignupError("Verify your email first.")


def _email_taken(email: str) -> bool:
    return User.objects.filter(email__iexact=email).exists()


def sweep_expired(now=None) -> int:
    """Abandoned drafts expire rather than rot. Run from a beat."""
    now = now or timezone.now()
    qs = SignupApplication.objects.filter(operator__isnull=True, expires_at__lt=now)
    count = qs.count()
    qs.delete()
    return count


# ---- email -------------------------------------------------------------------

FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wifios.co.ke")
CONSOLE_URL = getattr(settings, "PUBLIC_SITE_URL", "https://wifios.co.ke")


def _send(subject: str, body: str, to: str) -> None:
    """Never let a mail failure lose the applicant's progress — the draft is
    already saved. Log it and move on; they can resend."""
    try:
        send_mail(subject, body, FROM, [to], fail_silently=False)
    except Exception:
        logger.exception("Signup email failed to %s (%s)", to, subject)


def _send_code(email: str, name: str, code: str) -> None:
    _send(
        f"{code} is your WIFI.OS verification code",
        f"Hi {name or 'there'},\n\n"
        f"Your WIFI.OS verification code is:\n\n    {code}\n\n"
        "It expires in 15 minutes. If you didn't request this, you can ignore "
        "this email — nobody can use it without your inbox.\n\n"
        "— WIFI.OS",
        email,
    )


def _send_already_registered(email: str) -> None:
    """The anti-enumeration path: the caller gets the same response either way, but
    the real owner of the inbox gets told what's actually going on."""
    _send(
        "You already have a WIFI.OS account",
        "Hi,\n\n"
        "Someone (probably you) tried to create a WIFI.OS account with this email "
        "address — but you already have one.\n\n"
        f"Sign in instead: {CONSOLE_URL}/signin\n\n"
        "If this wasn't you, no action is needed. Your account is untouched.\n\n"
        "— WIFI.OS",
        email,
    )


def _send_welcome(email: str, name: str, operator: Operator) -> None:
    _send(
        f"Welcome to WIFI.OS, {operator.name}",
        f"Hi {name},\n\n"
        f"{operator.name} is set up. Your console is ready:\n\n"
        f"    https://{operator.slug}.wifios.co.ke\n\n"
        "One more thing before you can take payments: add your settlement account "
        "(the M-Pesa paybill or bank account we pay YOU into). Until then you can "
        "configure everything — routers, plans, branding — but payments stay off.\n\n"
        "Your first month is free.\n\n"
        "— WIFI.OS",
        email,
    )
