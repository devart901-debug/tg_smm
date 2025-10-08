from django.urls import path
from . import views
from . import telegram_handlers

urlpatterns = [
    path('webhook/telegram/', telegram_handlers.telegram_webhook, name='telegram_webhook'),
    path('test/', views.test_page, name='test_page'),
]