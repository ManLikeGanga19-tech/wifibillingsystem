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

    def has_permission(self, request, view):
        return acting_tenant(request) is not None


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
