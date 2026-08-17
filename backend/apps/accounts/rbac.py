"""What each role may do inside a tenant.

Two layers:
  1. DEFAULTS — the recommended capability set per role, hardcoded below (ROLE_CAPABILITIES).
  2. PER-TENANT OVERRIDES — an Owner can edit what each delegated role (admin/care/technician)
     may do, on the Access Control page. Those edits live in OperatorRoleConfig and win over the
     defaults for that tenant. capabilities_for() reads the override if present, else the default.

Capabilities are dotted strings (`resource.action`). A view declares the capability it needs
(RequireCapability); the console hides any module whose capability the role lacks. The server is
always authoritative — the UI hiding is convenience.

TWO capabilities are NON-DELEGABLE and can never be granted to a delegated role, in the UI or by
tampering with the DB: `money.manage` (withdrawals stay Owner-only) and `rbac.manage` (only the
Owner edits permissions). capabilities_for() intersects every override with ASSIGNABLE_CAPS, so
these can never leak into a delegated role even if a stored row somehow contained them.
"""

from __future__ import annotations

from .models import Role

# --- capability vocabulary (resource.action) ------------------------------------
CLIENTS_VIEW = "clients.view"
CLIENTS_WRITE = "clients.write"
CLIENTS_PLAN = "clients.plan"
CLIENTS_FIELD = "clients.field"
HOTSPOT_VOUCHERS = "hotspot.vouchers"
HOTSPOT_PLANS = "hotspot.plans"
LEADS_VIEW = "leads.view"
LEADS_WRITE = "leads.write"
NETWORK_WRITE = "network.write"           # towers, APs, radio plant
FIBRE_WRITE = "fibre.write"               # fibre outside-plant (points & spans)
ROUTER_ACCESS = "router.access"
TICKETS_VIEW = "tickets.view"
TICKETS_WORK = "tickets.work"
TICKETS_ASSIGN = "tickets.assign"
PAYMENTS_VIEW_AMOUNTS = "payments.view_amounts"
PAYMENTS_STATUS = "payments.status"
FINANCE_VIEW = "finance.view"
MONEY_MANAGE = "money.manage"           # NON-DELEGABLE — withdrawals, Owner only
MESSAGING_SEND = "messaging.send"
MESSAGING_CONFIG = "messaging.config"
SETTINGS_WRITE = "settings.write"
STAFF_MANAGE = "staff.manage"
RBAC_MANAGE = "rbac.manage"             # NON-DELEGABLE — edit role permissions, Owner only
MAP_VIEW = "map.view"
BUSINESS_LOCATION_WRITE = "business_location.write"

#: Everything a tenant can do — the Owner's full set; every other role is a subset.
ALL_TENANT_CAPS = frozenset({
    CLIENTS_VIEW, CLIENTS_WRITE, CLIENTS_PLAN, CLIENTS_FIELD,
    HOTSPOT_VOUCHERS, HOTSPOT_PLANS,
    LEADS_VIEW, LEADS_WRITE,
    NETWORK_WRITE, FIBRE_WRITE, ROUTER_ACCESS,
    TICKETS_VIEW, TICKETS_WORK, TICKETS_ASSIGN,
    PAYMENTS_VIEW_AMOUNTS, PAYMENTS_STATUS,
    FINANCE_VIEW, MONEY_MANAGE,
    MESSAGING_SEND, MESSAGING_CONFIG,
    SETTINGS_WRITE, STAFF_MANAGE, RBAC_MANAGE,
    MAP_VIEW, BUSINESS_LOCATION_WRITE,
})

#: Powers that stay with the Owner and can NEVER be handed to a delegated role.
NON_DELEGABLE = frozenset({MONEY_MANAGE, RBAC_MANAGE})

#: What an Owner may switch on/off for admin/care/technician on the Access Control page.
ASSIGNABLE_CAPS = ALL_TENANT_CAPS - NON_DELEGABLE

#: What a read-only viewer (platform support) may LOOK at.
READ_ONLY_CAPS = frozenset({
    CLIENTS_VIEW, LEADS_VIEW, TICKETS_VIEW,
    PAYMENTS_VIEW_AMOUNTS, FINANCE_VIEW, MAP_VIEW,
})

# --- recommended defaults --------------------------------------------------------
_ADMIN = ALL_TENANT_CAPS - NON_DELEGABLE

_CARE = frozenset({
    CLIENTS_VIEW, CLIENTS_WRITE, CLIENTS_PLAN,
    HOTSPOT_VOUCHERS,
    LEADS_VIEW, LEADS_WRITE,
    TICKETS_VIEW, TICKETS_WORK, TICKETS_ASSIGN,
    PAYMENTS_STATUS,
    MESSAGING_SEND, MAP_VIEW,
})

_TECHNICIAN = frozenset({
    CLIENTS_VIEW, CLIENTS_FIELD,
    NETWORK_WRITE, FIBRE_WRITE, ROUTER_ACCESS,   # fibre bundled with radio plant by default
    TICKETS_VIEW, TICKETS_WORK,
    LEADS_VIEW,
    MAP_VIEW,
})

#: role -> recommended capability set. Only the delegated roles are editable; Owner/platform are
#: resolved directly in capabilities_for so "everything" can never drift out of sync.
ROLE_CAPABILITIES = {
    Role.TENANT_ADMIN: _ADMIN,
    Role.TENANT_CARE: _CARE,
    Role.TENANT_TECHNICIAN: _TECHNICIAN,
}

#: The roles an Owner may customise on the Access Control page.
CONFIGURABLE_ROLES = (Role.TENANT_ADMIN, Role.TENANT_CARE, Role.TENANT_TECHNICIAN)

# --- human-readable catalogue (drives the Access Control checkboxes) -------------
#: (group, capability, label) for every ASSIGNABLE capability, in display order.
CAPABILITY_CATALOG = [
    ("Customers", CLIENTS_VIEW, "See clients"),
    ("Customers", CLIENTS_WRITE, "Add / edit clients"),
    ("Customers", CLIENTS_PLAN, "Change a client's plan"),
    ("Customers", CLIENTS_FIELD, "Update client status & location (field)"),
    ("Customers", HOTSPOT_VOUCHERS, "Issue hotspot vouchers"),
    ("Customers", LEADS_VIEW, "See leads"),
    ("Customers", LEADS_WRITE, "Manage leads (CRM)"),
    ("Network", NETWORK_WRITE, "Towers, access points & radio plant"),
    ("Network", FIBRE_WRITE, "Fibre plant (points & spans)"),
    ("Network", ROUTER_ACCESS, "Router access & provisioning"),
    ("Network", HOTSPOT_PLANS, "Create & price plans"),
    ("Network", MAP_VIEW, "Open the map"),
    ("Network", BUSINESS_LOCATION_WRITE, "Set the business location"),
    ("Tickets", TICKETS_VIEW, "See tickets"),
    ("Tickets", TICKETS_WORK, "Work / resolve tickets"),
    ("Tickets", TICKETS_ASSIGN, "Assign tickets to technicians"),
    ("Money", PAYMENTS_VIEW_AMOUNTS, "See payment amounts & ledger"),
    ("Money", PAYMENTS_STATUS, "Mark payments paid / unpaid"),
    ("Money", FINANCE_VIEW, "Invoices, reports & wallet balance"),
    ("Comms & admin", MESSAGING_SEND, "Send messages"),
    ("Comms & admin", MESSAGING_CONFIG, "Message templates & channels"),
    ("Comms & admin", SETTINGS_WRITE, "Operator settings"),
    ("Comms & admin", STAFF_MANAGE, "Manage employees"),
]


def default_capabilities(role) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(role, frozenset())


def _override_for(operator, role) -> frozenset[str] | None:
    """The Owner's saved capability set for this (operator, role), or None if they haven't
    customised it. Intersected with ASSIGNABLE_CAPS so a non-delegable power can never appear."""
    if operator is None:
        return None
    from .models import OperatorRoleConfig

    row = OperatorRoleConfig.objects.filter(operator=operator, role=role).first()
    if row is None:
        return None
    return frozenset(row.capabilities) & ASSIGNABLE_CAPS


def capabilities_for(user) -> frozenset[str]:
    """The resolved capability set for a user. Owner = everything; platform support = read-only;
    a delegated role = the tenant's override if the Owner set one, else the recommended default."""
    role = user.role
    if role in (Role.PLATFORM_OWNER, Role.TENANT_OWNER):
        return ALL_TENANT_CAPS
    if role == Role.PLATFORM_SUPPORT:
        return READ_ONLY_CAPS
    if role in CONFIGURABLE_ROLES:
        override = _override_for(user.operator, role)
        return override if override is not None else default_capabilities(role)
    return frozenset()


def effective_capabilities(operator, role) -> frozenset[str]:
    """The capability set a given role has AT a given tenant — used by the Access Control API to
    show the current state without needing a user of that role to exist."""
    if role not in CONFIGURABLE_ROLES:
        return frozenset()
    override = _override_for(operator, role)
    return override if override is not None else default_capabilities(role)


def has_capability(user, capability: str) -> bool:
    return capability in capabilities_for(user)
