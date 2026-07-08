from django.contrib import admin

from .models import Voucher


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ("code", "plan", "status", "batch_id", "redeemed_at", "printed", "created_at")
    list_filter = ("status", "plan", "printed")
    search_fields = ("code", "batch_id")
    readonly_fields = ("redeemed_by", "redeemed_at", "created_at", "updated_at")
