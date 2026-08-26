"""
HTTP URL routing for Twilio webhooks.
"""

from django.urls import path
from . import views

urlpatterns = [
    path('voice/', views.twilio_voice_webhook, name='twilio-voice'),
    path('sms-status/', views.twilio_sms_status, name='twilio-sms-status'),
    path('transfer-result/', views.twilio_transfer_result, name='twilio-transfer-result'),
]
