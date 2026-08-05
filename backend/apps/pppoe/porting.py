"""Import and export for broadband clients.

IMPORT adopts an ISP's pre-existing /ppp/secret users off their MikroTik into WIFI.OS —
for an ISP onboarding who was already running PPPoE by hand. EXPORT streams every client
as CSV — a portable backup or migration out.

Enterprise-grade on purpose:
  * PREVIEW before commit — the ISP sees exactly what will happen and maps profiles to plans.
  * IDEMPOTENT — a username WIFI.OS already manages is skipped, so a re-run never duplicates.
  * PER-CLIENT isolation — one bad row is recorded and skipped, never aborting the batch.
  * NON-DISRUPTIVE — import is DB-only; the live sessions on the router are never touched.
  * AUDITED.
"""

from django.utils import timezone

from apps.billing.reports import _stream_csv
from apps.core.services import audit
from apps.provisioning.adapters import get_adapter

from .models import Client, ServicePlan
from .services import create_client


def preview_import(operator, router) -> list[dict]:
    """Read the router's PPPoE secrets and describe what an import would do: which are new,
    which WIFI.OS already manages, and the plan each maps to (matched by profile name)."""
    secrets = get_adapter(router).list_pppoe_secrets()
    managed = set(
        Client.objects.filter(
            pppoe_username__in=[s.username for s in secrets]
        ).values_list("pppoe_username", flat=True)
    )
    plans_by_profile = {
        p.mikrotik_profile: p
        for p in ServicePlan.objects.filter(operator=operator)
        if p.mikrotik_profile
    }
    rows = []
    for s in secrets:
        plan = plans_by_profile.get(s.profile)
        rows.append({
            "username": s.username,
            "profile": s.profile,
            "comment": s.comment,
            "already_managed": s.username in managed,
            "suggested_plan": plan.id if plan else None,
            "suggested_plan_name": plan.name if plan else None,
        })
    return rows


def import_clients(operator, router, *, items, actor=None) -> dict:
    """Adopt selected router secrets as managed clients. The password is read FRESH off the
    router (authoritative) — the caller only chooses which usernames to import and their
    name + plan. DB-only: the client's live session on the router is never disturbed."""
    secrets = {s.username: s for s in get_adapter(router).list_pppoe_secrets()}
    valid_plan_ids = set(
        ServicePlan.objects.filter(operator=operator).values_list("id", flat=True)
    )
    imported, skipped, failed = [], [], []
    for item in items:
        username = (item.get("username") or "").strip()
        try:
            secret = secrets.get(username)
            if secret is None:
                skipped.append({"username": username, "reason": "not on the router"})
                continue
            if Client.objects.filter(pppoe_username=username).exists():
                skipped.append({"username": username, "reason": "already managed"})
                continue
            if item.get("plan") not in valid_plan_ids:
                skipped.append({"username": username, "reason": "no plan chosen"})
                continue
            plan = ServicePlan.objects.get(id=item["plan"], operator=operator)
            name = (item.get("full_name") or secret.comment or username).strip()[:120]
            client = create_client(
                operator=operator, plan=plan, router=router, created_by=actor,
                full_name=name, pppoe_username=username, pppoe_password=secret.password,
            )
            # Already live on the router — adopt as ACTIVE without re-pushing the secret.
            client.status = Client.Status.ACTIVE
            client.installed_at = timezone.localdate()
            client.save(update_fields=["status", "installed_at", "updated_at"])
            imported.append({"username": username, "account_number": client.account_number})
        except Exception as exc:  # noqa: BLE001 - isolate one bad row from the whole batch
            failed.append({"username": username, "reason": str(exc)[:200]})
    audit(
        "pppoe_clients_imported", operator=operator, actor=actor, router=router.name,
        imported=len(imported), skipped=len(skipped), failed=len(failed),
    )
    return {"imported": imported, "skipped": skipped, "failed": failed}


#: The export shape. `pppoe_password` is deliberately LAST and opt-in — see clients_csv.
#: This is also the shape the CSV importer expects, so an export round-trips back in.
CLIENT_CSV_COLUMNS = [
    "account_number", "full_name", "phone", "email", "physical_address", "plan",
    "pppoe_username", "status", "billing_day", "balance",
    "next_due_date", "delivery_method", "static_ip", "created_at",
]
CREDENTIAL_COLUMN = "pppoe_password"


def clients_csv(operator, *, include_credentials: bool = False):
    """Stream every client as CSV — a portable backup, and how an ISP leaves with their data.

    PPPoE passwords are opt-in. They are plaintext of necessity (CHAP needs a retrievable
    secret, and RouterOS stores them in plaintext anyway), which makes an unconditional
    export a silent bulk credential dump on every click. Opt-in keeps the ISP's right to
    take everything — without handing it over by accident. The caller enforces WHO may ask.
    """
    columns = [*CLIENT_CSV_COLUMNS]
    if include_credentials:
        columns.append(CREDENTIAL_COLUMN)

    def rows():
        for c in (
            Client.objects.filter(operator=operator)
            .select_related("plan").order_by("account_number").iterator()
        ):
            row = [
                c.account_number, c.full_name, c.phone, c.email, c.physical_address,
                c.plan.name if c.plan_id else "", c.pppoe_username,
                c.status, c.billing_day, c.balance, c.next_due_date or "",
                c.delivery_method, c.static_ip or "", c.created_at.isoformat(),
            ]
            if include_credentials:
                row.append(c.pppoe_password)
            yield row

    stamp = timezone.localdate().isoformat()
    suffix = "-with-credentials" if include_credentials else ""
    return _stream_csv(
        f"clients-{operator.slug}-{stamp}{suffix}.csv", columns, rows()
    )
