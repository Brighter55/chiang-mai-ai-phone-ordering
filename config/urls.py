"""
URL configuration — admin + Twilio webhook endpoint.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('twilio/', include('orders.urls')),
]
