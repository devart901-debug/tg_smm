from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path
from django.utils.html import format_html
from django.contrib import messages
import sys
import subprocess
import time
from .models import Campaign, Participant

# Глобальная переменная для хранения запущенных ботов
running_bots = {}

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'bot_status', 'participants_count', 'winners_count', 'export_excel_button', 'bot_actions']
    list_editable = ['status']
    list_filter = ['status', 'bot_is_running']
    prepopulated_fields = {'slug': ('name',)}
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'slug', 'status')
        }),
        ('Настройки Telegram', {
            'fields': ('channel_usernames',)
        }),
        ('Тексты для бота', {
            'fields': (
                'first_message', 
                'conditions_text',
                'prizes_text'
            )
        }),
        ('Тексты кнопок', {
            'fields': (
                'button_text', 
                'conditions_button',
                'prizes_button',
                'share_phone_button'
            )
        }),
        ('Настройки розыгрыша', {
            'fields': ('winners_count',)
        }),
        ('Управление ботом', {
            'fields': ('bot_is_running',),
            'classes': ('collapse',)
        }),
        ('Визуальное оформление', {
            'fields': ('theme_color',),
            'classes': ('collapse',)
        }),
    )
    
    # УБИРАЕМ ВСЕ СЛОЖНЫЕ ПРОВЕРКИ ПРАВ ДОСТУПА
    def has_delete_permission(self, request, obj=None):
        """Разрешаем удаление всегда"""
        return True
    
    def has_add_permission(self, request):
        """Разрешаем создание новых мероприятий"""
        return True

    def participants_count(self, obj):
        return obj.participants.count()
    participants_count.short_description = 'Участников'
    
    def bot_status(self, obj):
        if obj.bot_is_running:
            return format_html('<span style="color: green;">● Запущен</span>')
        else:
            return format_html('<span style="color: red;">● Остановлен</span>')
    bot_status.short_description = 'Статус бота'
    
    def winners_count(self, obj):
        return len(obj.winners) if obj.winners else 0
    winners_count.short_description = 'Победителей'
    
    def export_excel_button(self, obj):
        return format_html(
            '<a class="button" href="{}" style="background-color: #17a2b8; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px;">📊 Excel</a>',
            f'/admin/campaigns/campaign/{obj.id}/download_excel/'
        )
    export_excel_button.short_description = 'Экспорт'
    
    def bot_actions(self, obj):
        actions = []
        
        # Для черновиков показываем только запуск
        if obj.status == 'draft':
            actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/start_bot/" style="background-color: #28a745; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Запустить</a>')
        
        # Для активных мероприятий - полный набор действий
        elif obj.status == 'active':
            if obj.bot_is_running:
                actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/stop_bot/" style="background-color: #dc3545; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Остановить</a>')
                actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/restart_bot/" style="background-color: #ffc107; color: black; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Перезапустить</a>')
            else:
                actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/start_bot/" style="background-color: #28a745; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Запустить</a>')
            
            # Розыгрыш для активных мероприятий без победителей
            if not obj.winners:
                actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/raffle/" style="background-color: #ff6b35; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Розыгрыш</a>')
        
        # Для завершенных мероприятий
        elif obj.status == 'finished':
            if not obj.winners:
                actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/raffle/" style="background-color: #ff6b35; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">Розыгрыш</a>')
        
        # Показываем кнопку победителей только если есть победители
        if obj.winners:
            actions.append(f'<a class="button" href="/admin/campaigns/campaign/{obj.id}/show_winners/" style="background-color: #6f42c1; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; font-size: 12px; margin: 2px;">🏆 Победители</a>')
        
        if actions:
            return format_html(''.join(actions))
        else:
            return "-"
    
    bot_actions.short_description = 'Действия'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/start_bot/', self.start_bot, name='start_bot'),
            path('<path:object_id>/stop_bot/', self.stop_bot, name='stop_bot'),
            path('<path:object_id>/restart_bot/', self.restart_bot, name='restart_bot'),
            path('<path:object_id>/raffle/', self.start_raffle, name='raffle'),
            path('<path:object_id>/show_winners/', self.show_winners, name='show_winners'),
            path('<path:object_id>/download_excel/', self.export_excel, name='export_excel'),
        ]
        return custom_urls + urls
    
    def start_bot(self, request, object_id):
        try:
            campaign = Campaign.objects.get(id=object_id)
            
            # ПРОВЕРКА СТАТУСА
            if campaign.status != 'active':
                messages.error(request, 
                    f'Невозможно запустить бота! Мероприятие "{campaign.name}" имеет статус "{campaign.get_status_display()}". '
                    f'Запуск бота возможен только для мероприятий со статусом "Активно".'
                )
                return HttpResponseRedirect('/admin/campaigns/campaign/')
            
            # ПРОВЕРКА: Уже есть запущенный бот?
            active_bots = Campaign.objects.filter(bot_is_running=True).exclude(id=campaign.id)
            if active_bots.exists():
                active_campaign = active_bots.first()
                messages.error(request, 
                    f'Невозможно запустить бота! '
                    f'Уже запущен бот для мероприятия "{active_campaign.name}". '
                    f'Сначала остановите его, затем запускайте новый.'
                )
                return HttpResponseRedirect('/admin/campaigns/campaign/')
            
            if campaign.bot_is_running:
                messages.warning(request, f'Бот для мероприятия "{campaign.name}" уже запущен!')
            else:
                # ЗАПУСКАЕМ ЧЕРЕЗ ВЕБХУК (а не subprocess)
                success = campaign.start_bot()
                
                if success:
                    messages.success(request, f'Бот для мероприятия "{campaign.name}" успешно запущен (вебхук)!')
                else:
                    messages.error(request, f'Ошибка при запуске бота через вебхук!')
                    
        except Campaign.DoesNotExist:
            messages.error(request, 'Мероприятие не найдено!')
        except Exception as e:
            messages.error(request, f'Ошибка при запуске бота: {str(e)}')
        
        return HttpResponseRedirect('/admin/campaigns/campaign/')

    def stop_bot(self, request, object_id):
        try:
            campaign = Campaign.objects.get(id=object_id)
            
            if campaign.bot_is_running:
                # ОСТАНАВЛИВАЕМ ЧЕРЕЗ ВЕБХУК
                success = campaign.stop_bot()
                
                if success:
                    messages.success(request, f'Бот для мероприятия "{campaign.name}" остановлен!')
                else:
                    messages.error(request, f'Ошибка при остановке бота!')
            else:
                messages.warning(request, f'Бот для мероприятия "{campaign.name}" не был запущен!')
                
        except Campaign.DoesNotExist:
            messages.error(request, 'Мероприятие не найдено!')
        except Exception as e:
            messages.error(request, f'Ошибка при остановке бота: {str(e)}')
        
        return HttpResponseRedirect('/admin/campaigns/campaign/')

    def restart_bot(self, request, object_id):
        try:
            campaign = Campaign.objects.get(id=object_id)
            
            if campaign.bot_is_running:
                # Сначала останавливаем
                campaign.stop_bot()
                time.sleep(2)
                # Затем запускаем
                success = campaign.start_bot()
                
                if success:
                    messages.success(request, f'Бот для мероприятия "{campaign.name}" успешно перезапущен!')
                else:
                    messages.error(request, f'Ошибка при перезапуске бота!')
            else:
                messages.warning(request, f'Бот для мероприятия "{campaign.name}" не запущен! Используйте кнопку "Запустить".')
                
        except Campaign.DoesNotExist:
            messages.error(request, 'Мероприятие не найдено!')
        except Exception as e:
            messages.error(request, f'Ошибка при перезапуске бота: {str(e)}')
        
        return HttpResponseRedirect('/admin/campaigns/campaign/')

    def start_raffle(self, request, object_id):
        try:
            campaign = Campaign.objects.get(id=object_id)
            
            # 🔴 ПРОВЕРЯЕМ ЕСТЬ ЛИ УЖЕ ПОБЕДИТЕЛИ
            if campaign.winners:
                messages.error(request, f'Розыгрыш уже проводился для мероприятия "{campaign.name}"!')
                return HttpResponseRedirect('/admin/campaigns/campaign/')
            
            # 🔴 ПОДТВЕРЖДЕНИЕ РОЗЫГРЫША
            if 'confirm' not in request.GET:
                participants_count = campaign.participants.filter(is_subscribed=True).count()
                confirm_message = (
                    f'Вы уверены что хотите провести розыгрыш для мероприятия "<strong>{campaign.name}</strong>"?\n\n'
                    f'📊 Участников: {participants_count}\n'
                    f'🏆 Будет выбрано победителей: {campaign.winners_count}\n\n'
                    f'<strong>Это действие нельзя отменить!</strong>'
                )
                messages.warning(request, format_html(confirm_message))
                
                # Добавляем кнопки подтверждения
                confirm_url = f'/admin/campaigns/campaign/{object_id}/raffle/?confirm=true'
                cancel_url = '/admin/campaigns/campaign/'
                
                messages.info(request, format_html(
                    f'<a class="button" href="{confirm_url}" style="background-color: #28a745; color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px; margin: 5px;">✅ Да, провести розыгрыш</a>'
                    f'<a class="button" href="{cancel_url}" style="background-color: #dc3545; color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px; margin: 5px;">❌ Отмена</a>'
                ))
                return HttpResponseRedirect('/admin/campaigns/campaign/')
            
            # Проверяем можно ли проводить розыгрыш
            if campaign.status not in ['active', 'finished']:
                messages.error(request, 
                    f'Розыгрыш можно проводить только для активных или завершенных мероприятий! '
                    f'Текущий статус: "{campaign.get_status_display()}"'
                )
                return HttpResponseRedirect('/admin/campaigns/campaign/')
            
            # Запускаем розыгрыш
            result = subprocess.run([
                sys.executable, 'manage.py', 'raffle', campaign.slug, '--winners', str(campaign.winners_count)
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                messages.success(request, f'Розыгрыш для мероприятия "{campaign.name}" проведен успешно!')
                # Обновляем объект чтобы получить актуальные данные
                campaign.refresh_from_db()
                if campaign.winners:
                    # 🔴 ПОКАЗЫВАЕМ ПОБЕДИТЕЛЕЙ СРАЗУ ПОСЛЕ РОЗЫГРЫША
                    winners_text = "🏆 Победители:\n\n"
                    for winner in campaign.winners:
                        winners_text += f"{winner['place']}. {winner['name']} - {winner['phone']}\n"
                    messages.info(request, winners_text)
            else:
                messages.error(request, f'Ошибка при проведении розыгрыша: {result.stderr}')
            
        except Campaign.DoesNotExist:
            messages.error(request, 'Мероприятие не найдено!')
        except Exception as e:
            messages.error(request, f'Ошибка при проведении розыгрыша: {str(e)}')
        
        return HttpResponseRedirect('/admin/campaigns/campaign/')
    
    def show_winners(self, request, object_id):
        """Показать победителей в красивом формате"""
        try:
            campaign = Campaign.objects.get(id=object_id)
            if campaign.winners:
                # 🔴 СОЗДАЕМ КРАСИВЫЙ СПИСОК ПОБЕДИТЕЛЕЙ
                winners_html = f"""
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0;">
                    <h3 style="color: #6f42c1; margin-top: 0;">🏆 Победители мероприятия "{campaign.name}"</h3>
                    <div style="max-height: 400px; overflow-y: auto;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr style="background: #6f42c1; color: white;">
                                    <th style="padding: 10px; text-align: left; width: 60px;">Место</th>
                                    <th style="padding: 10px; text-align: left;">Имя</th>
                                    <th style="padding: 10px; text-align: left;">Телефон</th>
                                    <th style="padding: 10px; text-align: left;">Username</th>
                                </tr>
                            </thead>
                            <tbody>
                """
                
                for winner in campaign.winners:
                    winners_html += f"""
                                <tr style="border-bottom: 1px solid #dee2e6;">
                                    <td style="padding: 10px; font-weight: bold;">{winner['place']}</td>
                                    <td style="padding: 10px;">{winner['name']}</td>
                                    <td style="padding: 10px;">{winner['phone']}</td>
                                    <td style="padding: 10px;">{winner.get('username', 'Не указан')}</td>
                                </tr>
                    """
                
                winners_html += """
                            </tbody>
                        </table>
                    </div>
                    <p style="margin: 10px 0 0 0; color: #6c757d; font-size: 14px;">
                        Дата розыгрыша: """ + (campaign.raffle_date.strftime('%d.%m.%Y %H:%M') if campaign.raffle_date else 'Не указана') + """
                    </p>
                </div>
                """
                
                messages.success(request, format_html(winners_html))
            else:
                messages.warning(request, f"❌ Для мероприятия '{campaign.name}' розыгрыш еще не проводился!")
        except Campaign.DoesNotExist:
            messages.error(request, '❌ Мероприятие не найдено!')
        
        return HttpResponseRedirect('/admin/campaigns/campaign/')
    
    def export_excel(self, request, object_id):
        """Экспорт в Excel"""
        from .views import export_participants_excel
        return export_participants_excel(request, object_id)

@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'phone', 'campaign', 'is_subscribed', 'created_at']
    list_filter = ['campaign', 'is_subscribed', 'created_at']
    search_fields = ['first_name', 'phone', 'username']
    readonly_fields = ['created_at']

admin.site.site_header = "Управление Telegram ботом мероприятий"
admin.site.site_title = "Админка бота мероприятий"
admin.site.index_title = "Главная панель управления"