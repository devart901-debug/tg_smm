from django.db import models
from django.utils import timezone
import os
from dotenv import load_dotenv
load_dotenv()


class Campaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('active', 'Активно'),
        ('finished', 'Завершено'), 
        ('raffled', 'Розыгрыш проведен'),
    ]
    
    name = models.CharField('Название мероприятия', max_length=200)
    slug = models.SlugField('URL идентификатор', unique=True)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default='draft')
    channel_usernames = models.CharField('Username канала', max_length=100, default='@test_channel')
    
    first_message = models.TextField(
        'Первое сообщение бота', 
        default='Добро пожаловать на мероприятие! Нажмите кнопку ниже чтобы участвовать в розыгрыше.'
    )
    welcome_text = models.TextField('Текст приветствия', default='Добро пожаловать!')
    button_text = models.CharField('Текст кнопки', max_length=50, default='🎯 Участвовать в розыгрыше')
    
    # Новое поле для статуса бота
    bot_is_running = models.BooleanField('Бот запущен', default=False)


    
    theme_color = models.CharField('Цвет темы', max_length=7, default='#FF6B35')
    
     # НОВЫЕ ПОЛЯ:
    conditions_text = models.TextField(
        'Текст условий акции', 
        default='Для участия в розыгрыше необходимо:\n• Быть подписанным на наш канал\n• Заполнить контактные данные\n• Согласиться на обработку персональных данных'
    )
    prizes_text = models.TextField(
        'Текст призов', 
        default='🏆 Главные призы:\n• Профессиональный графический планшет\n• Набор дизайнерских инструментов\n• Годовой курс по дизайну'
    )
    share_phone_button = models.CharField(
        'Текст кнопки "Поделиться номером"', 
        max_length=50, 
        default='📱 Поделиться номером'
    )
    conditions_button = models.CharField(
        'Текст кнопки "Проверить подписку"', 
        max_length=50, 
        default='✅ Проверить подписку'
    )
    prizes_button = models.CharField(
        'Текст кнопки "Призы"', 
        max_length=50, 
        default='🎁 Посмотреть призы'
    )

     # Новые поля для розыгрыша
    winners_count = models.IntegerField('Количество победителей', default=1)
    winners = models.JSONField('Победители', default=list, blank=True)  # Храним список победителей
    raffle_date = models.DateTimeField('Дата розыгрыша', null=True, blank=True)
    
    # Множественные каналы для подписки
    channel_usernames = models.TextField(
        'Usernames каналов (через запятую)', 
        default='@test_channel',
        help_text='Укажите usernames каналов через запятую, например: @channel1, @channel2'
    )

    registration_stage = models.CharField(
        'Стадия регистрации', 
        max_length=20, 
        default='start',
        choices=[
            ('start', 'Начало'),
            ('name', 'Ввод имени'),
            ('phone', 'Ввод телефона'),
            ('subscription', 'Проверка подписки'),
            ('completed', 'Завершено')
        ]
    )

    def start_bot(self):
        """Запуск бота через вебхук"""
        try:
            # Устанавливаем флаг запуска
            self.bot_is_running = True
            self.save()
            
            # Настраиваем вебхук в Telegram
            bot_token = os.getenv("BOT_TOKEN")
            webhook_url = os.getenv("WEBHOOK_URL")
            
            import requests
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/setWebhook",
                data={'url': webhook_url}
            )
            
            if response.status_code == 200:
                print(f"✅ Вебхук настроен для бота")
                return True
            else:
                print(f"❌ Ошибка настройки вебхука: {response.text}")
                self.bot_is_running = False
                self.save()
                return False
                
        except Exception as e:
            print(f"❌ Ошибка запуска бота: {e}")
            self.bot_is_running = False
            self.save()
            return False

    def stop_bot(self):
        """Остановка бота - отключаем вебхук"""
        try:
            self.bot_is_running = False
            self.save()
            
            # Отключаем вебхук в Telegram
            bot_token = os.getenv("BOT_TOKEN")
            
            import requests
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
            )
            
            print(f"✅ Вебхук отключен")
            return True
        except Exception as e:
            print(f"❌ Ошибка остановки бота: {e}")
            return False

    def bot_status(self):
        """Статус бота"""
        if self.bot_is_running:
            return "🟢 Запущен (вебхук)"
        else:
            return "🔴 Остановлен"

    class Meta:
        verbose_name = 'Мероприятие'
        verbose_name_plural = 'Мероприятия'

    def __str__(self):
        return self.name
    
    def is_active(self):
        return self.status == 'active'
    
    def participants_count(self):
        return self.participants.count()
    participants_count.short_description = 'Участников'

class Participant(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='participants', verbose_name='Мероприятие')
    telegram_id = models.BigIntegerField('ID пользователя Telegram')
    username = models.CharField('Username', max_length=100, blank=True)
    first_name = models.CharField('Имя', max_length=100)
    phone = models.CharField('Телефон', max_length=20)
    is_subscribed = models.BooleanField('Подписан на канал', default=False)
    created_at = models.DateTimeField('Дата регистрации', auto_now_add=True)
    
    # Добавляем поле регистрации
    registration_stage = models.CharField(
        'Стадия регистрации',
        max_length=20,
        default='start',
        choices=[
            ('start', 'Начало'),
            ('name', 'Ввод имени'),
            ('phone', 'Ввод телефона'),
            ('subscription', 'Проверка подписки'),
            ('completed', 'Завершено')
        ]
    )
    
    class Meta:
        verbose_name = 'Участник'
        verbose_name_plural = 'Участники'
        unique_together = ['campaign', 'telegram_id']

    def __str__(self):
        return f"{self.first_name} - {self.campaign.name}"