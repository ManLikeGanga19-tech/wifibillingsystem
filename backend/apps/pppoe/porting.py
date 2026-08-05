"""Getting an ISP's customers in, and letting them out again.

THREE paths, because an ISP arrives with their data in different shapes:

  * ROUTER IMPORT — adopt the /ppp/secret users already dialling into their MikroTik. Gives
    real credentials, but a router knows nothing about the person behind them.
  * CSV IMPORT — take their customer list out of whatever billing system they used before.
    Gives the names, phones, addresses and billing days a router never had.
  * EXPORT — every client as CSV. A backup, and the file they take WITH them if they leave.

The CSV import accepts our own export format, so a file that leaves WIFI.OS comes straight
back in. That round-trip is what makes "you can always leave" true in both directions.

Enterprise-grade on purpose, for all three:
  * PREVIEW before commit — the ISP sees exactly what will happen, and maps plans first.
  * IDEMPOTENT — a username WIFI.OS already manages is skipped, so a re-run never duplicates.
  * PER-CLIENT isolation — one bad row is recorded and skipped, never aborting the batch.
  * NON-DISRUPTIVE — nothing is pushed to a router behind the ISP's back.
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


# ---- CSV import (migrating in from another billing system) --------------------------------
#
# The router import above adopts users that are already dialling in; this one takes an ISP's
# customer LIST from wherever they kept it before. They are complementary: the router knows
# usernames and passwords but nothing about the person, while an old billing system's export
# has the names, phones, addresses and billing days the router never had.
#
# The accepted shape is our own export, so a file that leaves WIFI.OS comes back in — which
# is what makes "you can always leave" true in both directions.

#: A guard, not a limit anyone should hit: ~10k clients is far beyond a single ISP's base,
#: and refusing early beats timing out halfway through parsing something enormous.
MAX_IMPORT_ROWS = 10_000

#: The only column we truly need. Everything else in the file (created_at, balance, …) is
#: ignored rather than rejected, so an export pasted straight back in just works.
CSV_REQUIRED_COLUMNS = ("full_name",)


class CsvImportError(Exception):
    """The file itself is unusable — not one bad row, but nothing worth previewing."""


def parse_client_csv(text: str) -> list[dict]:
    """Parse an uploaded CSV into dicts, tolerantly: any column order, case-insensitive
    headers, surrounding whitespace, and a UTF-8 BOM (Excel writes one, and it would
    otherwise corrupt the first header name and make the file look malformed)."""
    import csv
    import io

    if not (text or "").strip():
        raise CsvImportError("That file is empty.")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise CsvImportError("Could not read a header row from that file.")

    headers = {(h or "").strip().lower(): (h or "") for h in reader.fieldnames}
    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise CsvImportError(
            f"That file has no '{missing[0]}' column. Export your clients from WIFI.OS to "
            "see the expected format."
        )

    rows = []
    for raw in reader:
        row = {key: (raw.get(original) or "").strip() for key, original in headers.items()}
        if any(row.values()):  # skip blank lines
            rows.append(row)
        if len(rows) > MAX_IMPORT_ROWS:
            raise CsvImportError(
                f"That file has more than {MAX_IMPORT_ROWS:,} rows. Split it and import "
                "in batches."
            )
    if not rows:
        raise CsvImportError("That file has a header but no rows.")
    return rows


def _row_problem(row: dict, seen: set) -> str:
    """Why this row cannot be imported, or "" if it can. Every row is checked BEFORE anything
    is written, so the ISP sees all the problems up front rather than discovering them one
    failure at a time."""
    if not row.get("full_name"):
        return "No name"

    username = row.get("pppoe_username", "")
    if username:
        if username in seen:
            return "Duplicate PPPoE username inside this file"
        # Globally unique. A clash with ANOTHER ISP's user cannot be silently renamed,
        # because that username is exactly what the customer's router dials with.
        if Client.objects.filter(pppoe_username=username).exists():
            return "That PPPoE username is already taken"

    day = row.get("billing_day", "")
    if day and (not day.isdigit() or not 1 <= int(day) <= 28):
        return "Billing day must be a number from 1 to 28"
    return ""


def preview_csv_import(operator, rows: list[dict]) -> dict:
    """Describe exactly what importing this file would do — row by row, plus which plan names
    in it map to which of the ISP's plans. Nothing is written."""
    plans = {p.name.strip().lower(): p for p in ServicePlan.objects.filter(operator=operator)}

    seen: set = set()
    analysed = []
    plan_names: dict = {}
    for i, row in enumerate(rows, start=2):  # 2 = the first data line in a spreadsheet
        problem = _row_problem(row, seen)
        username = row.get("pppoe_username", "")
        if username:
            seen.add(username)

        raw_plan = row.get("plan", "")
        if raw_plan and raw_plan.lower() not in plan_names:
            matched = plans.get(raw_plan.lower())
            plan_names[raw_plan.lower()] = {
                "csv_plan": raw_plan,
                "plan": matched.id if matched else None,
                "plan_name": matched.name if matched else None,
            }

        analysed.append({
            "line": i,
            "full_name": row.get("full_name", ""),
            "phone": row.get("phone", ""),
            "account_number": row.get("account_number", ""),
            "pppoe_username": username,
            "csv_plan": raw_plan,
            "has_password": bool(row.get("pppoe_password")),
            "problem": problem,
            "importable": not problem,
        })

    return {
        "rows": analysed,
        "importable": sum(1 for r in analysed if r["importable"]),
        "blocked": sum(1 for r in analysed if not r["importable"]),
        # The ISP maps any plan name we could not match; every row needs a plan to land on.
        "plans": list(plan_names.values()),
    }


def import_clients_from_csv(
    operator, router, *, rows: list[dict], plan_map: dict | None = None,
    default_plan=None, actor=None,
) -> dict:
    """Create clients from a parsed CSV.

    Imported clients land as PENDING_INSTALL deliberately. Unlike the router import — where
    the user is demonstrably already dialling in — we have no evidence these accounts exist
    on any router yet. The ISP presses Provision, one explicit step, and THAT pushes the
    secret. Marking them ACTIVE on trust would bill for customers who may not be connected
    and would leave the console disagreeing with the router from the first minute.

    Per-row isolation: one bad row is recorded and skipped, never aborting the batch.
    """
    plans = {p.id: p for p in ServicePlan.objects.filter(operator=operator)}
    by_csv_name = {
        str(k).strip().lower(): plans.get(v)
        for k, v in (plan_map or {}).items()
        if plans.get(v)
    }

    imported, skipped, failed = [], [], []
    seen: set = set()
    for row in rows:
        name = row.get("full_name", "")
        username = row.get("pppoe_username", "")
        try:
            problem = _row_problem(row, seen)
            if problem:
                skipped.append({"name": name or "(no name)", "reason": problem})
                continue
            if username:
                seen.add(username)

            plan = by_csv_name.get(row.get("plan", "").strip().lower()) or default_plan
            if plan is None:
                skipped.append({"name": name, "reason": "No plan chosen for this row"})
                continue

            fields = {
                "full_name": name[:120],
                "phone": row.get("phone", "")[:20],
                "email": row.get("email", "")[:254],
                "physical_address": row.get("physical_address", "")[:200],
            }
            day = row.get("billing_day", "")
            if day.isdigit():
                fields["billing_day"] = int(day)
            delivery = row.get("delivery_method", "").lower()
            if delivery in dict(Client.Delivery.choices):
                fields["delivery_method"] = delivery
            # Carry the credentials when the file has them, so a customer's CPE keeps working
            # unchanged; generate fresh ones when it doesn't.
            if username:
                fields["pppoe_username"] = username
            if row.get("pppoe_password"):
                fields["pppoe_password"] = row["pppoe_password"]

            client = create_client(
                operator=operator, plan=plan, router=router, created_by=actor, **fields
            )
            imported.append({
                "name": client.full_name,
                "account_number": client.account_number,
                "pppoe_username": client.pppoe_username,
            })
        except Exception as exc:  # noqa: BLE001 - isolate one bad row from the whole batch
            failed.append({"name": name or "(no name)", "reason": str(exc)[:200]})

    audit(
        "pppoe_clients_csv_imported", operator=operator, actor=actor, router=router.name,
        imported=len(imported), skipped=len(skipped), failed=len(failed),
    )
    return {"imported": imported, "skipped": skipped, "failed": failed}
