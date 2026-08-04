"""
Models for the AI Phone Ordering System.
"""

from django.db import models


class MenuItem(models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    modifiers = models.JSONField(
        default=list,
        help_text='List of available modifications, e.g. ["extra spicy", "no onions", "extra cheese"]',
    )
    aliases = models.JSONField(
        default=list, blank=True,
        help_text='Phonetic variants / common mispronunciations for STT, e.g. ["kalsoy", "cosign"] for Khao Soi',
    )
    thai_name = models.CharField(
        max_length=200, blank=True,
        help_text='Thai script name, e.g. ข้าวซอย for Khao Soi. Used for matching when Thai speakers say the real name.',
    )
    available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} — ${self.price}'


class Order(models.Model):
    STATUSES = [
        ('new', 'New'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUSES, default='new')
    total = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    sms_sent = models.BooleanField(default=False)
    call_sid = models.CharField(max_length=100, blank=True, help_text='Twilio call SID for reference')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Order #{self.id} — {self.customer_name} (Pickup)'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200, help_text='Name as spoken by customer')
    quantity = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    notes = models.CharField(max_length=500, blank=True, help_text='Modifications / special requests')

    def __str__(self):
        return f'{self.quantity}x {self.name}'

    @property
    def line_total(self):
        return self.quantity * self.price
