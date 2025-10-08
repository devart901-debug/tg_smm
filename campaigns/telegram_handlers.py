import json
import re
import os
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Campaign, Participant
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ==============================
# WEBHOOK
# ==============================
@csrf_exempt
@require_POST
def telegram_webhook(request):
    try:
        update = json.loads(request.body)
        campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
        if not campaign:
            return JsonResponse({'ok': True})

        if 'callback_query' in update:
            handle_callback(update['callback_query'], campaign)
        elif 'message' in update:
            handle_message(update['message'], campaign)

    except Exception as e:
        print(f"❌ Webhook error: {e}")
    return JsonResponse({'ok': True})


# ==============================
# CALLBACK HANDLER
# ==============================
def handle_callback(callback, campaign):
    data = callback.get('data')
    chat_id = callback['message']['chat']['id']
    user_id = callback['from']['id']

    participant = Participant.objects.filter(telegram_id=user_id, campaign=campaign).first()
    if not participant:
        send_message(chat_id, "❌ Сначала нажмите /start")
        return

    if data == 'check_subscription':
        is_subscribed, failed_channels = check_subscription(user_id, campaign)
        if is_subscribed:
            participant.is_subscribed = True
            participant.registration_stage = 'completed'
            participant.save()
            send_message(
                chat_id,
                f"🎉 *Регистрация завершена!*\n\n✅ Вы успешно зарегистрированы!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}",
                parse_mode='Markdown'
            )
        else:
            failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
            inline_kb = {"inline_keyboard": [[{"text": "✅ Проверить подписку", "callback_data": "check_subscription"}]]}
            send_message(
                chat_id,
                f"❌ *Вы не подписаны на все каналы!*\n\nНе подписаны:\n{failed_text}\n\nПожалуйста, подпишитесь и нажмите кнопку снова:",
                reply_markup=inline_kb,
                parse_mode='Markdown'
            )


# ==============================
# MESSAGE HANDLER
# ==============================
def handle_message(message, campaign):
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    first_name = message['from'].get('first_name', '')
    username = message['from'].get('username', '')
    text = message.get('text', '')

    if 'contact' in message:
        phone = message['contact'].get('phone_number', '')
        handle_contact(chat_id, user_id, phone, first_name, username, campaign)
        return

    if text == '/start':
        handle_start(chat_id, user_id, first_name, username, campaign)
        return

    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_message(chat_id, "❌ Пожалуйста, нажмите /start для начала регистрации")
        return

    stage = participant.registration_stage
    if stage == 'name':
        handle_name_stage(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone_stage(chat_id, participant, text)
    elif stage == 'subscription':
        ask_subscription(chat_id, campaign)


# ==============================
# STAGES
# ==============================
def handle_start(chat_id, user_id, first_name, username, campaign):
    participant = Participant.objects.filter(telegram_id=user_id, campaign=campaign).first()
    if participant:
        if participant.registration_stage == 'completed':
            send_message(chat_id, f"Вы уже зарегистрированы!\n👤 {participant.first_name}\n📞 {participant.phone}")
        elif participant.registration_stage == 'subscription':
            ask_subscription(chat_id, campaign)
        else:
            send_message(chat_id, "❌ Вы начали регистрацию ранее. Продолжите с того места, где остановились.")
        return

    send_message(chat_id, campaign.first_message or "Добро пожаловать!")
    Participant.objects.filter(telegram_id=user_id, campaign=campaign, registration_stage__in=['name','phone','subscription']).delete()

    participant = Participant.objects.create(
        campaign=campaign,
        telegram_id=user_id,
        username=username,
        first_name=first_name,
        registration_stage='name'
    )
    ask_name(chat_id, participant)


def handle_name_stage(chat_id, participant, text):
    if not text.strip():
        send_message(chat_id, "Пожалуйста, введите имя:")
        return
    participant.first_name = text.strip()
    participant.registration_stage = 'phone'
    participant.save()
    ask_phone(chat_id, participant)


def handle_phone_stage(chat_id, participant, text):
    if not text.strip():
        send_message(chat_id, "Пожалуйста, введите телефон:")
        return

    phone = re.sub(r'[^\d+]', '', text.strip())
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()

    send_message(chat_id, "Спасибо! Теперь ознакомьтесь с условиями розыгрыша:")
    ask_subscription(chat_id, participant.campaign)


def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    participant = Participant.objects.filter(telegram_id=user_id, campaign=campaign).first()
    if not participant:
        send_message(chat_id, "❌ Сначала нажмите /start")
        return

    participant.phone = re.sub(r'[^\d+]', '', phone)
    participant.registration_stage = 'subscription'
    participant.save()

    send_message(chat_id, "Спасибо! Теперь ознакомьтесь с условиями розыгрыша:")
    ask_subscription(chat_id, campaign)


# ==============================
# ASK FUNCTIONS
# ==============================
def ask_name(chat_id, participant):
    send_message(chat_id, "📝 *Как вас зовут?*\nВведите имя и фамилию:", parse_mode='Markdown')


def ask_phone(chat_id, participant):
    keyboard = {'keyboard': [[{'text': participant.campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
                'resize_keyboard': True}
    send_message(chat_id, f"Приятно познакомиться, {participant.first_name}! Введите номер или нажмите кнопку:", reply_markup=keyboard)


def ask_subscription(chat_id, campaign):
    inline_kb = {"inline_keyboard": [[{"text": campaign.conditions_button or '✅ Проверить подписку', "callback_data": "check_subscription"}]]}
    text = (
        "Для участия в розыгрыше необходимо:\n"
        "• Быть подписанным на наш канал\n"
        "• Заполнить контактные данные\n"
        "• Согласиться на обработку персональных данных\n\n"
        f"{campaign.conditions_text or ''}"
    )
    send_message(chat_id, text, reply_markup=inline_kb)


# ==============================
# SUBSCRIPTION CHECK
# ==============================
def check_subscription(user_id, campaign):
    bot_token = BOT_TOKEN
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    failed_channels = []

    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel
        try:
            res = requests.get(f"https://api.telegram.org/bot{bot_token}/getChatMember",
                               params={'chat_id': channel, 'user_id': user_id}, timeout=10)
            data = res.json()
            if not data.get('ok') or data['result']['status'] not in ['member','administrator','creator']:
                failed_channels.append(channel)
        except Exception as e:
            print(f"❌ Ошибка проверки подписки {channel}: {e}")
            failed_channels.append(channel)

    return len(failed_channels) == 0, failed_channels


# ==============================
# SEND MESSAGE
# ==============================
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        data['parse_mode'] = parse_mode
    try:
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', data=data)
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")
