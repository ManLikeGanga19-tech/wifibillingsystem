from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import Operator
from apps.core.phone import normalize_msisdn


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra):
        if not phone:
            raise ValueError("Phone number is required")
        user = self.model(phone=normalize_msisdn(phone), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(phone, password, **extra)


class Role(models.TextChoices):
    """Who you are decides what you may do.

    PLATFORM roles (Danamo Tech) act across tenants. The TENANT side has exactly ONE
    role: the ISP owner.

    We shipped tenant_manager and tenant_support and then retired them. They were a
    guess at what ISPs would want, and they bought us nothing: a sub-role that cannot
    touch money, routers or plans can barely do anything, while every screen, test and
    permission check had to carry the branching anyway. An ISP that wants a second pair
    of hands gives them an owner login; if a real demand for delegated access shows up,
    it comes back as a designed feature (scoped invites, audited), not as three enum
    values nobody asked for.
    """

    # Platform (Danamo Tech)
    PLATFORM_OWNER = "platform_owner", "Platform owner"
    PLATFORM_SUPPORT = "platform_support", "Platform support (read-only)"
    # Tenant (an ISP) — one role, on purpose.
    TENANT_OWNER = "tenant_owner", "ISP owner"

    @classmethod
    def platform_roles(cls):
        return {cls.PLATFORM_OWNER, cls.PLATFORM_SUPPORT}

    @classmethod
    def read_only_roles(cls):
        return {cls.PLATFORM_SUPPORT}


class User(AbstractBaseUser, PermissionsMixin):
    """LOGIN ACCOUNTS ONLY: platform staff and ISP staff. Phone is globally
    unique because it is the login username. Customers are NOT users — they are
    `Subscriber` rows (see below), so the same phone can be a customer of several
    ISPs and still register its own ISP account without colliding here.

    A platform user MAY also own a tenant (Daniel is the platform owner AND runs
    his own WISP): `role` decides platform powers, `operator` is their home ISP.
    """

    operator = models.ForeignKey(
        Operator,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="users",
        help_text="The ISP this user belongs to (their 'home' tenant).",
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.TENANT_OWNER, db_index=True
    )
    phone = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    #: A SECOND login identifier, not just a contact field — you may sign in with
    #: either. Hence unique (case-insensitively, below): two accounts sharing an
    #: address would make "sign in with your email" ambiguous, and the payout-change
    #: code is emailed here, so it must point at exactly one account.
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            # Case-insensitive: Ann@acme.co.ke and ann@acme.co.ke are one person, and
            # a login must never depend on which capitalisation they typed. Blank is
            # exempt — platform/system accounts sign in by phone and have no email.
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="user_email_unique_ci",
            )
        ]

    def save(self, *args, **kwargs):
        # Normalise at the door. The constraint would catch duplicates anyway, but
        # storing one canonical form keeps lookups, emails and audit trails honest.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or self.phone

    # -- capability helpers: the single source of truth for permissions --------
    @property
    def is_platform_staff(self) -> bool:
        """Platform hat. NOTE: deliberately NOT 'has no operator' — the platform
        owner also runs his own ISP."""
        return self.role in Role.platform_roles()

    @property
    def is_read_only(self) -> bool:
        return self.role in Role.read_only_roles()

    @property
    def can_manage_money(self) -> bool:
        """Withdrawals and payout decisions: owners only."""
        return self.role in (Role.PLATFORM_OWNER, Role.TENANT_OWNER)


class Subscriber(models.Model):
    """A CUSTOMER of one ISP: a phone number that buys WiFi. Not a login account.
    Unique per (operator, phone) — the same human/phone is a distinct subscriber
    at each ISP they use, and may separately hold a staff `User` login."""

    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="subscribers"
    )
    phone = models.CharField(max_length=12, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operator", "phone"], name="subscriber_unique_operator_phone"
            )
        ]
        indexes = [models.Index(fields=["operator", "phone"])]

    def __str__(self):
        return f"{self.name or self.phone} @ {self.operator.slug}"

    @classmethod
    def get_or_create_for(cls, operator, phone, **defaults):
        return cls.objects.get_or_create(
            operator=operator, phone=normalize_msisdn(phone), defaults=defaults
        )
