from django.contrib import admin

from .models import LedgerEntry, Payout


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "operator", "entry_type", "amount", "memo")
    list_filter = ("entry_type", "operator")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False  # money lines only via services (auditable, idempotent)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("created_at", "operator", "amount", "phone", "status", "mpesa_reference")
    list_filter = ("status", "operator")
