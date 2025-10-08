# campaigns/telegram_handlers.py
import json
import re
import os
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Campaign, Participant
from .utils import check_user_subscription

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ==============================
# WEBHOOK
# ==============================
@csrf_exempt
@require_POST
def telegram_webhook(request):
    try:
        update = json.loads(request.body)
        if 'message' in update:
            handle_message(update['message'])
        elif 'callback_query' in update:
            handle_callback(update['callback_query'])
    except Exception as e:
        print(f"Webhook error: {e}")
    return JsonResponse({'ok': True})

# ==============================
# MESSAGE HANDLER
# ==============================
def handle_message(message):
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    text = message.get('text', '')
    first_name = message['from'].get('first_name', '')
    username = message['from'].get('username', '')

    campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
    if not campaign:
        return

    # Контакт
    if 'contact' in message:
        phone = message['contact'].get('phone_number', '')
        handle_contact(chat_id, user_id, phone, first_name, username, campaign)
        return

    # /start
    if text == '/start':
        handle_start(chat_id, user_id, first_name, username, campaign)
        return

    # Обработка обычного текста
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_message(chat_id, "❌ Пожалуйста, нажмите /start для начала регистрации")
        return

    stage = participant.registration_stage
    if stage == 'name':
        handle_name_stage(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone_stage(chat_id, participant, text, campaign)
    elif stage == 'subscription':
        send_message(
            chat_id,
            "📋 Пожалуйста, используйте кнопку 'Проверить подписку', чтобы продолжить"
        )

# ==============================
# CALLBACK HANDLER
# ==============================
def handle_callback(callback):
    data = callback['data']
    user_id = callback['from']['id']
    chat_id = callback['message']['chat']['id']

    campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
    if not campaign:
        send_message(chat_id, "❌ Произошла ошибка, попробуйте позже")
        return

    participant = Participant.objects.filter(telegram_id=user_id, campaign=campaign).first()
    if not participant:
        send_message(chat_id, "❌ Сначала нажмите /start для начала регистрации")
        return

    if data == 'check_subscription':
        is_subscribed, failed_channel = check_user_subscription(BOT_TOKEN, user_id, campaign.channel_usernames)
        if is_subscribed:
            participant.is_subscribed = True
            participant.registration_stage = 'completed'
            participant.save()
            send_message(
                chat_id,
                f"🎉 Регистрация завершена!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}",
                reply_markup={'inline_keyboard': [[{'text': campaign.button_text or '🎯 Участвовать', 'callback_data': 'participate'}]]}
            )
        else:
            # Если не подписан, присылаем условия + кнопку
            send_message(
                chat_id,
                f"❌ Вы не подписаны на канал {failed_channel}\n{campaign.conditions_text or '📋 Ознакомьтесь с условиями акции'}",
                reply_markup={'inline_keyboard': [[{'text': '✅ Проверить подписку', 'callback_data': 'check_subscription'}]]}
            )


# ==============================
# STAGES
# ==============================
def handle_start(chat_id, user_id, first_name, username, campaign):
    # Проверяем есть ли участник
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if participant:
        if participant.registration_stage == 'completed':
            send_message(
                chat_id,
                f"Вы уже зарегистрированы!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}",
                reply_markup={'inline_keyboard': [[{'text': campaign.button_text or '🎯 Участвовать', 'callback_data': 'participate'}]]}
            )
        elif participant.registration_stage == 'subscription':
            ask_subscription(chat_id, campaign)
        else:
            send_message(chat_id, "❌ Вы начали регистрацию ранее. Пожалуйста, продолжите с того места, где остановились.")
        return

    # Если участника нет — создаем нового
    send_message(chat_id, campaign.first_message or "Добро пожаловать! Нажмите кнопку ниже, чтобы участвовать.")
    participant = Participant.objects.create(
        campaign=campaign,
        telegram_id=user_id,
        username=username,
        first_name=first_name,
        registration_stage='name'
    )
    ask_name(chat_id)


def handle_name_stage(chat_id, participant, text):
    if not text.strip():
        send_message(chat_id, "Пожалуйста, введите ваше имя:")
        return
    participant.first_name = text.strip()
    participant.registration_stage = 'phone'
    participant.save()
    ask_phone(chat_id, participant)

def handle_phone_stage(chat_id, participant, text, campaign):
    if not text.strip():
        send_message(chat_id, "Пожалуйста, введите ваш номер:")
        return
    phone = re.sub(r'[^\d+]', '', text.strip())
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone
    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()
    ask_subscription(chat_id, campaign)

def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    participant = Participant.objects.filter(telegram_id=user_id, campaign=campaign).first()
    if not participant:
        send_message(chat_id, "❌ Сначала нажмите /start")
        return
    phone = re.sub(r'[^\d+]', '', phone)
    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()
    ask_subscription(chat_id, campaign)

# ==============================
# ASK FUNCTIONS
# ==============================
def ask_name(chat_id):
    send_message(chat_id, "📝 Как вас зовут?\nВведите имя и фамилию:")

def ask_phone(chat_id, participant):
    keyboard = {
        'keyboard': [[{'text': participant.campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
        'resize_keyboard': True,
        'one_time_keyboard': True
    }
    send_message(chat_id, f"Приятно познакомиться, {participant.first_name}! Введите номер или нажмите кнопку:", reply_markup=keyboard)

def ask_subscription(chat_id, campaign):
    # Текст условий и кнопка проверки подписки
    text = campaign.conditions_text or "📋 Текст условий акции"
    keyboard = {
        'inline_keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку', 'callback_data': 'check_subscription'}]]
    }
    send_message(chat_id, text, reply_markup=keyboard)

# ==============================
# SEND MESSAGE
# ==============================
def send_message(chat_id, text, reply_markup=None):
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', data=data)
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")
