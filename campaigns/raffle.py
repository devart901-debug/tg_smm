import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from campaigns.models import Campaign, Participant

class Command(BaseCommand):
    help = 'Провести розыгрыш среди участников мероприятия'
    
    def add_arguments(self, parser):
        parser.add_argument('campaign_slug', type=str, help='Slug мероприятия')
        parser.add_argument('--winners', type=int, help='Количество победителей', default=1)
    
    def handle(self, *args, **options):
        campaign_slug = options['campaign_slug']
        winners_count = options['winners']
        
        try:
            campaign = Campaign.objects.get(slug=campaign_slug)
            participants = Participant.objects.filter(campaign=campaign, is_subscribed=True)
            
            self.stdout.write(f"РОЗЫГРЫШ для мероприятия: {campaign.name}")
            self.stdout.write(f"Участников: {participants.count()}")
            self.stdout.write(f"Будет выбрано победителей: {winners_count}")
            
            # 🔴 ОСТАНАВЛИВАЕМ БОТА ПЕРЕД РОЗЫГРЫШЕМ
            if campaign.bot_is_running:
                self.stdout.write("Останавливаем бота перед розыгрышем...")
                campaign.bot_is_running = False
                campaign.save()
            
            if participants.count() < winners_count:
                self.stdout.write("ОШИБКА: Недостаточно участников для розыгрыша!")
                return
            
            if campaign.winners:
                self.stdout.write("ОШИБКА: Розыгрыш уже проводился для этого мероприятия!")
                return
            
            winners = random.sample(list(participants), winners_count)
            
            winners_data = []
            for i, winner in enumerate(winners, 1):
                winner_data = {
                    'place': i,
                    'name': winner.first_name,
                    'phone': winner.phone,
                    'telegram_id': winner.telegram_id,
                    'username': winner.username or 'Не указан'
                }
                winners_data.append(winner_data)
                self.stdout.write(f"{i}. {winner.first_name} - {winner.phone} (@{winner.username})")
            
            # Обновляем кампанию
            campaign.winners = winners_data
            campaign.raffle_date = timezone.now()
            campaign.status = 'raffled'
            campaign.bot_is_running = False  # 🔴 Гарантируем что бот выключен
            campaign.save()
            
            self.stdout.write(f"РОЗЫГРЫШ завершен! Победители сохранены в базу.")
            
        except Campaign.DoesNotExist:
            self.stdout.write(f"ОШИБКА: Мероприятие '{campaign_slug}' не найдено")
        except Exception as e:
            self.stdout.write(f"ОШИБКА: {e}")