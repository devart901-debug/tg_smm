import json
import requests
import re
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Campaign, Participant
from dotenv import load_dotenv
load_dotenv()


@csrf_exempt
@require_POST
def telegram_webhook(request):
    try:
        active_campaign = Campaign.objects.filter(status='active', bot_is_running=True).first()
        if not active_campaign:
            print("❌ Нет активных кампаний с запущенным ботом")
            return JsonResponse({'ok': True})

        update = json.loads(request.body)
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            user_id = message['from']['id']
            first_name = message['from'].get('first_name', '')
            username = message['from'].get('username', '')

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

            handle_contact(chat_id, user_id, phone, first_name, username, active_campaign)

    except Exception as e:
        print(f"❌ Error in webhook: {e}")

    return JsonResponse({'ok': True})


def handle_start(chat_id, user_id, first_name, username, campaign):
    try:
        keyboard = {'keyboard': [[{'text': campaign.button_text or '🎯 Участвовать'}]],
                    'resize_keyboard': True, 'one_time_keyboard': False}
        send_telegram_message(chat_id, campaign.first_message or 'Добро пожаловать!', keyboard)
        print(f"🔹 Пользователь {first_name} начал общение")
    except Exception as e:
        print(f"❌ Error in handle_start: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")


def handle_participate(chat_id, user_id, first_name, username, campaign):
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

        send_telegram_message(chat_id, "📝 *Как вас зовут?*\n\nВведите ваше имя и фамилию:",
                              {'remove_keyboard': True}, parse_mode='Markdown')
        print(f"🔹 Начата регистрация для {first_name}")

    except Exception as e:
        print(f"❌ Error in handle_participate: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")


def handle_user_message(chat_id, user_id, text, first_name, username, campaign):
    try:
        participant = Participant.objects.filter(
            telegram_id=user_id,
            registration_stage__in=['name', 'phone', 'subscription']
        ).first()
        if not participant:
            handle_start(chat_id, user_id, first_name, username, campaign)
            return

        stage = participant.registration_stage
        if stage == 'name':
            handle_name_stage(chat_id, participant, text, campaign)
        elif stage == 'phone':
            handle_phone_stage(chat_id, participant, text, campaign)
        elif stage == 'subscription':
            handle_subscription_stage(chat_id, participant, text, campaign, first_name)

    except Exception as e:
        print(f"❌ Error in handle_user_message: {e}")
        send_telegram_message(chat_id, "❌ Произошла ошибка, попробуйте позже")


def handle_name_stage(chat_id, participant, text, campaign):
    if text.strip():
        participant.first_name = text.strip()
        participant.registration_stage = 'phone'
        participant.save()
        keyboard = {'keyboard': [[{'text': campaign.share_phone_button or '📱 Поделиться номером', 'request_contact': True}]],
                    'resize_keyboard': True}
        send_telegram_message(
            chat_id,
            f"Приятно познакомиться, {text.strip()}! 📱 *Ваш номер телефона*\n\nВведите номер или нажмите кнопку:",
            keyboard, parse_mode='Markdown')
    else:
        send_telegram_message(chat_id, "Пожалуйста, введите ваше имя:")


def handle_phone_stage(chat_id, participant, text, campaign):
    if text == (campaign.share_phone_button or '📱 Поделиться номером'):
        send_telegram_message(chat_id,
                              f"Пожалуйста, нажмите на кнопку '{campaign.share_phone_button or '📱 Поделиться номером'}' и выберите 'Отправить мой номер'",
                              parse_mode='Markdown')
        return

    if text.strip():
        phone_exists = Participant.objects.filter(
            campaign=participant.campaign,
            phone=text.strip(),
            registration_stage='completed'
        ).exists()
        if phone_exists:
            send_telegram_message(chat_id, "❌ Этот номер уже зарегистрирован. Введите другой:")
            return
        participant.phone = text.strip()
        participant.registration_stage = 'subscription'
        participant.save()
        ask_for_subscription(chat_id, participant.campaign, participant)
    else:
        send_telegram_message(chat_id, "Пожалуйста, введите ваш телефон:")


def handle_subscription_stage(chat_id, participant, text, campaign, first_name):
    if text == (campaign.conditions_button or '✅ Проверить подписку'):
        check_and_complete_registration(chat_id, participant.telegram_id, campaign, participant, first_name)
    else:
        keyboard = {'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]], 'resize_keyboard': True}
        send_telegram_message(chat_id, "Подпишитесь на каналы и нажмите кнопку:", keyboard)


def handle_contact(chat_id, user_id, phone, first_name, username, campaign):
    participant = Participant.objects.filter(telegram_id=user_id, registration_stage='phone').first()
    if not participant:
        send_telegram_message(chat_id, "❌ Сначала введите ваше имя")
        return

    if phone:
        phone = re.sub(r'[^\d+]', '', phone)
        if not phone.startswith('+'):
            phone = '+' + phone

    phone_exists = Participant.objects.filter(
        campaign=participant.campaign,
        phone=phone,
        registration_stage='completed'
    ).exists()
    if phone_exists:
        send_telegram_message(chat_id, "❌ Этот номер уже зарегистрирован. Введите другой:")
        return

    participant.phone = phone
    participant.registration_stage = 'subscription'
    participant.save()
    ask_for_subscription(chat_id, participant.campaign, participant)


def ask_for_subscription(chat_id, campaign, participant):
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',') if ch.strip()]
    channels_text = "\n".join([f"• {ch}" for ch in channels])
    keyboard = {'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]],
                'resize_keyboard': True}
    send_telegram_message(chat_id,
                          f"📢 *Подпишитесь на каналы*\n\n{channels_text}\n\nПосле подписки нажмите кнопку:",
                          keyboard, parse_mode='Markdown')


def check_and_complete_registration(chat_id, user_id, campaign, participant, first_name):
    is_subscribed, failed_channels = check_user_subscription(user_id, campaign)
    if is_subscribed:
        participant.is_subscribed = True
        participant.registration_stage = 'completed'
        participant.save()
        keyboard = {'keyboard': [[{'text': campaign.button_text or '🎯 Участвовать'}]],
                    'resize_keyboard': True}
        send_telegram_message(chat_id,
                              f"🎉 Регистрация завершена!\n👤 {participant.first_name}\n📞 {participant.phone}",
                              keyboard)
    else:
        failed_text = "\n".join([f"• {ch}" for ch in failed_channels])
        keyboard = {'keyboard': [[{'text': campaign.conditions_button or '✅ Проверить подписку'}]], 'resize_keyboard': True}
        send_telegram_message(chat_id, f"❌ Не подписаны на:\n{failed_text}\nПодпишитесь и попробуйте снова.", keyboard)


def check_user_subscription(user_id, campaign):
    bot_token = os.getenv("BOT_TOKEN")
    if not campaign.channel_usernames:
        return True, []
    channels = [ch.strip() for ch in campaign.channel_usernames.split(',')]
    failed = []
    for ch in channels:
        if not ch.startswith('@'):
            ch = '@' + ch
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        params = {'chat_id': ch, 'user_id': user_id}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200 and r.json().get('ok'):
                status = r.json()['result']['status']
                if status not in ['member', 'administrator', 'creator']:
                    failed.append(ch)
            else:
                failed.append(ch)
        except Exception:
            failed.append(ch)
    return len(failed) == 0, failed


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
