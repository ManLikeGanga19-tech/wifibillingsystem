from django.contrib import admin

from .models import Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "plan_type",
        "price",
        "duration",
        "download_kbps",
        "upload_kbps",
        "data_cap_mb",
        "is_active",
    )
    list_filter = ("plan_type", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name",)
