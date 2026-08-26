"""
Django admin configuration for menu + order management.
"""

from django.contrib import admin
from .models import MenuItem, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['line_total']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer_name', 'customer_phone', 'status', 'total', 'sms_sent', 'clover_pushed', 'created_at']
    list_filter = ['status', 'sms_sent', 'clover_pushed', 'created_at']
    search_fields = ['customer_name', 'customer_phone', 'notes']
    inlines = [OrderItemInline]
    readonly_fields = ['call_sid', 'clover_order_id', 'clover_error']


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'category', 'available', 'clover_item_id', 'created_at']
    list_filter = ['category', 'available']
    search_fields = ['name', 'description', 'clover_item_id']
    list_editable = ['price', 'available']
    readonly_fields = ['clover_item_id', 'clover_modifiers']
