from django.contrib import admin

from .models import Router, RouterHealthCheck, Session


@admin.register(Router)
class RouterAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "operator",
        "management_host",
        "status",
        "routeros_version",
        "last_seen_at",
        "last_sync_at",
        "is_active",
    )
    list_filter = ("provisioning_backend", "status", "is_active")
    readonly_fields = ("enrollment_token", "enrolled_at", "last_seen_at", "last_sync_at")


@admin.register(RouterHealthCheck)
class RouterHealthCheckAdmin(admin.ModelAdmin):
    list_display = ("router", "online", "checked_at")
    list_filter = ("online", "router")
    date_hierarchy = "checked_at"


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
