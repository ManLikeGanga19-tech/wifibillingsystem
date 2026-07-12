from django.contrib import admin

from .models import AuditLog, Operator


@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "settlement_verified_at", "is_active", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_type", "target_id")
    list_filter = ("action", "target_type")
    search_fields = ("target_id", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
