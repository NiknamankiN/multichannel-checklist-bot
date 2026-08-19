from telegram import Update
from telegram.ext import ContextTypes
from telegram_bot_calendar import DetailedTelegramCalendar

from common.session import Session
from common.callbacks import ChecklistLogic
from apps.telegram.keyboards import Keyboards
from apps.telegram.handlers.messages import send_step_message
from services.geo_service import geo_service
from datetime import date


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Session):
    """
    Обработчик callback-запросов для Telegram.
    Использует общую логику из ChecklistLogic.
    """
    query = update.callback_query
    data = query.data

    if data == 'do_nothing':
        await query.answer()
        return

    if not chat.checklist_id or not chat.checklist_line:
        await query.answer("Checklist is not active")
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2')
    names = line.get('names')

    async def clear_buttons():
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

    async def finish_step(success: bool, error: str, completed: bool):
        """Вспомогательная функция завершения шага"""
        if success:
            await query.answer()
            await clear_buttons()
            if completed:
                await query.message.reply_text("✅")
            else:
                await send_step_message(context, chat)
        else:
            await query.answer((error or "Error")[:200], show_alert=True)

    # --- НАВИГАЦИЯ ---

    if data == "back":
        await query.answer()
        await clear_buttons()
        await ChecklistLogic.on_back(chat)
        await send_step_message(context, chat)
        return

    if data == "next":
        success, error, completed = await ChecklistLogic.on_next(chat)
        await finish_step(success, error, completed)
        return

    # --- ТИПЫ ШАГОВ ---

    if step_type == 'toggle' and data in ['True', 'False']:
        success, error, completed = await ChecklistLogic.on_toggle(chat, data == 'True')
        await finish_step(success, error, completed)
        return

    elif step_type == 'rating' and data.startswith('rating_'):
        try:
            val = int(data.split('_')[1])
            success, error, completed = await ChecklistLogic.on_rating(chat, val)
            await finish_step(success, error, completed)
        except ValueError:
            await query.answer("Error")
        return

    elif step_type == 'spinner':
        if data.startswith(('increment_', 'decrement_')):
            action = 1 if 'increment_' in data else -1
            success, error = await ChecklistLogic.on_spinner_change(chat, action)

            if success:
                # Обновляем клавиатуру
                kb = await Keyboards.get_spinner(chat.cur_spinner, line['key'], chat.lang)
                try:
                    await query.edit_message_reply_markup(kb)
                except Exception:
                    pass
                await query.answer()
            else:
                await query.answer(error[:200], show_alert=True)
        return

    elif step_type == 'select':
        if data == 'select_confirm':
            success, error, completed = await ChecklistLogic.on_select_confirm(chat)
            await finish_step(success, error, completed)
            return

        if data.startswith('select_'):
            key = data[len('select_'):]

            # Автопереход для choice=1
            if options.get('choice', 1000) == 1:
                success, error, completed = await ChecklistLogic.on_choice(chat, key)
                await finish_step(success, error, completed)
                return

            # Иначе просто переключаем чекбокс
            success, error = await ChecklistLogic.on_select_toggle(chat, key)
            if success:
                kb = await Keyboards.get_select(options, chat.selectors_data, chat.lang, names)
                try:
                    await query.edit_message_reply_markup(kb)
                except Exception:
                    pass
                await query.answer()
            else:
                await query.answer(error[:200], show_alert=True)
            return

    elif step_type == 'choice':
        if data.startswith('confirm_choice_'):
            key = data[len('confirm_choice_'):]
            success, error, completed = await ChecklistLogic.on_choice(chat, key)
            await finish_step(success, error, completed)
            return

    elif step_type == 'multi-spinner':
        if data.startswith('multi-spinner_'):
            # Подтверждение
            success, error, completed = await ChecklistLogic.on_save_value(chat, None, json_data=chat.spinners_data)
            await finish_step(success, error, completed)
            return

        # Логика +/-
        action, key = None, None
        if data.startswith('decrement_'):
            action = -1
            key = data[len('decrement_'):]
        elif data.startswith('increment_'):
            action = 1
            key = data[len('increment_'):]

        if key and action:
            success, error = await ChecklistLogic.on_multi_spinner_change(chat, key, action)

            if success:
                # Обновляем клавиатуру
                kb = await Keyboards.get_multi_spinner(options, chat.spinners_data, line['key'], chat.lang, names)
                try:
                    await query.edit_message_reply_markup(kb)
                except Exception:
                    pass
                await query.answer()
            else:
                await query.answer(error[:200], show_alert=True)
            return

    # --- СПЕЦИФИЧНЫЕ ДЛЯ TELEGRAM (Календарь) ---
    elif step_type == 'date':
        locale = chat.lang if chat.lang in ['en', 'ru', 'eo'] else 'en'
        min_date = date.fromisoformat(options['min']) if 'min' in options else None
        max_date = date.fromisoformat(options['max']) if 'max' in options else None
        result, key, step = DetailedTelegramCalendar(calendar_id=0, min_date=min_date, max_date=max_date, locale=locale).process(data)

        if not result and key:
            try:
                await query.edit_message_text(f"{line.get('comment', '')}", reply_markup=key, parse_mode='html')
            except Exception:
                pass
            await query.answer()
        elif result:
            date_str = result.strftime("%d/%m/%Y")
            success, error, completed = await ChecklistLogic.on_save_value(chat, date_str)
            await finish_step(success, error, completed)
        return

    # --- MAP (Специфично, так как шлет локацию) ---
    elif step_type == 'map':
        if data.startswith('address_'):
            coords = data[len('address_'):]
            try:
                lon, lat = map(float, coords.split())
                await context.bot.send_location(chat.user_id, lat, lon)
                formatted, _ = await geo_service.get_formatted_address(lon, lat, chat.lang)
                kb = await Keyboards.get_map_confirm(coords, chat.lang)
                await context.bot.send_message(chat.user_id, formatted or "Confirm", reply_markup=kb)
                await query.answer()
            except ValueError:
                await query.answer("Error")
            return

        elif data.startswith('confirm_address_'):
            coords = data[len('confirm_address_'):]
            try:
                lon, lat = map(float, coords.split())
                full_addr = await geo_service.get_full_address_data(lon, lat)
                success, error, completed = await ChecklistLogic.on_save_value(chat, None, json_data=full_addr)
                await finish_step(success, error, completed)
            except ValueError:
                await query.answer("Error")
            return

    await query.answer()
