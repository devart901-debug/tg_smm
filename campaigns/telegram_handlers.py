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
    """Главная точка входа вебхука Telegram"""
    try:
        campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
        if not campaign:
            print("❌ Нет активных кампаний с запущенным ботом")
            return JsonResponse({'ok': True})

        update = json.loads(request.body)
        if 'message' not in update:
            return JsonResponse({'ok': True})

        message = update['message']
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        first_name = message['from'].get('first_name', '')
        username = message['from'].get('username', '')
        text = message.get('text', '')

        # Обработка контакта
        if 'contact' in message:
            phone = message['contact'].get('phone_number', '')
            handle_phone(chat_id, user_id, phone, first_name, username, campaign)
            return JsonResponse({'ok': True})

        # /start
        if text == '/start':
            handle_start(chat_id, user_id, first_name, username, campaign)
            return JsonResponse({'ok': True})

        # Обработка текста
        handle_text(chat_id, user_id, text, first_name, username, campaign)

    except Exception as e:
        print(f"❌ Error in webhook: {e}")

    return JsonResponse({'ok': True})


def handle_start(chat_id, user_id, first_name, username, campaign):
    """Начало общения с ботом"""
    try:
        # Приветственное сообщение
        send_telegram_message(chat_id, campaign.first_message or "Добро пожаловать!")

        # Удаляем старые незавершенные регистрации
        Participant.objects.filter(
            telegram_id=user_id,
            campaign=campaign,
            registration_stage__in=['name', 'phone', 'subscription']
        ).delete()

        # Создаем нового участника
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
    send_telegram_message(
        chat_id,
        "📝 *Как вас зовут?*\nВведите ваше имя и фамилию:",
        {'remove_keyboard': True},
        parse_mode='Markdown'
    )


def handle_text(chat_id, user_id, text, first_name, username, campaign):
    """Обработка текста по стадиям"""
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Пожалуйста, нажмите /start для начала регистрации")
        return

    stage = participant.registration_stage

    if stage == 'name':
        handle_name(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone(chat_id, user_id, text, first_name, username, campaign)
    elif stage == 'subscription':
        if text == (campaign.conditions_button or '✅ Проверить подписку'):
            handle_subscription(chat_id, user_id, campaign, participant)
        else:
            send_telegram_message(
                chat_id,
                f"❌ Сначала подпишитесь на каналы и нажмите кнопку '{campaign.conditions_button or '✅ Проверить подписку'}'"
            )


def handle_name(chat_id, participant, text):
    if not text.strip():
        send_telegram_message(chat_id, "Пожалуйста, введите ваше имя:")
        return

    participant.first_name = text.strip()
    participant.registration_stage = 'phone'
    participant.save()
    ask_phone(chat_id, participant)


def ask_phone(chat_id, participant):
    keyboard = {
        'keyboard': [[{'text': participant.campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
        'resize_keyboard': True
    }
    send_telegram_message(
        chat_id,
        f"Приятно познакомиться, {participant.first_name}! 📱 Введите ваш номер телефона или нажмите кнопку:",
        keyboard,
        parse_mode='Markdown'
    )


def handle_phone(chat_id, user_id, phone_text, first_name, username, campaign):
    """Сохраняем телефон и идем на подписку"""
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Сначала нажмите /start")
        return

    # Нормализация номера
    phone = re.sub(r'[^\d+]', '', phone_text.strip())
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()
    ask_subscription(chat_id, campaign, participant)


def ask_subscription(chat_id, campaign, participant):
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    channels_text = "\n".join([f"• {ch}" for ch in channels])
    keyboard = {
        'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]],
        'resize_keyboard': True
    }
    send_telegram_message(
        chat_id,
        f"📢 *Подпишитесь на наши каналы*\n\n{channels_text}\nПосле подписки нажмите кнопку:",
        keyboard,
        parse_mode='Markdown'
    )


def handle_subscription(chat_id, user_id, campaign, participant):
    """Проверка подписки и завершение регистрации"""
    subscribed, failed_channels = check_subscription(user_id, campaign)
    if subscribed:
        participant.is_subscribed = True
        participant.registration_stage = 'completed'
        participant.save()
        keyboard = {'keyboard': [[{'text': campaign.button_text or '🎯 Участвовать'}]], 'resize_keyboard': True}
        send_telegram_message(
            chat_id,
            f"🎉 *Регистрация завершена!*\n✅ Вы успешно зарегистрированы!\n👤 {participant.first_name}\n📞 {participant.phone}",
            keyboard,
            parse_mode='Markdown'
        )
    else:
        failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
        keyboard = {'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]], 'resize_keyboard': True}
        send_telegram_message(
            chat_id,
            f"❌ *Вы не подписаны на все каналы!*\nНе подписаны:\n{failed_text}\nПожалуйста, подпишитесь и нажмите кнопку снова:",
            keyboard,
            parse_mode='Markdown'
        )


def check_subscription(user_id, campaign):
    """Проверка подписки на каналы"""
    bot_token = os.getenv("BOT_TOKEN")
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    failed = []
    for ch in channels:
        if not ch.startswith('@'):
            ch = '@' + ch
        try:
            res = requests.get(f'https://api.telegram.org/bot{bot_token}/getChatMember',
                               params={'chat_id': ch, 'user_id': user_id}, timeout=10)
            data = res.json()
            if not data.get('ok') or data['result']['status'] not in ['member', 'administrator', 'creator']:
                failed.append(ch)
        except Exception as e:
            print(f"❌ Ошибка проверки подписки на {ch}: {e}")
            failed.append(ch)
    return len(failed) == 0, failed


def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Отправка сообщения через Telegram API"""
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
