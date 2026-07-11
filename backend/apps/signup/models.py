"""The 5-step ISP signup, held on the SERVER.

A multi-step wizard has to remember steps 1-4 while you are on step 5. Every
instinct says localStorage — which this system forbids, and rightly: a
half-finished signup rotting in a browser across a deploy is exactly the stale
state that has already bitten us twice.

So the draft is a server resource, referenced by an httpOnly cookie. The client
stores nothing and simply asks "which step am I on, and what do you already know
about me?". That makes the wizard refresh-safe, back-button-safe and deploy-safe
by construction, and abandoned drafts expire instead of rotting.

This is also the FIRST anonymous write endpoint in the system — everything else is
behind auth — so the anti-abuse fields (attempts, resends, expiry) are not
decoration. See docs/ONBOARDING_ARCHITECTURE.md.
"""

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# The verification code the applicant types in from their email.
CODE_LENGTH = 6
CODE_TTL_MINUTES = 15
#: Burn the draft after this many wrong codes. 6 digits = 1,000,000 combinations,
#: so a handful of guesses is nowhere near enough — but a bot with unlimited tries
#: would get there.
MAX_CODE_ATTEMPTS = 5
#: Don't let anyone use us to bomb a victim's inbox.
RESEND_COOLDOWN_SECONDS = 60
MAX_RESENDS = 5
#: Abandoned drafts are swept, not kept.
DRAFT_TTL_HOURS = 48


def generate_code() -> str:
    """Cryptographically random. `random` is not acceptable for a credential."""
    return "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))


class SignupApplication(models.Model):
    """One in-flight ISP signup. Consumed when it becomes a real Operator."""

    class Step(models.IntegerChoices):
        VERIFY_EMAIL = 2, "Verify email"
        COMPANY = 3, "Name your ISP"
        DETAILS = 4, "Where you operate"
        PASSWORD = 5, "Secure your account"
        DONE = 6, "Complete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # -- step 1: who are you ------------------------------------------------
    full_name = models.CharField(max_length=120)
    email = models.EmailField(db_index=True)

    # -- step 2: prove you own that inbox -----------------------------------
    # The code is HASHED. A leaked database must not hand an attacker live codes.
    code_hash = models.CharField(max_length=128, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    resends = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    # -- step 3: name your ISP ----------------------------------------------
    company_name = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=40, blank=True)

    # -- step 4: where you operate ------------------------------------------
    # Billing currency is implicit KSh (Kenya-only), so it is not a field.
    county = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    referral_source = models.CharField(max_length=40, blank=True)

    # -- step 5: terms ------------------------------------------------------
    # Record the VERSION, or the acceptance is legally worthless.
    tos_version = models.CharField(max_length=20, blank=True)
    tos_accepted_at = models.DateTimeField(null=True, blank=True)

    # -- lifecycle ----------------------------------------------------------
    operator = models.OneToOneField(
        "core.Operator",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="signup_application",
        help_text="Set when the draft becomes a real ISP",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "-created_at"])]

    def __str__(self):
        return f"{self.email} ({self.company_name or 'unnamed'}) step {self.current_step}"

    # -- state --------------------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=DRAFT_TTL_HOURS)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_complete(self) -> bool:
        return self.operator_id is not None

    @property
    def current_step(self) -> int:
        """Where the wizard should put them. THE SERVER decides this — a refresh
        resumes exactly here, because the client holds no opinion of its own."""
        if self.is_complete:
            return self.Step.DONE
        if not self.email_verified_at:
            return self.Step.VERIFY_EMAIL
        if not self.slug:
            return self.Step.COMPANY
        if not self.county or not self.phone:
            return self.Step.DETAILS
        return self.Step.PASSWORD

    # -- verification code --------------------------------------------------

    def set_code(self) -> str:
        """Mint a fresh code, store only its hash, and return the plaintext ONCE
        (to be emailed and then forgotten)."""
        from django.contrib.auth.hashers import make_password

        code = generate_code()
        self.code_hash = make_password(code)
        self.code_expires_at = timezone.now() + timedelta(minutes=CODE_TTL_MINUTES)
        self.attempts = 0
        self.last_sent_at = timezone.now()
        return code

    def check_code(self, code: str) -> bool:
        from django.contrib.auth.hashers import check_password

        if not self.code_hash or not self.code_expires_at:
            return False
        if timezone.now() >= self.code_expires_at:
            return False
        return check_password(code.strip(), self.code_hash)

    @property
    def code_attempts_exhausted(self) -> bool:
        return self.attempts >= MAX_CODE_ATTEMPTS

    @property
    def resend_available_in(self) -> int:
        """Seconds until they may ask for another code. Stops us being used as an
        email cannon pointed at someone else's inbox."""
        if not self.last_sent_at:
            return 0
        elapsed = (timezone.now() - self.last_sent_at).total_seconds()
        return max(0, int(RESEND_COOLDOWN_SECONDS - elapsed))


class SignupThrottle(models.Model):
    """Per-email + per-IP send counters.

    `/signup/start/` is unauthenticated and sends an email to an address the caller
    chooses — a gift to anyone who wants to bomb a competitor's inbox. DRF's
    throttles are per-endpoint; these counters are per-TARGET, which is what
    actually matters here.
    """

    key = models.CharField(max_length=190, primary_key=True)  # "email:x" | "ip:x"
    count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)

    WINDOW = timedelta(hours=1)
    MAX_PER_EMAIL = 3
    MAX_PER_IP = 10

    def __str__(self):
        return f"{self.key}={self.count}"

    @classmethod
    def hit(cls, key: str, limit: int) -> bool:
        """Count one send. Returns False when the caller is over the limit."""
        now = timezone.now()
        row, _ = cls.objects.get_or_create(key=key)
        if now - row.window_started_at > cls.WINDOW:
            row.count = 0
            row.window_started_at = now
        row.count += 1
        row.save(update_fields=["count", "window_started_at"])
        return row.count <= limit


#: Where the ToS lives. Bumping this invalidates nothing retroactively — old
#: acceptances stay pinned to the version they actually agreed to.
TOS_VERSION = getattr(settings, "TOS_VERSION", "2026-07-01")
