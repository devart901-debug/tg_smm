# campaigns/views.py
import pandas as pd
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from .models import Campaign

# campaigns/views.py
from django.shortcuts import redirect

def home_page(request):
    """Главная страница - редирект на админку"""
    return redirect('/admin/')

def test_page(request):
    """Тестовая страница вебхука"""
    return HttpResponse("✅ Вебхук эндпоинт доступен!")

@staff_member_required
def export_participants_excel(request, campaign_id):
    """Экспорт участников в Excel"""
    campaign = get_object_or_404(Campaign, id=campaign_id)
    participants = campaign.participants.all()
    
    # Создаем DataFrame с участниками
    participants_data = []
    for participant in participants:
        participants_data.append({
            'ID': participant.id,
            'Telegram ID': participant.telegram_id,
            'Username': participant.username or 'Не указан',
            'Имя': participant.first_name,
            'Телефон': participant.phone,
            'Подписан на канал': 'Да' if participant.is_subscribed else 'Нет',
            'Дата регистрации': participant.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    # Создаем HttpResponse с Excel файлом
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="participants_{campaign.slug}.xlsx"'
    
    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        # Лист с участниками
        if participants_data:
            df_participants = pd.DataFrame(participants_data)
            df_participants.to_excel(writer, sheet_name='Участники', index=False)
        else:
            # Пустой лист если нет участников
            pd.DataFrame(['Нет участников']).to_excel(writer, sheet_name='Участники', index=False, header=False)
        
        # Лист с победителями если есть
        if campaign.winners:
            # Преобразуем JSON в DataFrame
            winners_data = []
            for winner in campaign.winners:
                winners_data.append({
                    'Место': winner.get('place', ''),
                    'Имя': winner.get('name', ''),
                    'Телефон': winner.get('phone', ''),
                    'Telegram ID': winner.get('telegram_id', '')
                })
            df_winners = pd.DataFrame(winners_data)
            df_winners.to_excel(writer, sheet_name='Победители', index=False)
        else:
            pd.DataFrame(['Розыгрыш еще не проводился']).to_excel(writer, sheet_name='Победители', index=False, header=False)
        
        # Лист с информацией о мероприятии
        info_data = {
            'Параметр': ['Название', 'Статус', 'Количество участников', 'Количество победителей', 'Дата розыгрыша'],
            'Значение': [
                campaign.name,
                campaign.get_status_display(),
                participants.count(),
                campaign.winners_count,
                campaign.raffle_date.strftime('%Y-%m-%d %H:%M:%S') if campaign.raffle_date else 'Не проводился'
            ]
        }
        df_info = pd.DataFrame(info_data)
        df_info.to_excel(writer, sheet_name='Информация', index=False)
    
    return response