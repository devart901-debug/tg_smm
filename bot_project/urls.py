from django.contrib import admin
from django.urls import path, include
from campaigns import views
from django.views.generic import RedirectView

urlpatterns = [
    path('', RedirectView.as_view(url='/admin/')),  # Редирект на админку
    path('admin/', admin.site.urls),
    path('campaigns/', include('campaigns.urls')),
    path('', views.home_page, name='home'),
    path('webhook/', include('campaigns.urls')),
]