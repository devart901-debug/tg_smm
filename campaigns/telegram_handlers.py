import json
import requests
import re
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Campaign, Participant
import os
from dotenv import load_dotenv
load_dotenv()


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Обработка вебхука Telegram"""
    try:
        active_campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
        if not active_campaign:
            print("❌ Нет активных кампаний с запущенным ботом")
            return JsonResponse({'ok': True})
        
        update = json.loads(request.body)
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', '')
            username = message['from'].get('username', '')

            # Если пользователь прислал контакт
            if 'contact' in message:
                phone = message['contact'].get('phone_number', '')
                handle_contact(chat_id, user_id, phone, first_name, username, active_campaign)
                return JsonResponse({'ok': True})

            # Логика команд
            if text == '/start':
                handle_start(chat_id, user_id, first_name, username, active_campaign)
            else:
                handle_user_message(chat_id, user_id, text, first_name, username, active_campaign)

    except Exception as e:
        print(f"❌ Error in webhook: {e}")

    return JsonResponse({'ok': True})


def handle_start(chat_id, user_id, first_name, username, campaign):
    """Начало общения с ботом"""
    try:
        # Отправляем приветственное сообщение
        send_telegram_message(
            chat_id,
            campaign.first_message or "Добро пожаловать на мероприятие!"
        )
        # Создаем или обнуляем регистрацию
        Participant.objects.filter(
            telegram_id=user_id,
            registration_stage__in=['name', 'phone', 'subscription']
        ).delete()
        participant = Participant.objects.create(
            campaign=campaign,
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            registration_stage='name'
        )
        ask_name(chat_id, participant)
    except Exception as e:
        print(f"❌ Error in handle_start: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")


def ask_name(chat_id, participant):
    """Запрос имени"""
    send_telegram_message(
        chat_id,
        "📝 *Как вас зовут?*\n\nВведите ваше имя и фамилию:",
        {'remove_keyboard': True},
        parse_mode='Markdown'
    )


def handle_user_message(chat_id, user_id, text, first_name, username, campaign):
    """Обработка сообщений по стадиям регистрации"""
    participant = Participant.objects.filter(
        telegram_id=user_id,
        registration_stage__in=['name', 'phone', 'subscription']
    ).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Пожалуйста, нажмите /start для начала регистрации")
        return

    stage = participant.registration_stage
    if stage == 'name':
        handle_name_stage(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone_stage(chat_id, campaign, participant, text)
    elif stage == 'subscription':
        handle_subscription_stage(chat_id, user_id, campaign, participant)


def handle_name_stage(chat_id, participant, text):
    """Сохраняем имя и запрашиваем телефон"""
    if not text.strip():
        send_telegram_message(chat_id, "Пожалуйста, введите ваше имя:")
        return

    participant.first_name = text.strip()
    participant.registration_stage = 'phone'
    participant.save()
    ask_phone(chat_id, participant)


def ask_phone(chat_id, participant):
    """Запрос телефона"""
    keyboard = {
        'keyboard': [[{'text': participant.campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
        'resize_keyboard': True
    }
    send_telegram_message(
        chat_id,
        f"Приятно познакомиться, {participant.first_name}! 📱 *Ваш номер телефона*\n\nВведите номер или нажмите кнопку:",
        keyboard,
        parse_mode='Markdown'
    )


def handle_phone_stage(chat_id, campaign, participant, text):
    """Сохраняем телефон и предлагаем подписку"""
    if not text.strip():
        send_telegram_message(chat_id, "Пожалуйста, введите ваш телефон:")
        return

    # Приводим номер к формату +7...
    phone = re.sub(r'[^\d+]', '', text.strip())
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()

    ask_for_subscription(chat_id, campaign, participant)



def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    """Обработка контакта"""
    participant = Participant.objects.filter(
        telegram_id=user_id,
        registration_stage='phone'
    ).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Сначала введите ваше имя")
        return

    participant.phone = re.sub(r'[^\d+]', '', phone)
    participant.registration_stage = 'subscription'
    participant.save()
    ask_for_subscription(chat_id, campaign, participant)


def ask_for_subscription(chat_id, campaign, participant):
    """Запрос подписки на каналы с кнопкой"""
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    channels_text = "\n".join([f"• {ch}" for ch in channels])
    keyboard = {
        'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]],
        'resize_keyboard': True
    }
    send_telegram_message(
        chat_id,
        f"📢 *Подпишитесь на наши каналы*\n\n{channels_text}\n\nПосле подписки нажмите кнопку:",
        keyboard,
        parse_mode='Markdown'
    )


def handle_subscription_stage(chat_id, user_id, campaign, participant):
    """Проверка подписки и завершение регистрации"""
    is_subscribed, failed_channels = check_user_subscription(user_id, campaign)
    if is_subscribed:
        participant.is_subscribed = True
        participant.registration_stage = 'completed'
        participant.save()
        keyboard = {
            'keyboard': [[{'text': campaign.button_text or '🎯 Участвовать'}]],
            'resize_keyboard': True
        }
        send_telegram_message(
            chat_id,
            f"🎉 *Регистрация завершена!*\n\n✅ Вы успешно зарегистрированы!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}",
            keyboard,
            parse_mode='Markdown'
        )
    else:
        failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
        keyboard = {
            'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]],
            'resize_keyboard': True
        }
        send_telegram_message(
            chat_id,
            f"❌ *Вы не подписаны на все каналы!*\n\nНе подписаны:\n{failed_text}\n\nПожалуйста, подпишитесь и нажмите кнопку снова:",
            keyboard,
            parse_mode='Markdown'
        )


def check_user_subscription(user_id, campaign):
    """Проверка подписки пользователя на каналы"""
    bot_token = os.getenv("BOT_TOKEN")
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    failed_channels = []
    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        try:
            response = requests.get(url, params={'chat_id': channel, 'user_id': user_id}, timeout=10)
            data = response.json()
            if not data.get('ok') or data['result']['status'] not in ['member', 'administrator', 'creator']:
                failed_channels.append(channel)
        except Exception as e:
            print(f"❌ Ошибка проверки подписки на {channel}: {e}")
            failed_channels.append(channel)
    return len(failed_channels) == 0, failed_channels


def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    bot_token = os.getenv("BOT_TOKEN")
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        data['parse_mode'] = parse_mode
    try:
        requests.post(f'https://api.telegram.org/bot{bot_token}/sendMessage', data=data)
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
