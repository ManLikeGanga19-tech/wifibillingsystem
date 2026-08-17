from django.conf import settings
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

    PLATFORM roles (Danamo Tech) act across tenants. The TENANT side has an OWNER plus a
    designed set of delegated workforce roles.

    HISTORY (read before adding a role): we once shipped generic tenant_manager and
    tenant_support and retired them — a sub-role that cannot touch money, routers or plans
    could barely do anything, while every screen, test and permission check carried the
    branching anyway. The delegated roles below (admin / care / technician) are the "real
    demand, designed feature" that retirement asked for: each maps to a concrete job, and
    their reach lives in ONE capability map (accounts/rbac.py), not in scattered if-branches.
    Admin differs from those dead roles because it CAN touch routers, plans and network — it is
    a full operator minus moving money, which is a genuine, useful distinction.
    """

    # Platform (Danamo Tech)
    PLATFORM_OWNER = "platform_owner", "Platform owner"
    PLATFORM_SUPPORT = "platform_support", "Platform support (read-only)"
    # Tenant (an ISP): the owner, plus delegated workforce roles (see rbac.py for their reach).
    # See rbac.py for each role's reach:
    TENANT_OWNER = "tenant_owner", "ISP owner"                  # everything, incl. money
    TENANT_ADMIN = "tenant_admin", "ISP administrator"          # full console except moving money
    TENANT_CARE = "tenant_care", "Customer care"                # front desk: clients/tickets
    TENANT_TECHNICIAN = "tenant_technician", "Technician"  # field ops: map/plant/tickets

    @classmethod
    def platform_roles(cls):
        return {cls.PLATFORM_OWNER, cls.PLATFORM_SUPPORT}

    @classmethod
    def tenant_roles(cls):
        return {cls.TENANT_OWNER, cls.TENANT_ADMIN, cls.TENANT_CARE, cls.TENANT_TECHNICIAN}

    @classmethod
    def staff_manageable_roles(cls):
        """Roles an Owner/Admin may assign when creating an employee — never a platform hat,
        and (deliberately) never Owner: ownership transfer is its own audited action, not a
        dropdown in the staff screen."""
        return {cls.TENANT_ADMIN, cls.TENANT_CARE, cls.TENANT_TECHNICIAN}

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

    #: When platform support last cleared this user's authenticator (lost phone, lost
    #: recovery codes). Withdrawals are frozen for a cooling-off period afterwards —
    #: see mfa.PAYOUT_FREEZE_HOURS. A reset is the one moment the second factor is
    #: down, so it is exactly when a fraudulent reset would be cashed in; the freeze
    #: buys the real owner time to see the email and shout.
    mfa_reset_at = models.DateTimeField(null=True, blank=True)

    #: Monotonic session epoch. It is stamped into every issued JWT (the `sver` claim) and
    #: checked on every request — a token whose `sver` is behind the user's current value is
    #: rejected (401), forcing a fresh login. Bumping it (see `revoke_sessions`) instantly voids
    #: every token that user holds: this is how a role downgrade or an offboarding takes effect
    #: NOW instead of whenever a short-lived token happened to expire.
    session_version = models.PositiveIntegerField(default=0)

    #: Set when an Owner/Admin creates or resets an employee: the temp password is single-use and
    #: the console forces a change before the employee can work. Cleared by ChangePasswordView.
    must_change_password = models.BooleanField(default=False)

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
        """Withdrawals and payout decisions: owners only. Admin is deliberately excluded —
        adding delegated roles never widens who can move money."""
        return self.role in (Role.PLATFORM_OWNER, Role.TENANT_OWNER)

    def has_capability(self, capability: str) -> bool:
        """Does this user's role grant `capability` (see accounts/rbac.py)? The one check
        every RequireCapability gate and every UI guard resolves through."""
        from .rbac import has_capability

        return has_capability(self, capability)

    @property
    def capabilities(self) -> list[str]:
        """The resolved capability set, sorted — shipped to the console via /me/ so the UI hides
        what the API would refuse anyway."""
        from .rbac import capabilities_for

        return sorted(capabilities_for(self))

    def revoke_sessions(self):
        """Invalidate every JWT this user currently holds — NOW. Call on role change, offboarding,
        password reset, or a forced 2FA change. Bumps session_version atomically (F-expression, so
        concurrent requests can't lose a bump) and refreshes the in-memory copy."""
        from django.db.models import F

        type(self).objects.filter(pk=self.pk).update(session_version=F("session_version") + 1)
        self.refresh_from_db(fields=["session_version"])


class OperatorRoleConfig(models.Model):
    """An Owner's per-tenant override of what a delegated role (admin/care/technician) may do,
    set on the Access Control page. Absent = use the recommended defaults (rbac.ROLE_CAPABILITIES).
    Only ASSIGNABLE_CAPS are ever honoured — money.manage / rbac.manage stay with the Owner, which
    capabilities_for() enforces regardless of what's stored here."""

    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="role_configs")
    role = models.CharField(max_length=20, choices=Role.choices)
    #: The exact capability strings this role holds at this tenant (a list of rbac.* constants).
    capabilities = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operator", "role"], name="uniq_operator_role_config")
        ]

    def __str__(self):
        return f"{self.operator_id}:{self.role} ({len(self.capabilities)} caps)"


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


# The MFA models live in mfa.py (they belong with the logic that uses them), but
# Django only discovers models imported from models.py. The string reference to
# "accounts.User" inside them keeps this from being circular.
from .mfa import MfaDevice, RecoveryCode  # noqa: E402,F401
