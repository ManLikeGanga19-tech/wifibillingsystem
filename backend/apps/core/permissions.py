"""RBAC. Every ISP-facing view composes: IsStaff + TenantIsOperational +
RequireTenant (+ role gate). Read-only roles cannot write anything, anywhere."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .tenancy import acting_tenant, is_impersonating


class IsPlatformStaff(BasePermission):
    """Danamo Tech staff (platform_owner / platform_support)."""

    message = "Platform access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_staff)


class IsPlatformOwner(BasePermission):
    """Platform money decisions (paying out ISPs, changing tenant rates)."""

    message = "Platform owner access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_platform_staff
            and user.can_manage_money
        )


class RequireTenant(BasePermission):
    """FAIL CLOSED: ISP data is never served without exactly one resolved tenant.

    This is the guard that makes the old cross-tenant leak impossible: a platform
    admin with no tenant selected gets 403 here instead of an unfiltered queryset.
    """

    message = (
        "No ISP selected. Platform staff must choose a tenant "
        "(X-Act-As-Tenant header) to view ISP data."
    )
    #: Shown when a read-only demo tenant attempts a write. The console renders this as a
    #: gentle notice, not an error.
    DEMO_MESSAGE = "This is a read-only demo of WIFI.OS — changes are disabled here."

    def has_permission(self, request, view):
        tenant = acting_tenant(request)
        if tenant is None:
            return False
        # The demo tenant is a fully-seeded showcase: everyone may LOOK, nobody may write.
        # This is the single chokepoint every ISP write already passes through, so one guard
        # here covers CRUD, money actions, imports — everything — without per-view changes.
        if getattr(tenant, "is_demo", False) and request.method not in SAFE_METHODS:
            self.message = self.DEMO_MESSAGE
            return False
        return True


class TenantIsOperational(BasePermission):
    """May this tenant's staff open the console at all?

    A PENDING tenant CAN — they signed up, they get to build. Only a SUSPENDED
    tenant is locked out. Money is a separate gate (TenantCanTransact).
    """

    message = "This ISP account has been suspended. Contact the platform administrator."

    def has_permission(self, request, view):
        user = request.user
        if user and user.is_authenticated and user.is_platform_staff:
            return True  # platform support must still reach suspended tenants
        operator = acting_tenant(request)
        if operator is None:
            return True  # RequireTenant reports this case
        return operator.is_operational


class TenantCanTransact(BasePermission):
    """THE MONEY GATE. Nothing that moves money may happen for an unverified ISP.

    Covers: collecting a payment, redeeming a voucher, provisioning a paying
    customer, and withdrawing. An ISP can configure everything else meanwhile.

    Why this is not optional: WE own the paybill. A business we have not verified
    collecting real customer money through Danamo's shortcode is OUR anti-money-
    laundering exposure. The ISP's convenience does not outrank that.
    """

    message = (
        "Payments are not switched on for this ISP yet. Add your settlement "
        "account (the paybill or bank account we pay you into) to go live."
    )

    def has_permission(self, request, view):
        operator = acting_tenant(request)
        if operator is None:
            return True  # RequireTenant reports this case
        return operator.can_transact


class ReadOnlyForSupport(BasePermission):
    """Support roles may look, never touch."""

    message = "Your role is read-only."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return not user.is_read_only


class NotBillingLocked(BasePermission):
    """PAST-DUE LOCKOUT: read-only + pay.

    When an ISP owes us past their lock threshold (billing.enforcement.is_locked), the
    owner's console drops to read-only — they can still SEE everything and, crucially, still
    PAY us (the top-up/settlement views are separate APIViews that do not carry this
    permission, so they stay open — there must never be a catch-22 where the one screen that
    clears the debt is itself locked).

    Distinct from TenantIsOperational (which is SUSPENDED — an AML/TOS shutdown that hides
    the console entirely). Past-due is a money state, not a trust state.
    """

    message = (
        "Your account is past due. You can still view everything and pay — settle your "
        "balance in Settings > Payments to restore full access."
    )

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True  # reading is always allowed
        user = request.user
        if user and user.is_authenticated and user.is_platform_staff:
            return True  # platform staff can still act on a locked tenant
        operator = acting_tenant(request)
        if operator is None:
            return True  # RequireTenant reports this case
        from apps.billing.enforcement import is_locked

        return not is_locked(operator)


class RequireCapability(BasePermission):
    """LAYER A of RBAC: gate a view on a single capability string (see accounts/rbac.py).

    Usage — instantiate with the capability the view needs:

        permission_classes = [IsAuthenticated, RequireTenant, RequireCapability("network.write")]

    The role -> capability map is the ONE place a role's reach is defined, so a new screen adds a
    capability + this gate and touches nothing else. Row-level ("own tickets only") and
    field-level ("status not amounts") scoping are separate layers (get_queryset / serializer);
    this only answers "may this role perform this action at all".

    Pass `read=<other_capability>` to require a LIGHTER capability on safe (GET/HEAD) requests than
    on writes — e.g. RequireCapability("leads.write", read="leads.view") lets a technician read
    leads while only Care/Admin may edit them.
    """

    def __init__(self, capability: str, read: str | None = None):
        self.capability = capability
        self.read_capability = read

    def __call__(self):
        # DRF instantiates permission_classes; we're already an instance, so return self.
        return self

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        lighter = self.read_capability and request.method in SAFE_METHODS
        needed = self.read_capability if lighter else self.capability
        if user.has_capability(needed):
            return True
        self.message = f"Your role does not allow this action ({needed})."
        return False


class HasViewsetCapability(BasePermission):
    """LAYER A on the tenant viewsets: enforce the capability a viewset DECLARES, by method.

    A viewset sets `read_capability` (list/retrieve) and/or `write_capability` (create/update/
    delete) as class attributes; either may be a single capability string or an iterable of them
    (ANY-of — e.g. a client is writable by clients.write OR clients.field OR clients.plan, with the
    narrower ones field-scoped in the serializer). A `None` capability means "not gated here", so a
    viewset that hasn't opted in behaves exactly as before.

    Platform staff BYPASS this gate: platform support must still read every tenant's data for
    support, and its writes are already refused by ReadOnlyForSupport. Platform owner has full
    power. Keeping them out of the capability map preserves today's platform behaviour unchanged.
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_platform_staff:
            return True
        attr = "read_capability" if request.method in SAFE_METHODS else "write_capability"
        needed = getattr(view, attr, None)
        if needed is None:
            return True
        caps = (needed,) if isinstance(needed, str) else tuple(needed)
        if any(user.has_capability(c) for c in caps):
            return True
        self.message = "Your role does not allow this action here."
        return False


class CanManageMoney(BasePermission):
    """Withdrawals and payout destinations: the ISP OWNER, acting as themselves."""

    message = "Only the ISP owner can withdraw funds."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True

        # NEVER on a borrowed identity. Impersonation exists to TROUBLESHOOT, and
        # troubleshooting never requires moving money.
        #
        # Without this, a platform account — or anyone who steals one — opens a grant,
        # enrols their OWN authenticator, and withdraws the ISP's balance. The second
        # factor would be satisfied by the attacker's own phone, which makes it
        # decoration. This is also what keeps the platform-side MFA reset from being a
        # master key: support can clear a lost device, but cannot then spend the money.
        if is_impersonating(request):
            self.message = (
                "You are acting as another ISP. Money cannot move on a borrowed "
                "identity — the ISP owner must do this themselves."
            )
            return False

        return user.can_manage_money
