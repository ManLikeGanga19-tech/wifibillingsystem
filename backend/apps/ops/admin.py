from django.contrib import admin

from .models import Equipment, Expense, Lead, Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "subscriber", "status", "priority", "assigned_to")
    list_filter = ("status", "priority")
    search_fields = ("subject", "subscriber__phone")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "location", "source", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "phone")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("date", "category", "description", "amount", "router")
    list_filter = ("category", "router")
    date_hierarchy = "date"


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "equipment_type", "serial_number", "status", "router", "cost")
    list_filter = ("equipment_type", "status")
    search_fields = ("name", "serial_number")
