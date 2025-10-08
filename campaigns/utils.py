# campaigns/utils.py
import requests
import os

def check_user_subscription(bot_token, user_id, channel_usernames):
    """
    Проверяет подписку пользователя на все указанные каналы.
    Возвращает (is_subscribed: bool, failed_channels: list)
    """
    if not channel_usernames:
        return True, []

    channels = [ch.strip() for ch in channel_usernames.split(',') if ch.strip()]
    failed_channels = []

    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel

        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        params = {'chat_id': channel, 'user_id': user_id}

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('ok'):
                status = data['result'].get('status')
                if status in ['left', 'kicked']:
                    failed_channels.append(channel)
            else:
                # Ошибка от Telegram (например, бот не админ)
                failed_channels.append(channel)
        except Exception as e:
            print(f"Ошибка проверки подписки на {channel}: {e}")
            failed_channels.append(channel)

    is_subscribed = len(failed_channels) == 0
    return is_subscribed, failed_channels
