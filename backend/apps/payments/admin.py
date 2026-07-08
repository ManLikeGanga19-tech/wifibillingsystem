from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "phone",
        "plan",
        "amount",
        "status",
        "mpesa_receipt",
        "result_code",
    )
    list_filter = ("status", "plan")
    search_fields = ("phone", "mpesa_receipt", "checkout_request_id")
    readonly_fields = (
        "public_id",
        "checkout_request_id",
        "merchant_request_id",
        "raw_callback",
        "callback_received_at",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
