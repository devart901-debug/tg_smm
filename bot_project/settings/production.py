from .base import *
import os
from dotenv import load_dotenv

load_dotenv()

DEBUG = False
ALLOWED_HOSTS = ['bot.laconistiq.ru', 'localhost', '127.0.0.1']


# База данных PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'telegram_bot'),
        'USER': os.getenv('DB_USER', 'bot_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Static files
STATIC_ROOT = '/var/www/telegram-bot/static/'
MEDIA_ROOT = '/var/www/telegram-bot/media/'

# Security
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')