from typing import Dict, Any
from common.session import Session
from common.callbacks import ChecklistLogic
from apps.max.keyboards import MaxKeyboards
from apps.max.client import max_client
from apps.max.handlers.messages import send_step_message
from services.geo_service import geo_service
from utils.logger import max_logger as logger


async def handle_callback(event: Dict, chat: Session):
    """
    Обработчик событий нажатия на кнопки (message_callback) для Max Messenger.
    """
    callback_data = event.get('callback', {})
    payload = callback_data.get('payload')  # Данные, зашитые в кнопку

    # ID сообщения для редактирования (спиннеры, селекты)
    # Структура: callback -> message -> body -> mid
    callback_id = callback_data.get('callback_id')
    message_id = callback_data.get('message', {}).get('body', {}).get('mid')

    if not payload or payload == 'do_nothing':
        return

    if not chat.checklist_id or not chat.checklist_line:
        await max_client.send_message(chat.user_id, "Checklist is not active")
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2') or {}
    names = line.get('names')

    async def finish_step(success: bool, error: str, completed: bool):
        """Вспомогательная функция завершения шага"""
        if success:
            # Пытаемся убрать кнопки у старого сообщения
            if callback_id:
                try:
                    await max_client.callback_answer(chat.user_id, callback_id, keyboard=None)
                except Exception:
                    pass  # Игнорируем ошибки редактирования (например, если сообщение старое)

            if completed:
                await max_client.send_message(chat.user_id, "✅", keyboard=None)
            else:
                # Отправляем следующий вопрос
                await send_step_message(chat)
        else:
            # В Max нет алертов, шлем текст ошибки
            await max_client.send_message(chat.user_id, f"⚠️ {error or 'Error'}")

    # --- НАВИГАЦИЯ ---

    if payload == "back":
        # Убираем кнопки у текущего шага
        if callback_id:
            try:
                await max_client.callback_answer(chat.user_id, callback_id, keyboard=None)
            except Exception:
                pass

        await ChecklistLogic.on_back(chat)
        await send_step_message(chat)
        return

    if payload == "next":
        success, error, completed = await ChecklistLogic.on_next(chat)
        await finish_step(success, error, completed)
        return

    # --- ТИПЫ ШАГОВ ---

    if step_type == 'toggle' and payload in ['True', 'False']:
        success, error, completed = await ChecklistLogic.on_toggle(chat, payload == 'True')
        await finish_step(success, error, completed)
        return

    elif step_type == 'rating' and payload.startswith('rating_'):
        try:
            val = int(payload.split('_')[1])
            success, error, completed = await ChecklistLogic.on_rating(chat, val)
            await finish_step(success, error, completed)
        except ValueError:
            pass
        return

    elif step_type == 'spinner':
        # Интерактивное обновление сообщения
        if payload.startswith(('increment_', 'decrement_')):
            action = 1 if 'increment_' in payload else -1
            success, error = await ChecklistLogic.on_spinner_change(chat, action)

            if success:
                # Генерируем новую клавиатуру с обновленным числом
                kb = await MaxKeyboards.get_spinner(chat.cur_spinner, line['key'], chat.lang)
                if callback_id:
                    await max_client.callback_answer(chat.user_id, callback_id, keyboard=kb)
            else:
                await max_client.send_message(chat.user_id, f"⚠️ {error}")
        return

    elif step_type == 'select':
        if payload == 'select_confirm':
            success, error, completed = await ChecklistLogic.on_select_confirm(chat)
            await finish_step(success, error, completed)
            return

        if payload.startswith('select_'):
            key = payload[len('select_'):]

            # Автопереход для choice=1
            if options.get('choice', 1000) == 1:
                success, error, completed = await ChecklistLogic.on_choice(chat, key)
                await finish_step(success, error, completed)
                return

            # Переключение чекбокса (обновляем сообщение)
            success, error = await ChecklistLogic.on_select_toggle(chat, key)
            if success:
                kb = await MaxKeyboards.get_select(options, chat.selectors_data, chat.lang, names)
                if callback_id:
                    await max_client.callback_answer(chat.user_id, callback_id, keyboard=kb)
            else:
                await max_client.send_message(chat.user_id, f"⚠️ {error}")
            return

    elif step_type == 'choice':
        if payload.startswith('confirm_choice_'):
            key = payload[len('confirm_choice_'):]
            success, error, completed = await ChecklistLogic.on_choice(chat, key)
            await finish_step(success, error, completed)
            return

    elif step_type == 'multi-spinner':
        if payload.startswith('multi-spinner_'):
            success, error, completed = await ChecklistLogic.on_save_value(chat, None, json_data=chat.spinners_data)
            await finish_step(success, error, completed)
            return

        # Логика +/- для мультиспиннера
        action, key = None, None
        if payload.startswith('decrement_'):
            action = -1
            key = payload[len('decrement_'):]
        elif payload.startswith('increment_'):
            action = 1
            key = payload[len('increment_'):]

        if key and action:
            success, error = await ChecklistLogic.on_multi_spinner_change(chat, key, action)
            if success:
                kb = await MaxKeyboards.get_multi_spinner(options, chat.spinners_data, line['key'], chat.lang, names)
                if callback_id:
                    await max_client.callback_answer(chat.user_id, callback_id, keyboard=kb)
            else:
                await max_client.send_message(chat.user_id, f"⚠️ {error}")
        return

    # --- DATE / CALENDAR ---
    elif step_type == 'date':
        # Календарь для Max реализован вручную в MaxKeyboards.get_calendar

        if payload.startswith('cal_'):
            # Навигация (смена месяца) -> Редактируем сообщение
            # Payload формата cal_YEAR_MONTH обрабатывается внутри get_calendar
            kb = MaxKeyboards.get_calendar(options, chat.lang, calendar_callback=payload)
            if callback_id:
                await max_client.callback_answer(chat.user_id, callback_id, keyboard=kb)
        else:
            # Выбор даты (payload содержит дату dd/mm/yyyy)
            # Простейшая проверка: если это не навигация, значит это дата
            success, error, completed = await ChecklistLogic.on_save_value(chat, payload)
            await finish_step(success, error, completed)
        return

    # --- MAP ---
    elif step_type == 'map':
        if payload.startswith('address_'):
            # Выбор промежуточного адреса
            coords = payload[len('address_'):]
            try:
                lon, lat = map(float, coords.split())

                # Отправляем сообщение с подтверждением (Max не поддерживает send_location так же нативно как TG для редактирования, поэтому шлем новое)
                formatted, _ = await geo_service.get_formatted_address(lon, lat, chat.lang)
                kb = await MaxKeyboards.get_map_confirm(coords, chat.lang)

                await max_client.send_message(
                    user_id=chat.user_id,
                    text=formatted or "Confirm location",
                    keyboard=kb,
                    location={"latitude": lat, "longitude": lon}
                )
            except ValueError:
                pass
            return

        elif payload.startswith('confirm_address_'):
            coords = payload[len('confirm_address_'):]
            try:
                lon, lat = map(float, coords.split())
                full_addr = await geo_service.get_full_address_data(lon, lat)
                success, error, completed = await ChecklistLogic.on_save_value(chat, None, json_data=full_addr)
                await finish_step(success, error, completed)
            except ValueError:
                await max_client.send_message(chat.user_id, "Error processing address")
            return