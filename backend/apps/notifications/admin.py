from django.contrib import admin

from .models import Campaign, Message


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "channel",
        "audience",
        "status",
        "total_recipients",
        "sent_count",
        "failed_count",
        "created_at",
    )
    list_filter = ("channel", "audience", "status")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("to_phone", "channel", "status", "campaign", "sent_at", "error")
    list_filter = ("channel", "status")
    search_fields = ("to_phone",)
