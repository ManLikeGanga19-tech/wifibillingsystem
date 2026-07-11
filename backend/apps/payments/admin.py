from django.contrib import admin

from .models import C2BPayment, Transaction


@admin.register(C2BPayment)
class C2BPaymentAdmin(admin.ModelAdmin):
    list_display = ("received_at", "trans_id", "bill_ref", "amount", "status", "client")
    list_filter = ("status",)
    search_fields = ("trans_id", "bill_ref", "msisdn")
    readonly_fields = [f.name for f in C2BPayment._meta.fields]

    def has_add_permission(self, request):
        return False


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
