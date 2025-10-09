# campaigns/apps.py
from django.apps import AppConfig

class CampaignsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'campaigns'
    # УБЕРИТЕ verbose_name если добавляли