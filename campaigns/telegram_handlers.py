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
    """Обработка вебхука Telegram (сообщения и callback-и)"""
    try:
        active_campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
        if not active_campaign:
            return JsonResponse({'ok': True})

        update = json.loads(request.body)

        # 🔹 1. Callback от inline кнопки
        if 'callback_query' in update:
            callback = update['callback_query']
            data = callback.get('data')
            chat_id = callback['message']['chat']['id']
            user_id = callback['from']['id']
            message_id = callback['message']['message_id']  # 🔹 ДОБАВЛЯЕМ
            callback_query_id = callback['id']  # 🔹 ДОБАВЛЯЕМ

            participant = Participant.objects.filter(campaign=active_campaign, telegram_id=user_id).first()
            if not participant:
                send_telegram_message(chat_id, "❌ Сначала нажмите /start")
                answer_callback_query(callback_query_id, "❌ Сначала нажмите /start")
                return JsonResponse({'ok': True})

            if data == 'check_subscription':
                # 🔹 ПЕРЕДАЕМ ДОПОЛНИТЕЛЬНЫЕ ПАРАМЕТРЫ
                handle_subscription_stage(chat_id, user_id, active_campaign, participant, message_id, callback_query_id)

            return JsonResponse({'ok': True})

        # 🔹 2. Обычные сообщения
        if 'message' not in update:
            return JsonResponse({'ok': True})

        message = update['message']
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        first_name = message['from'].get('first_name', '')
        username = message['from'].get('username', '')
        text = message.get('text', '')

        if 'contact' in message:
            phone = message['contact'].get('phone_number', '')
            handle_contact(chat_id, user_id, phone, first_name, username, active_campaign)
            return JsonResponse({'ok': True})

        if text == '/start':
            handle_start(chat_id, user_id, first_name, username, active_campaign)
            return JsonResponse({'ok': True})

        handle_user_message(chat_id, user_id, text, first_name, username, active_campaign)

    except Exception as e:
        print(f"❌ Error in webhook: {e}")

    return JsonResponse({'ok': True})


def handle_start(chat_id, user_id, first_name, username, campaign):
    """Начало общения с ботом"""
    try:
        # Приветственное сообщение
        send_telegram_message(chat_id, campaign.first_message or "Добро пожаловать на мероприятие!")

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
    """Запрос имени"""
    send_telegram_message(
        chat_id,
        "📝 *Как вас зовут?*\n\nВведите ваше имя и фамилию:",
        {'remove_keyboard': True},
        parse_mode='Markdown'
    )


def handle_user_message(chat_id, user_id, text, first_name, username, campaign):
    """Обработка сообщений по стадиям регистрации"""
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Пожалуйста, нажмите /start для начала регистрации")
        return

    stage = participant.registration_stage

    if stage == 'name':
        handle_name_stage(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone_stage(chat_id, campaign, participant, text)
    elif stage == 'subscription':
        if text == (campaign.conditions_button or '✅ Проверить подписку'):
            # 🔹 ПЕРЕДАЕМ None для message_id и callback_query_id при обычном сообщении
            handle_subscription_stage(chat_id, user_id, campaign, participant, None, None)
        else:
            send_telegram_message(
                chat_id,
                f"❌ Сначала подпишитесь на каналы и нажмите кнопку '{campaign.conditions_button or '✅ Проверить подписку'}'"
            )


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
    """Сохраняем телефон и отправляем условия акции с inline кнопкой"""
    if not text.strip():
        send_telegram_message(chat_id, "Пожалуйста, введите ваш телефон:")
        return

    # Приведение к формату +7...
    phone = re.sub(r'[^\d+]', '', text.strip())
    if phone.startswith('8'):
        phone = '+7' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()

    # 🔹 Убираем клавиатуру
    remove_keyboard = {"remove_keyboard": True}
    send_telegram_message(chat_id, "Спасибо! Теперь ознакомьтесь с условиями розыгрыша:", reply_markup=remove_keyboard)

    # 🔹 Ждем немного перед отправкой условий
    import time
    time.sleep(0.5)
    
    # 🔹 Отправляем условия с inline-кнопкой
    send_conditions_with_inline_button(chat_id, campaign)


def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    """Обработка контакта Telegram"""
    participant = Participant.objects.filter(campaign=campaign, telegram_id=user_id).first()
    if not participant:
        send_telegram_message(chat_id, "❌ Сначала нажмите /start")
        return

    participant.phone = re.sub(r'[^\d+]', '', phone)
    participant.registration_stage = 'subscription'
    participant.save()

    # 🔹 Убираем клавиатуру
    remove_keyboard = {"remove_keyboard": True}
    send_telegram_message(chat_id, "Спасибо! Теперь ознакомьтесь с условиями розыгрыша:", reply_markup=remove_keyboard)

    # 🔹 Отправляем условия акции с inline кнопкой
    send_conditions_with_inline_button(chat_id, campaign)


def send_conditions_with_inline_button(chat_id, campaign):
    """Отправляем текст условий акции и inline кнопку"""
    # Проверяем, есть ли текст условий
    conditions_text = campaign.conditions_text
    if not conditions_text or conditions_text.strip() == "":
        conditions_text = "📋 *Условия участия в розыгрыше:*\n\nПодпишитесь на указанные каналы для участия."
    
    inline_keyboard = {
        "inline_keyboard": [
            [{"text": campaign.conditions_button or "✅ Проверить подписку", "callback_data": "check_subscription"}]
        ]
    }
    
    send_telegram_message(
        chat_id,
        conditions_text,
        reply_markup=inline_keyboard,
        parse_mode='Markdown'
    )


def handle_subscription_stage(chat_id, user_id, campaign, participant, message_id=None, callback_query_id=None):
    """Проверка подписки и завершение регистрации"""
    is_subscribed, failed_channels = check_user_subscription(user_id, campaign)

    if is_subscribed:
        participant.is_subscribed = True
        participant.registration_stage = 'completed'
        participant.save()
        
        # 🔹 Если это callback, отвечаем на него
        if callback_query_id:
            answer_callback_query(callback_query_id, "🎉 Регистрация завершена!")
        
        send_telegram_message(
            chat_id,
            f"🎉 *Регистрация завершена!*\n\n✅ Вы успешно зарегистрированы!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}",
            parse_mode='Markdown'
        )
        
        # 🔹 Если есть message_id, удаляем старое сообщение с кнопкой
        if message_id:
            delete_message(chat_id, message_id)
            
    else:
        failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
        inline_keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Проверить подписку", "callback_data": "check_subscription"}]
            ]
        }
        
        # 🔹 ОТВЕЧАЕМ НА CALLBACK, чтобы убрать "часики" на кнопке
        if callback_query_id:
            answer_callback_query(callback_query_id, "❌ Вы не подписаны на все каналы")
        
        # 🔹 Если есть message_id, РЕДАКТИРУЕМ существующее сообщение
        if message_id:
            edit_message_with_inline_button(
                chat_id, 
                message_id, 
                f"❌ *Вы не подписаны на все каналы!*\n\nНе подписаны:\n{failed_text}\n\nПожалуйста, подпишитесь и нажмите кнопку снова:",
                inline_keyboard,
                parse_mode='Markdown'
            )
        else:
            # 🔹 Если нет message_id (например, при обычном сообщении), отправляем новое
            send_telegram_message(
                chat_id,
                f"❌ *Вы не подписаны на все каналы!*\n\nНе подписаны:\n{failed_text}\n\nПожалуйста, подпишитесь и нажмите кнопку снова:",
                reply_markup=inline_keyboard,
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
            
            # Улучшенная проверка статуса подписки
            if data.get('ok'):
                status = data['result']['status']
                # Проверяем, что пользователь действительно подписан
                if status in ['member', 'administrator', 'creator']:
                    continue  # Подписан - переходим к следующему каналу
                
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
        response = requests.post(f'https://api.telegram.org/bot{bot_token}/sendMessage', data=data)
        if response.status_code != 200:
            print(f"⚠️ Ошибка Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")



def answer_callback_query(callback_query_id, text):
    """Отвечаем на callback query (убирает часики)"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {
        'callback_query_id': callback_query_id,
        'text': text,
        'show_alert': False
    }
    try:
        requests.post(f'https://api.telegram.org/bot{bot_token}/answerCallbackQuery', data=data)
    except Exception as e:
        print(f"❌ Ошибка ответа на callback: {e}")


def edit_message_with_inline_button(chat_id, message_id, text, reply_markup=None, parse_mode=None):
    """Редактируем сообщение с inline кнопкой"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text
    }
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        data['parse_mode'] = parse_mode
    
    try:
        requests.post(f'https://api.telegram.org/bot{bot_token}/editMessageText', data=data)
    except Exception as e:
        print(f"❌ Ошибка редактирования сообщения: {e}")


def delete_message(chat_id, message_id):
    """Удаляем сообщение"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {
        'chat_id': chat_id,
        'message_id': message_id
    }
    try:
        requests.post(f'https://api.telegram.org/bot{bot_token}/deleteMessage', data=data)
    except Exception as e:
        print(f"❌ Ошибка удаления сообщения: {e}")