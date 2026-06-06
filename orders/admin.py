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
    list_display = ['id', 'customer_name', 'customer_phone', 'order_type', 'status', 'total', 'sms_sent', 'created_at']
    list_filter = ['status', 'order_type', 'sms_sent', 'created_at']
    search_fields = ['customer_name', 'customer_phone', 'notes']
    inlines = [OrderItemInline]
    readonly_fields = ['call_sid']


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'category', 'available', 'created_at']
    list_filter = ['category', 'available']
    search_fields = ['name', 'description']
    list_editable = ['price', 'available']
