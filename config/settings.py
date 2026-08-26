"""
Django settings for AI Phone Ordering System.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-change-in-production')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'channels',
    'orders',
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# In-memory channel layer for dev; switch to Redis in production
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'chiang_mai_ai'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Chicago'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

# Logging — ensure all app output goes to console
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '%(levelname)s %(name)s %(message)s'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'orders': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'daphne': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- API Keys & Config ---
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
RESTAURANT_PHONE = os.getenv('RESTAURANT_PHONE')
# Optional: phone number to transfer callers to when they ask for a human.
# MUST NOT equal RESTAURANT_PHONE (AT&T no-answer forwarding would bounce the
# call back into the AI) or TWILIO_PHONE_NUMBER. Empty = feature disabled.
TRANSFER_PHONE = os.getenv('TRANSFER_PHONE', '')
RESTAURANT_NAME = os.getenv('RESTAURANT_NAME', 'Our Restaurant')

# Deepgram Voice Agent API — STT + LLM + TTS in one managed WebSocket.
# See https://developers.deepgram.com/docs/voice-agent
# STT: nova-3-general supports keyterm biasing (needed for Thai dish names);
#      flux-general-en has better native turn-taking but NO keyterm support.
DEEPGRAM_VOICE_AGENT_STT_MODEL = os.getenv('DEEPGRAM_VOICE_AGENT_STT_MODEL', 'nova-3-general')
DEEPGRAM_VOICE_AGENT_LLM_MODEL = os.getenv('DEEPGRAM_VOICE_AGENT_LLM_MODEL', 'gpt-4o-mini')
DEEPGRAM_VOICE_AGENT_TTS_MODEL = os.getenv('DEEPGRAM_VOICE_AGENT_TTS_MODEL', 'aura-asteria-en')
DEEPGRAM_VOICE_AGENT_TEMPERATURE = float(os.getenv('DEEPGRAM_VOICE_AGENT_TEMPERATURE', '0'))

# Clover POS — menu source of truth + order placement.
# Token: long-lived merchant API token (API Access → Generate Token), not OAuth.
CLOVER_MERCHANT_ID = os.getenv('CLOVER_MERCHANT_ID')
CLOVER_API_TOKEN = os.getenv('CLOVER_API_TOKEN')
CLOVER_BASE_URL = os.getenv('CLOVER_BASE_URL', 'https://api.clover.com')
CLOVER_ORDER_TYPE_NAME = os.getenv('CLOVER_ORDER_TYPE_NAME', 'Take out')
# Optional hardcoded order-type id — bypasses the /order_types lookup, which some
# API tokens can't read (401). Find the id in the dashboard URL for that order type.
CLOVER_ORDER_TYPE_ID = os.getenv('CLOVER_ORDER_TYPE_ID', '')
