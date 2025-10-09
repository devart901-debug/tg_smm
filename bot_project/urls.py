from django.contrib import admin
from django.urls import path, include
from campaigns import views

urlpatterns = [
    path('', admin.site.urls),
    path('', views.home_page, name='home'),
    path('webhook/', include('campaigns.urls')),
]