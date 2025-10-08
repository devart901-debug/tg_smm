from django.urls import path
from . import telegram_handlers
from . import views

urlpatterns = [
    path('telegram/', telegram_handlers.telegram_webhook, name='telegram_webhook'),
    path('test/', views.test_page, name='test_page'),
]
