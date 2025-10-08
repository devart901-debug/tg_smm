# campaigns/utils.py
import requests

def check_user_subscription(bot_token, user_id, channel_usernames):
    if not channel_usernames:
        return True, None

    channels = [c.strip() for c in channel_usernames.split(',')]
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
                    return False, channel
            else:
                # Telegram вернул ошибку, например бот не член канала
                print(f"check_user_subscription Telegram error: {data}")
                return False, channel
        except Exception as e:
            print(f"Ошибка проверки подписки на {channel}: {e}")
            return False, channel

    return True, None

    """
    Проверяет подписку пользователя на все указанные каналы
    Возвращает (is_subscribed: bool, failed_channel: str)
    """
    if not channel_usernames or channel_usernames.strip() == '@test_channel':
        # Если канал не указан или тестовый, пропускаем проверку
        return True, None
        
    channels = [channel.strip() for channel in channel_usernames.split(',')]
    
    for channel in channels:
        if not channel.startswith('@'):
            channel = '@' + channel
            
        # Пропускаем тестовый канал
        if channel == '@test_channel':
            continue
            
        # Проверяем подписку на канал
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        params = {
            'chat_id': channel,
            'user_id': user_id
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    status = data['result'].get('status')
                    # Если пользователь не участник или покинул канал
                    if status in ['left', 'kicked']:
                        return False, channel
                    # Если пользователь участник, администратор или создатель
                    elif status in ['member', 'administrator', 'creator']:
                        continue  # Проверяем следующий канал
                    else:
                        return False, channel
                else:
                    # Если бот не имеет доступа к каналу
                    return False, channel
            else:
                return False, channel
        except Exception as e:
            print(f"Ошибка проверки подписки на {channel}: {e}")
            return False, channel
    
    return True, None