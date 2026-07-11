from django.contrib import admin

from .models import AccessPoint, Client, Invoice, ServicePlan, Tower


@admin.register(ServicePlan)
class ServicePlanAdmin(admin.ModelAdmin):
    list_display = ("name", "operator", "price", "download_kbps", "upload_kbps", "is_active")
    list_filter = ("operator", "is_active")


@admin.register(Tower)
class TowerAdmin(admin.ModelAdmin):
    list_display = ("name", "operator", "is_active")
    list_filter = ("operator", "is_active")


@admin.register(AccessPoint)
class AccessPointAdmin(admin.ModelAdmin):
    list_display = ("name", "tower", "operator", "mode", "capacity", "is_active")
    list_filter = ("operator", "mode", "is_active")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "account_number",
        "full_name",
        "operator",
        "plan",
        "status",
        "delivery_method",
        "next_due_date",
    )
    list_filter = ("operator", "status", "delivery_method")
    search_fields = ("account_number", "full_name", "phone", "pppoe_username")
    readonly_fields = ("account_number", "created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "client", "operator", "amount", "status", "due_date", "paid_at")
    list_filter = ("operator", "status")
    search_fields = ("number", "client__account_number")
    date_hierarchy = "issued_at"
