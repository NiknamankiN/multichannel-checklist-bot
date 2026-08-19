from common.session import Session
from apps.max.keyboards import MaxKeyboards
from apps.max.client import max_client
from common.validators import check_string, check_amount, is_file_required
from utils.helpers import get_translation
from services.geo_service import geo_service
from database.repository import repo


async def send_step_message(chat: Session):
    """
    Отправляет сообщение для текущего шага чеклиста в Max Messenger.
    """
    if not chat.checklist_line:
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2') or {} # Гарантируем dict
    names = line.get('names')

    # Текст сообщения из чеклиста
    text = line.get('comment', '')

    # Генерация клавиатуры (возвращает dict для JSON API)
    keyboard = None

    if step_type == 'spinner':
        keyboard = await MaxKeyboards.get_spinner(chat.cur_spinner, line['key'], chat.lang)
    elif step_type == 'toggle':
        keyboard = await MaxKeyboards.get_toggle(chat.lang)
    elif step_type == 'geo-position':
        keyboard = await MaxKeyboards.get_geo_request(chat.lang)
    elif step_type == 'rating':
        keyboard = await MaxKeyboards.get_rating(chat.lang)
    elif step_type == 'multi-spinner':
        keyboard = await MaxKeyboards.get_multi_spinner(options, chat.spinners_data, line['key'], chat.lang, names)
    elif step_type == 'select':
        keyboard = await MaxKeyboards.get_select(options, chat.selectors_data, chat.lang, names)
    elif step_type == 'choice':
        keyboard = await MaxKeyboards.get_choice(options, chat.lang, names)
    elif step_type == 'date':
        # Для Max мы используем нашу упрощенную реализацию календаря
        keyboard = MaxKeyboards.get_calendar(options, chat.lang)
    elif step_type == 'map':
        keyboard = await MaxKeyboards.get_navigation(chat.lang, has_next=False)

    elif step_type == 'video':
        has_next = not is_file_required(options)
        keyboard = await MaxKeyboards.get_navigation(chat.lang, has_next=has_next)

    elif step_type == 'document':
        keyboard = await MaxKeyboards.get_navigation(chat.lang, has_next=False)

    elif step_type == 'photo':
        keyboard = await MaxKeyboards.get_navigation(chat.lang, has_next=True)

    else:
        # Стандартная навигация (текст, сумма)
        keyboard = await MaxKeyboards.get_navigation(chat.lang)

    # Отправка сообщения через клиент Max
    await max_client.send_message(
        user_id=chat.user_id,
        text=text,
        keyboard=keyboard
    )


async def handle_text(text: str, chat: Session):
    """
    Обработчик входящих текстовых сообщений для Max.
    """
    if not chat.checklist_id or not chat.checklist_line:
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2') or {}
    names = line.get('names')

    checklist_completed = False
    update_result = False
    error_message = None

    # --- ЛОГИКА ОБРАБОТКИ ПО ТИПАМ ---

    if step_type == 'text':
        if check_string(text, options):
            success, desc, next_step_key = await repo.update_checklist_step(
                bot_name=chat.bot_name,
                chat_id=chat.user_id,
                checklist_id=chat.checklist_id,
                step_key=line['key'],
                value=text,
                lang=chat.lang
            )
            if success:
                checklist_completed = await chat.next_step(next_step_key)
                update_result = True
            else:
                error_message = desc
        else:
            error_message = await get_translation('wrong-answer', lang=chat.lang)

    elif step_type == 'amount':
        if check_amount(text, options):
            amount = float(text)
            success, desc, next_step_key = await repo.update_checklist_step(
                bot_name=chat.bot_name,
                chat_id=chat.user_id,
                checklist_id=chat.checklist_id,
                step_key=line['key'],
                amount=amount,
                lang=chat.lang
            )
            if success:
                checklist_completed = await chat.next_step(next_step_key)
                update_result = True
            else:
                error_message = desc
        else:
            error_message = await get_translation('wrong-answer', lang=chat.lang)

    elif step_type == 'map':
        # Поиск адреса
        addresses = await geo_service.search_places(text, chat.lang)
        keyboard = await MaxKeyboards.get_map_selection(addresses, chat.lang)

        msg = line.get('comment', 'Select address')
        await max_client.send_message(chat.user_id, msg, keyboard=keyboard)
        return

    elif step_type == 'select':
        # Фильтрация списка select
        try:
            keyboard = await MaxKeyboards.get_select(options, chat.selectors_data, chat.lang, names, select_query=text)
            msg = line.get('comment', '')
            await max_client.send_message(chat.user_id, msg, keyboard=keyboard)
        except Exception:
            pass
        return

    elif step_type == 'choice':
        # Фильтрация списка choice
        try:
            keyboard = await MaxKeyboards.get_choice(options, chat.lang, names, select_query=text)
            msg = line.get('comment', '')
            await max_client.send_message(chat.user_id, msg, keyboard=keyboard)
        except Exception:
            pass
        return

    else:
        # Если текст отправлен там, где его не ждут, повторяем вопрос
        await send_step_message(chat)
        return

    # --- РЕЗУЛЬТАТ ---

    if error_message:
        await max_client.send_message(chat.user_id, error_message)
        return

    if update_result:
        if checklist_completed:
            # Отправляем галочку и убираем клавиатуру (keyboard=None)
            await max_client.send_message(chat.user_id, "✅", keyboard=None)
        else:
            # Переходим к следующему шагу
            await send_step_message(chat)