from django.urls import path
from . import views
from . import telegram_handlers

urlpatterns = [
    path('telegram-webhook/<str:token>/', telegram_handlers.telegram_webhook, name='telegram_webhook'),
]