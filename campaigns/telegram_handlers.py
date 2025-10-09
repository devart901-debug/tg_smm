import json
import requests
import re
import time
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
        print(f"📨 Получен update: {json.dumps(update, indent=2, ensure_ascii=False)}")  # Логирование

        # 🔹 1. Callback от inline кнопки
        if 'callback_query' in update:
            callback = update['callback_query']
            data = callback.get('data')
            chat_id = callback['message']['chat']['id']
            user_id = callback['from']['id']
            message_id = callback['message']['message_id']
            callback_query_id = callback['id']

            participant = Participant.objects.filter(campaign=active_campaign, telegram_id=user_id).first()
            if not participant:
                send_telegram_message(chat_id, "❌ Сначала нажмите /start")
                answer_callback_query(callback_query_id, "❌ Сначала нажмите /start")
                return JsonResponse({'ok': True})

            if data == 'check_subscription':
                # 🔹 ПЕРЕДАЕМ ДОПОЛНИТЕЛЬНЫЕ ПАРАМЕТРЫ
                handle_subscription_stage(chat_id, user_id, active_campaign, participant, message_id, callback_query_id)
            else:
                answer_callback_query(callback_query_id, "❌ Неизвестная команда")

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

        print(f"💬 Message from {user_id}: {text}")

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
        # 🔹 ПРОВЕРЯЕМ ЕСТЬ ЛИ УЖЕ ЗАВЕРШЕННАЯ РЕГИСТРАЦИЯ
        existing_participant = Participant.objects.filter(
            campaign=campaign, 
            telegram_id=user_id,
            registration_stage='completed'
        ).first()
        
        if existing_participant:
            # 🔹 ЕСЛИ РЕГИСТРАЦИЯ УЖЕ ЗАВЕРШЕНА - ПОКАЗЫВАЕМ СТАТУС
            send_telegram_message(
                chat_id,
                f"🎉 *Вы уже зарегистрированы!*\n\n"
                f"✅ Ваша регистрация подтверждена\n"
                f"👤 Имя: {existing_participant.first_name}\n"
                f"📞 Телефон: {existing_participant.phone}\n\n"
                f"Ожидайте результатов розыгрыша!",
                parse_mode='Markdown'
            )
            return

        # 🔹 ПРОВЕРЯЕМ ЕСТЬ ЛИ НЕЗАВЕРШЕННАЯ РЕГИСТРАЦИЯ
        incomplete_participant = Participant.objects.filter(
            telegram_id=user_id,
            campaign=campaign,
            registration_stage__in=['name', 'phone', 'subscription']
        ).first()
        
        if incomplete_participant:
            # 🔹 ЕСЛИ ЕСТЬ НЕЗАВЕРШЕННАЯ РЕГИСТРАЦИЯ - ПРОДОЛЖАЕМ С ТЕКУЩЕЙ СТАДИИ
            stage = incomplete_participant.registration_stage
            if stage == 'name':
                ask_name(chat_id, incomplete_participant)
            elif stage == 'phone':
                ask_phone(chat_id, incomplete_participant)
            elif stage == 'subscription':
                send_conditions_with_inline_button(chat_id, campaign)
            return

        # 🔹 ЕСЛИ УЧАСТНИКА ВООБЩЕ НЕТ - НАЧИНАЕМ НОВУЮ РЕГИСТРАЦИЮ
        welcome_message = campaign.first_message or "Добро пожаловать на мероприятие!"
        send_telegram_message(chat_id, welcome_message)

        # Создаем нового участника
        participant = Participant.objects.create(
            campaign=campaign,
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            registration_stage='name'
        )

        # Ждем немного перед запросом имени
        time.sleep(0.5)
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

    # 🔹 ЕСЛИ РЕГИСТРАЦИЯ УЖЕ ЗАВЕРШЕНА - ПОКАЗЫВАЕМ СТАТУС
    if participant.registration_stage == 'completed':
        send_telegram_message(
            chat_id,
            f"🎉 *Вы уже зарегистрированы!*\n\n"
            f"✅ Ваша регистрация подтверждена\n"
            f"👤 Имя: {participant.first_name}\n"
            f"📞 Телефон: {participant.phone}\n\n"
            f"Ожидайте результатов розыгрыша!",
            parse_mode='Markdown'
        )
        return

    stage = participant.registration_stage
    print(f"🎯 Stage for user {user_id}: {stage}")

    if stage == 'name':
        handle_name_stage(chat_id, participant, text)
    elif stage == 'phone':
        handle_phone_stage(chat_id, campaign, participant, text)
    elif stage == 'subscription':
        if text == (campaign.conditions_button or '✅ Проверить подписку'):
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
    
    # Ждем немного перед запросом телефона
    time.sleep(0.5)
    ask_phone(chat_id, participant)


def ask_phone(chat_id, participant):
    """Запрос телефона"""
    keyboard = {
        'keyboard': [[{'text': participant.campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
        'resize_keyboard': True,
        'one_time_keyboard': True
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

    # Проверяем минимальную длину номера
    if len(phone) < 11:
        send_telegram_message(chat_id, "❌ Номер телефона слишком короткий. Пожалуйста, введите корректный номер:")
        return

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()

    # 🔹 Убираем клавиатуру
    remove_keyboard = {"remove_keyboard": True}
    send_telegram_message(chat_id, "Спасибо! Теперь ознакомьтесь с условиями розыгрыша:", reply_markup=remove_keyboard)

    # 🔹 Ждем немного перед отправкой условий
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

    # 🔹 Ждем немного перед отправкой условий
    time.sleep(0.5)
    
    # 🔹 Отправляем условия акции с inline кнопкой
    send_conditions_with_inline_button(chat_id, campaign)


def send_conditions_with_inline_button(chat_id, campaign):
    """Отправляем текст условий акции и inline кнопку - УПРОЩЕННАЯ ВЕРСИЯ"""
    try:
        # Просто берем текст как есть, без форматирования
        conditions_text = campaign.conditions_text
        
        # Если нет текста, используем базовый
        if not conditions_text or conditions_text.strip() == "":
            conditions_text = "📋 Для участия в розыгрыше подпишитесь на указанные каналы и нажмите кнопку проверки подписки."
        
        # Текст кнопки
        button_text = campaign.conditions_button or "✅ Проверить подписку"
        
        inline_keyboard = {
            "inline_keyboard": [
                [{"text": button_text, "callback_data": "check_subscription"}]
            ]
        }
        
        print(f"📋 Sending conditions to {chat_id}")
        print(f"📝 Conditions text: {conditions_text}")
        
        # Отправляем БЕЗ Markdown форматирования
        send_telegram_message(
            chat_id,
            conditions_text,
            reply_markup=inline_keyboard,
            parse_mode=None  # Важно: без форматирования
        )
            
    except Exception as e:
        print(f"❌ Error in send_conditions_with_inline_button: {e}")
        # Фолбэк - минимальное сообщение
        send_telegram_message(
            chat_id,
            "📋 Для участия подпишитесь на каналы и нажмите кнопку проверки:",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "✅ Проверить подписку", "callback_data": "check_subscription"}]
                ]
            }
        )


def handle_subscription_stage(chat_id, user_id, campaign, participant, message_id=None, callback_query_id=None):
    """Проверка подписки и завершение регистрации"""
    try:
        print(f"🔍 Checking subscription for user {user_id}")
        is_subscribed, failed_channels = check_user_subscription(user_id, campaign)

        if is_subscribed:
            participant.is_subscribed = True
            participant.registration_stage = 'completed'
            participant.save()
            
            print(f"✅ User {user_id} successfully subscribed")
            
            # 🔹 Если это callback, отвечаем на него
            if callback_query_id:
                answer_callback_query(callback_query_id, "🎉 Регистрация завершена!")
            
            success_message = (
                f"🎉 *Регистрация завершена!*\n\n"
                f"✅ Вы успешно зарегистрированы!\n"
                f"👤 Имя: {participant.first_name}\n"
                f"📞 Телефон: {participant.phone}"
            )
            
            # 🔹 Если есть message_id, редактируем сообщение
            if message_id:
                edit_message_with_inline_button(
                    chat_id, message_id, success_message, 
                    None, 'Markdown'  # Убираем клавиатуру
                )
            else:
                send_telegram_message(chat_id, success_message, parse_mode='Markdown')
                
        else:
            print(f"❌ User {user_id} not subscribed to: {failed_channels}")
            failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
            inline_keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Проверить подписку", "callback_data": "check_subscription"}]
                ]
            }
            
            error_message = (
                f"❌ *Вы не подписаны на все каналы!*\n\n"
                f"Не подписаны:\n{failed_text}\n\n"
                f"Пожалуйста, подпишитесь и нажмите кнопку снова:"
            )
            
            # 🔹 ОТВЕЧАЕМ НА CALLBACK, чтобы убрать "часики" на кнопке
            if callback_query_id:
                answer_callback_query(callback_query_id, "❌ Вы не подписаны на все каналы")
            
            # 🔹 Если есть message_id, РЕДАКТИРУЕМ существующее сообщение
            if message_id:
                edit_message_with_inline_button(
                    chat_id, message_id, error_message,
                    inline_keyboard, 'Markdown'
                )
            else:
                send_telegram_message(
                    chat_id, error_message,
                    reply_markup=inline_keyboard, parse_mode='Markdown'
                )
            
    except Exception as e:
        print(f"❌ Error in handle_subscription_stage: {e}")
        if callback_query_id:
            answer_callback_query(callback_query_id, "❌ Произошла ошибка, попробуйте позже")


def check_user_subscription(user_id, campaign):
    """Проверка подписки пользователя на каналы"""
    bot_token = os.getenv("BOT_TOKEN")
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    failed_channels = []

    print(f"🔍 Checking {len(channels)} channels for user {user_id}")

    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel
            
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        try:
            print(f"  🔎 Checking channel: {channel}")
            response = requests.get(url, params={'chat_id': channel, 'user_id': user_id}, timeout=10)
            data = response.json()
            
            print(f"  📊 Response for {channel}: {data}")
            
            if data.get('ok'):
                status = data['result']['status']
                # Проверяем, что пользователь действительно подписан
                if status in ['member', 'administrator', 'creator']:
                    print(f"  ✅ Subscribed to {channel}")
                    continue  # Подписан - переходим к следующему каналу
                else:
                    print(f"  ❌ Not subscribed to {channel}, status: {status}")
            else:
                print(f"  ❌ API error for {channel}: {data}")
                
            failed_channels.append(channel)
            
        except Exception as e:
            print(f"❌ Ошибка проверки подписки на {channel}: {e}")
            failed_channels.append(channel)

    print(f"📊 Subscription result: {len(failed_channels)} failed channels")
    return len(failed_channels) == 0, failed_channels


def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Отправка сообщения в Telegram"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        data['parse_mode'] = parse_mode
    
    print(f"📤 Sending message to {chat_id}")
    print(f"📝 Text preview: {text[:100]}...")
    if reply_markup:
        print(f"🛜 Reply markup: {reply_markup}")
    
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage', 
            data=data, 
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"⚠️ Ошибка Telegram API: {response.status_code} - {response.text}")
            return response
            
        print(f"✅ Message sent successfully")
        return response
        
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return None


def answer_callback_query(callback_query_id, text):
    """Отвечаем на callback query (убирает часики)"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {
        'callback_query_id': callback_query_id,
        'text': text,
        'show_alert': False
    }
    try:
        print(f"🔔 Answering callback: {text}")
        response = requests.post(f'https://api.telegram.org/bot{bot_token}/answerCallbackQuery', data=data, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Ошибка ответа на callback: {response.text}")
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
    
    print(f"✏️ Editing message {message_id} in chat {chat_id}")
    
    try:
        response = requests.post(f'https://api.telegram.org/bot{bot_token}/editMessageText', data=data, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Ошибка редактирования сообщения: {response.status_code} - {response.text}")
            return False
        print(f"✅ Message edited successfully")
        return True
    except Exception as e:
        print(f"❌ Ошибка редактирования сообщения: {e}")
        return False


def delete_message(chat_id, message_id):
    """Удаляем сообщение"""
    bot_token = os.getenv("BOT_TOKEN")
    data = {
        'chat_id': chat_id,
        'message_id': message_id
    }
    try:
        print(f"🗑️ Deleting message {message_id} from chat {chat_id}")
        response = requests.post(f'https://api.telegram.org/bot{bot_token}/deleteMessage', data=data, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Ошибка удаления сообщения: {response.text}")
        else:
            print(f"✅ Message deleted successfully")
    except Exception as e:
        print(f"❌ Ошибка удаления сообщения: {e}")