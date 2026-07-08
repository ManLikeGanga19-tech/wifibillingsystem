from django.contrib import admin

from .models import Router, Session


@admin.register(Router)
class RouterAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "management_host",
        "api_port",
        "provisioning_backend",
        "status",
        "last_seen_at",
        "is_active",
    )
    list_filter = ("provisioning_backend", "status", "is_active")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        "hotspot_username",
        "plan",
        "router",
        "status",
        "starts_at",
        "expires_at",
        "mac_address",
    )
    list_filter = ("status", "router", "plan")
    search_fields = ("hotspot_username", "mac_address")
    readonly_fields = ("transaction", "voucher", "created_at", "updated_at")
    date_hierarchy = "created_at"
