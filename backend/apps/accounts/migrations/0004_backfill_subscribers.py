"""Rebuild customer identities as Subscribers.

Customers used to be rows in the User table (globally-unique phone), which meant
one phone could not be a customer of two ISPs, nor a customer and an ISP owner.
Transactions/Sessions keep the phone on the row, so we can reconstruct the
per-operator Subscriber records and relink them without data loss.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Subscriber = apps.get_model("accounts", "Subscriber")
    Transaction = apps.get_model("payments", "Transaction")
    Session = apps.get_model("provisioning", "Session")

    cache = {}

    def subscriber_for(operator_id, phone):
        key = (operator_id, phone)
        if key not in cache:
            cache[key], _ = Subscriber.objects.get_or_create(
                operator_id=operator_id, phone=phone
            )
        return cache[key]

    for tx in Transaction.objects.exclude(phone="").iterator():
        tx.subscriber = subscriber_for(tx.operator_id, tx.phone)
        tx.save(update_fields=["subscriber"])

    # Sessions inherit their customer from the paying transaction
    for session in Session.objects.select_related("transaction").iterator():
        if session.transaction and session.transaction.subscriber_id:
            session.subscriber_id = session.transaction.subscriber_id
            session.save(update_fields=["subscriber"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_subscriber"),
        ("payments", "0004_remove_transaction_user_transaction_subscriber"),
        ("provisioning", "0004_remove_session_user_session_subscriber"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
