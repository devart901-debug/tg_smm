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
    """Вебхук с проверкой активности бота"""
    try:
        # ПРОВЕРЯЕМ ЕСТЬ ЛИ АКТИВНЫЕ КАМПАНИИ С ЗАПУЩЕННЫМ БОТОМ
        active_campaign = Campaign.objects.filter(
            status='active', 
            bot_is_running=True
        ).first()
        
        if not active_campaign:
            print("❌ Нет активных кампаний с запущенным ботом")
            return JsonResponse({'ok': True})  # Все равно возвращаем 200 для Telegram
        
        update = json.loads(request.body)
        print(f"🔄 Received update для кампании: {active_campaign.name}")
        
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            user_id = message['from']['id']
            first_name = message['from'].get('first_name', '')
            username = message['from'].get('username', '')
            
            print(f"💬 Сообщение от {first_name}: {text}")
            
            # Передаем active_campaign в обработчики
            if text == '/start':
                handle_start(chat_id, user_id, first_name, username, active_campaign)
            elif text == '🎯 Участвовать в розыгрыше':
                handle_participate(chat_id, user_id, first_name, username, active_campaign)
            else:
                handle_user_message(chat_id, user_id, text, first_name, username, active_campaign)
        
        # Обработка контакта (кнопка "Поделиться номером")
        elif 'message' in update and 'contact' in update['message']:
            message = update['message']
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            first_name = message['from'].get('first_name', '')
            username = message['from'].get('username', '')
            contact = message['contact']
            phone = contact.get('phone_number', '')
            
            print(f"📱 Получен контакт от {first_name}: {phone}")
            handle_contact(chat_id, user_id, phone, first_name, username, active_campaign)
                
    except Exception as e:
        print(f"❌ Error: {e}")
    
    return JsonResponse({'ok': True})

def handle_start(chat_id, user_id, first_name, username, campaign):
    """Обработка команды /start - главное меню"""
    try:
        # Приветственное сообщение с кнопкой
        keyboard = {
            'keyboard': [
                [{'text': '🎯 Участвовать в розыгрыше!'}]
            ],
            'resize_keyboard': True,
            'one_time_keyboard': False
        }
        
        send_telegram_message(
            chat_id, 
            campaign.first_message,
            keyboard
        )
        
        print(f"🔹 Пользователь {first_name} начал общение")
        
    except Exception as e:
        print(f"❌ Error in handle_start: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")

def handle_participate(chat_id, user_id, first_name, username, campaign):
    """Начало регистрации при нажатии кнопки участвовать"""
    try:
        # Удаляем предыдущие незавершенные регистрации
        Participant.objects.filter(
            telegram_id=user_id,
            registration_stage__in=['name', 'phone', 'subscription']
        ).delete()

        # Создаем новую регистрацию
        participant = Participant.objects.create(
            campaign=campaign,
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            registration_stage='name'
        )
        
        # Запрос имени
        send_telegram_message(
            chat_id, 
            "📝 *Как вас зовут?*\n\nВведите ваше имя и фамилию:",
            {'remove_keyboard': True},
            parse_mode='Markdown'
        )
        
        print(f"🔹 Начата регистрация для {first_name}")
        
    except Exception as e:
        print(f"❌ Error in handle_participate: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")

def handle_user_message(chat_id, user_id, text, first_name, username, campaign):
    """Обработка сообщений пользователя по стадиям"""
    try:
        participant = Participant.objects.filter(
            telegram_id=user_id,
            registration_stage__in=['name', 'phone', 'subscription']
        ).first()
        
        if not participant:
            # Если нет активной регистрации, показываем стартовое меню
            handle_start(chat_id, user_id, first_name, username, campaign)
            return
        
        print(f"🔹 Обработка для {first_name}, стадия: {participant.registration_stage}")
        
        if participant.registration_stage == 'name':
            handle_name_stage(chat_id, participant, text)
            
        elif participant.registration_stage == 'phone':
            handle_phone_stage(chat_id, campaign, participant, text)
            
        elif participant.registration_stage == 'subscription':
            handle_subscription_stage(chat_id, user_id, campaign, participant, text, first_name)
                    
    except Exception as e:
        print(f"❌ Error in handle_user_message: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")

def handle_name_stage(chat_id, participant, text):
    """Обработка ввода имени"""
    if text.strip():
        participant.first_name = text.strip()
        participant.registration_stage = 'phone'
        participant.save()
        
        print(f"✅ Сохранено имя: {text}")
        
        # Запрос телефона с кнопкой
        keyboard = {
            'keyboard': [[
                {'text': '📱 Поделиться номером', 'request_contact': True}
            ]],
            'resize_keyboard': True
        }
        
        send_telegram_message(
            chat_id, 
            f"Приятно познакомиться, {text.strip()}! 📱 *Ваш номер телефона*\n\nНам нужен ваш номер для связи в случае выигрыша.\n\nВведите номер или нажмите кнопку:", 
            keyboard,
            parse_mode='Markdown'
        )
    else:
        send_telegram_message(chat_id, "Пожалуйста, введите ваше имя:")

def handle_phone_stage(chat_id, campaign, participant, text):
    """Обработка ввода телефона"""
    if text == '📱 Поделиться номером':
        # Пользователь нажал кнопку, но не отправил контакт
        send_telegram_message(
            chat_id,
            "Пожалуйста, нажмите на кнопку '📱 Поделиться номером' и выберите 'Отправить мой номер'",
            parse_mode='Markdown'
        )
        return
        
    if text.strip():
        # Проверяем уникальность телефона
        phone_exists = Participant.objects.filter(
            campaign=campaign,
            phone=text.strip(),
            registration_stage='completed'
        ).exists()
        
        if phone_exists:
            send_telegram_message(
                chat_id,
                "❌ Этот номер телефона уже зарегистрирован. Пожалуйста, введите другой номер:"
            )
            return
        
        # Сохраняем телефон
        participant.phone = text.strip()
        participant.registration_stage = 'subscription'
        participant.save()
        
        print(f"✅ Сохранен телефон: {text}")
        
        # Переходим к подписке на каналы
        ask_for_subscription(chat_id, campaign, participant)
    else:
        send_telegram_message(chat_id, "Пожалуйста, введите ваш телефон:")

def handle_subscription_stage(chat_id, user_id, campaign, participant, text, first_name):
    """Обработка проверки подписки"""
    if text == '✅ Проверить подписку':
        # Проверяем подписку
        check_and_complete_registration(chat_id, user_id, campaign, participant, first_name)
    else:
        # Напоминаем о необходимости проверить подписку
        keyboard = {
            'keyboard': [[{'text': '✅ Проверить подписку'}]],
            'resize_keyboard': True
        }
        
        send_telegram_message(
            chat_id,
            "Пожалуйста, подпишитесь на указанные каналы и нажмите '✅ Проверить подписку'",
            keyboard
        )

def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    """Обработка отправленного контакта"""
    try:
        participant = Participant.objects.filter(
            telegram_id=user_id,
            registration_stage='phone'
        ).first()
        
        if not participant:
            send_telegram_message(chat_id, "❌ Сначала введите ваше имя")
            return
            
        # Форматируем номер телефона
        if phone:
            phone = re.sub(r'[^\d+]', '', phone)
            if not phone.startswith('+'):
                phone = '+' + phone
        
        # Проверяем уникальность телефона
        phone_exists = Participant.objects.filter(
            campaign=campaign,
            phone=phone,
            registration_stage='completed'
        ).exists()
        
        if phone_exists:
            send_telegram_message(
                chat_id,
                "❌ Этот номер телефона уже зарегистрирован. Пожалуйста, введите другой номер:"
            )
            return
        
        # Сохраняем телефон
        participant.phone = phone
        participant.registration_stage = 'subscription'
        participant.save()
        
        print(f"✅ Сохранен телефон из контакта: {phone}")
        
        # Переходим к подписке на каналы
        ask_for_subscription(chat_id, campaign, participant)
        
    except Exception as e:
        print(f"❌ Error in handle_contact: {e}")
        send_telegram_message(chat_id, "❌ Ошибка при обработке номера")

def ask_for_subscription(chat_id, campaign, participant):
    """Запрос подписки на каналы"""
    try:
        # Формируем список каналов
        channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
        channels_text = "\n".join([f"• {channel}" for channel in channels])
        
        keyboard = {
            'keyboard': [[{'text': '✅ Проверить подписку'}]],
            'resize_keyboard': True
        }
        
        send_telegram_message(
            chat_id,
            f"📢 *Подпишитесь на наши каналы*\n\n{channels_text}\n\nПосле подписки нажмите кнопку:",
            keyboard,
            parse_mode='Markdown'
        )
        
        print(f"🔹 Запрошена подписка для {participant.first_name}")
        
    except Exception as e:
        print(f"❌ Error in ask_for_subscription: {e}")

def check_and_complete_registration(chat_id, user_id, campaign, participant, first_name):
    """Проверка подписки и завершение регистрации"""
    try:
        # Проверяем подписку
        is_subscribed, failed_channels = check_user_subscription(user_id, campaign)
        
        if is_subscribed:
            # Завершаем регистрацию
            participant.is_subscribed = True
            participant.registration_stage = 'completed'
            participant.save()
            
            print(f"✅ Регистрация завершена для {participant.first_name}")
            
            # Финальное сообщение
            keyboard = {
                'keyboard': [
                    [{'text': '🎯 Участвовать в розыгрыше'}]
                ],
                'resize_keyboard': True
            }
            
            send_telegram_message(
                chat_id,
                f"🎉 *Регистрация завершена!*\n\n✅ Вы успешно зарегистрированы!\n👤 Имя: {participant.first_name}\n📞 Телефон: {participant.phone}\n\nСледите за новостями!",
                keyboard,
                parse_mode='Markdown'
            )
        else:
            # Показываем какие каналы не пройдены
            failed_text = "\n".join([f"• {channel}" for channel in failed_channels])
            
            keyboard = {
                'keyboard': [[{'text': '✅ Проверить подписку'}]],
                'resize_keyboard': True
            }
            
            send_telegram_message(
                chat_id,
                f"❌ *Вы не подписаны на все каналы!*\n\nНе подписаны:\n{failed_text}\n\nПожалуйста, подпишитесь и нажмите кнопку снова:",
                keyboard,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        print(f"❌ Error in check_and_complete_registration: {e}")
        send_telegram_message(chat_id, "❌ Ошибка при проверке подписки")

def check_user_subscription(user_id, campaign):
    """Проверка подписки пользователя на каналы"""
    bot_token = os.getenv("BOT_TOKEN")
    
    if not campaign.channel_usernames or campaign.channel_usernames.strip() == '@test_channel':
        return True, []
        
    channels = [channel.strip() for channel in campaign.channel_usernames.split(',')]
    
    print(f"🔍 Проверяемые каналы: {channels}")
    
    failed_channels = []
    
    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel
            
        if channel == '@test_channel':
            continue
            
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        params = {'chat_id': channel, 'user_id': user_id}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('ok'):
                    status = data['result'].get('status')
                    
                    if status in ['member', 'administrator', 'creator']:
                        print(f"✅ Подписан на {channel}")
                    else:
                        print(f"❌ НЕ подписан на {channel}")
                        failed_channels.append(channel)
                else:
                    print(f"🚫 Нет доступа к {channel}")
                    failed_channels.append(channel)
            else:
                print(f"🌐 Ошибка доступа к {channel}")
                failed_channels.append(channel)
                
        except Exception as e:
            print(f"💥 Ошибка проверки {channel}: {e}")
            failed_channels.append(channel)
    
    return len(failed_channels) == 0, failed_channels

def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Отправка сообщения через Telegram Bot API"""
    bot_token = os.getenv("BOT_TOKEN")
    
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    data = {
        'chat_id': chat_id,
        'text': text,
    }
    
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    
    if parse_mode:
        data['parse_mode'] = parse_mode
    
    try:
        response = requests.post(url, data=data)
        print(f"📤 Отправлено: {text[:50]}...")
        return response.json()
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return None