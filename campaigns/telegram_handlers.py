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
        active_campaign = Campaign.objects.filter(
            status='active', 
            bot_is_running=True
        ).first()
        
        if not active_campaign:
            print("❌ Нет активных кампаний с запущенным ботом")
            return JsonResponse({'ok': True})
        
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
            
            if text == '/start':
                handle_start(chat_id, user_id, first_name, username, active_campaign)
            elif text == (active_campaign.button_text or '🎯 Участвовать'):
                handle_participate(chat_id, user_id, first_name, username, active_campaign)
            else:
                handle_user_message(chat_id, user_id, text, first_name, username, active_campaign)
        
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
        keyboard = {
            'keyboard': [
                [{'text': campaign.button_text or '🎯 Участвовать'}]
            ],
            'resize_keyboard': True,
            'one_time_keyboard': False
        }
        
        send_telegram_message(
            chat_id, 
            campaign.first_message or 'Добро пожаловать!',
            keyboard
        )
        
        print(f"🔹 Пользователь {first_name} начал общение")
        
    except Exception as e:
        print(f"❌ Error in handle_start: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")

def handle_participate(chat_id, user_id, first_name, username, campaign):
    """Начало регистрации при нажатии кнопки участвовать"""
    try:
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

def handle_name_stage(chat_id, participant, text, campaign=None):
    if text.strip():
        participant.first_name = text.strip()
        participant.registration_stage = 'phone'
        participant.save()
        
        print(f"✅ Сохранено имя: {text}")
        
        keyboard = {
            'keyboard': [[
                {'text': campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}
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
    if text == (campaign.share_phone_button or '📱 Поделиться номером'):
        send_telegram_message(
            chat_id,
            f"Пожалуйста, нажмите на кнопку '{campaign.share_phone_button or '📱 Поделиться номером'}' и выберите 'Отправить мой номер'",
            parse_mode='Markdown'
        )
        return
        
    if text.strip():
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
        
        participant.phone = text.strip()
        participant.registration_stage = 'subscription'
        participant.save()
        
        print(f"✅ Сохранен телефон: {text}")
        
        ask_for_subscription(chat_id, campaign, participant)
    else:
        send_telegram_message(chat_id, "Пожалуйста, введите ваш телефон:")

def ask_for_subscription(chat_id, campaign, participant):
    """Запрос подписки на каналы"""
    try:
        channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
        channels_text = "\n".join([f"• {channel}" for channel in channels])
        
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
        
        print(f"🔹 Запрошена подписка для {participant.first_name}")
        
    except Exception as e:
        print(f"❌ Error in ask_for_subscription: {e}")

def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    bot_token = os.getenv("BOT_TOKEN")
    
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    data = {'chat_id': chat_id, 'text': text}
    
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
