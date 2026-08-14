from django.db import migrations


def backfill(apps, schema_editor):
    """Give every already-live tenant an ACTIVATED anchor so precise churn has a baseline.

    Precise tenant churn counts activations vs suspensions inside a window. Tenants that
    went live BEFORE this log existed have no events, so they'd be invisible to the "who
    was live at the start of the month" denominator. We anchor one ACTIVATED per such
    tenant at its approved_at (the moment its money gate opened), fallback created_at.

    We deliberately do NOT invent SUSPENDED events for currently-suspended tenants: we
    have no trustworthy suspension DATE, and dating it wrong would fabricate churn in the
    wrong month. Churn is precise from here forward; every real suspension is logged live.
    The demo tenant earns nothing and is skipped.
    """
    Operator = apps.get_model("core", "Operator")
    Event = apps.get_model("core", "TenantLifecycleEvent")

    rows = []
    for op in Operator.objects.exclude(is_demo=True).filter(approved_at__isnull=False):
        rows.append(Event(
            operator=op,
            slug=op.slug,
            name=op.name,
            event="activated",
            to_status=op.status,
            reason="backfilled anchor",
            occurred_at=op.approved_at or op.created_at,
        ))
    Event.objects.bulk_create(rows, batch_size=200)


def unbackfill(apps, schema_editor):
    Event = apps.get_model("core", "TenantLifecycleEvent")
    Event.objects.filter(reason="backfilled anchor").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0024_tenantlifecycleevent")]
    operations = [migrations.RunPython(backfill, unbackfill)]
