"""The SINGLE source of truth for what each role may do inside a tenant.

Capabilities are dotted strings (`resource.action`). A view declares the capability it needs
(`RequireCapability`); this map is the ONLY place a role's reach is defined. That is deliberate:
the previous tenant sub-roles (`tenant_manager`, `tenant_support`) were deleted because their
logic branched through every view. Here, adding a screen means adding one capability string and
one gate — never editing four roles' worth of if-branches. The permission MATRIX in the design
spec is generated from this file; the API enforces it; `/me/` ships the resolved set to the UI.

Row-level scoping ("a technician sees only their assigned tickets") is NOT a capability — it lives
in `get_queryset` (Layer B). Capabilities are coarse yes/no action gates (Layer A); field-level
redaction ("Care sees payment status, never amounts") is the serializer (Layer C).
"""

from __future__ import annotations

from .models import Role

# --- capability vocabulary (resource.action) ------------------------------------
CLIENTS_VIEW = "clients.view"
CLIENTS_WRITE = "clients.write"           # create / edit the whole record
CLIENTS_PLAN = "clients.plan"             # change a client's service plan
CLIENTS_FIELD = "clients.field"           # status + location only (the technician's edit)
HOTSPOT_VOUCHERS = "hotspot.vouchers"     # issue / sell / revoke vouchers (front desk)
HOTSPOT_PLANS = "hotspot.plans"           # create / price hotspot & broadband plans
LEADS_VIEW = "leads.view"                 # read-only (technician: map layer only)
LEADS_WRITE = "leads.write"               # the CRM: create / edit / convert
NETWORK_WRITE = "network.write"           # towers, APs, ADSS plant
ROUTER_ACCESS = "router.access"           # MikroTik access + provisioning
TICKETS_VIEW = "tickets.view"             # (technician is row-scoped to assigned — Layer B)
TICKETS_WORK = "tickets.work"             # update / resolve
TICKETS_ASSIGN = "tickets.assign"         # hand a ticket to a technician
PAYMENTS_VIEW_AMOUNTS = "payments.view_amounts"   # see amounts / ledger
PAYMENTS_STATUS = "payments.status"       # mark paid / unpaid, no amounts (Care)
FINANCE_VIEW = "finance.view"             # invoices, reports, finance
MONEY_MANAGE = "money.manage"             # withdrawals + payout config — OWNER ONLY
MESSAGING_SEND = "messaging.send"
MESSAGING_CONFIG = "messaging.config"     # templates / channel config
SETTINGS_WRITE = "settings.write"         # operator settings
STAFF_MANAGE = "staff.manage"             # create / edit / offboard employees
MAP_VIEW = "map.view"
BUSINESS_LOCATION_WRITE = "business_location.write"

#: Everything a tenant can do. The Owner's full set; every other role is a subset of this.
ALL_TENANT_CAPS = frozenset({
    CLIENTS_VIEW, CLIENTS_WRITE, CLIENTS_PLAN, CLIENTS_FIELD,
    HOTSPOT_VOUCHERS, HOTSPOT_PLANS,
    LEADS_VIEW, LEADS_WRITE,
    NETWORK_WRITE, ROUTER_ACCESS,
    TICKETS_VIEW, TICKETS_WORK, TICKETS_ASSIGN,
    PAYMENTS_VIEW_AMOUNTS, PAYMENTS_STATUS,
    FINANCE_VIEW, MONEY_MANAGE,
    MESSAGING_SEND, MESSAGING_CONFIG,
    SETTINGS_WRITE, STAFF_MANAGE,
    MAP_VIEW, BUSINESS_LOCATION_WRITE,
})

#: What a read-only viewer (platform support) may LOOK at. No write, no money-move.
READ_ONLY_CAPS = frozenset({
    CLIENTS_VIEW, LEADS_VIEW, TICKETS_VIEW,
    PAYMENTS_VIEW_AMOUNTS, FINANCE_VIEW, MAP_VIEW,
})

# --- the map ---------------------------------------------------------------------
_ADMIN = ALL_TENANT_CAPS - {MONEY_MANAGE}

_CARE = frozenset({
    CLIENTS_VIEW, CLIENTS_WRITE, CLIENTS_PLAN,
    HOTSPOT_VOUCHERS,                 # issue vouchers on the front desk — NOT plan/pricing config
    LEADS_VIEW, LEADS_WRITE,
    TICKETS_VIEW, TICKETS_WORK, TICKETS_ASSIGN,
    PAYMENTS_STATUS,                  # status only — never payments.view_amounts
    MESSAGING_SEND, MAP_VIEW,
})

_TECHNICIAN = frozenset({
    CLIENTS_VIEW, CLIENTS_FIELD,      # status/location, not create/plan
    NETWORK_WRITE, ROUTER_ACCESS,
    TICKETS_VIEW, TICKETS_WORK,       # row-scoped to assigned in get_queryset
    LEADS_VIEW,                       # read-only, map layer only — no CRM edit
    MAP_VIEW,
})

#: role -> capability set. Owner/platform-owner resolve to the full set below (kept out of the
#: dict so "everything" can never drift out of sync with ALL_TENANT_CAPS).
ROLE_CAPABILITIES = {
    Role.TENANT_ADMIN: _ADMIN,
    Role.TENANT_CARE: _CARE,
    Role.TENANT_TECHNICIAN: _TECHNICIAN,
}


def capabilities_for(user) -> frozenset[str]:
    """The resolved capability set for a user, given their role.

    Platform owner = full tenant power (for support); platform support = read-only. Money moves
    are additionally gated by CanManageMoney (owner, self-identity, TOTP) regardless of this set.
    """
    role = user.role
    if role in (Role.PLATFORM_OWNER, Role.TENANT_OWNER):
        return ALL_TENANT_CAPS
    if role == Role.PLATFORM_SUPPORT:
        return READ_ONLY_CAPS
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(user, capability: str) -> bool:
    return capability in capabilities_for(user)
