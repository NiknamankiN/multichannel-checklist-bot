from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from common.session import Session
from apps.telegram.keyboards import Keyboards
from common.validators import check_string, check_amount, is_file_required
from utils.helpers import get_translation
from services.geo_service import geo_service
from database.repository import repo


async def send_step_message(context: ContextTypes.DEFAULT_TYPE, chat: Session):
    """
    Отправляет сообщение для текущего шага чеклиста с соответствующей клавиатурой.
    Эта функция используется после перехода на новый шаг (Next/Back/Input).
    """
    if not chat.checklist_line:
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2')
    names = line.get('names')

    # Текст сообщения из чеклиста
    text = line.get('comment', '')

    # Генерация клавиатуры в зависимости от типа шага
    keyboard = None

    if step_type == 'spinner':
        keyboard = await Keyboards.get_spinner(chat.cur_spinner, line['key'], chat.lang)
    elif step_type == 'toggle':
        keyboard = await Keyboards.get_toggle(chat.lang)
    elif step_type == 'geo-position':
        keyboard = await Keyboards.get_geo_request(chat.lang)
    elif step_type == 'rating':
        keyboard = await Keyboards.get_rating(chat.lang)
    elif step_type == 'multi-spinner':
        keyboard = await Keyboards.get_multi_spinner(options, chat.spinners_data, line['key'], chat.lang, names)
    elif step_type == 'select':
        keyboard = await Keyboards.get_select(options, chat.selectors_data, chat.lang, names)
    elif step_type == 'choice':
        keyboard = await Keyboards.get_choice(options, chat.lang, names)
    elif step_type == 'date':
        keyboard = Keyboards.get_calendar(options, chat.lang)
    elif step_type == 'map':
        keyboard = await Keyboards.get_navigation(chat.lang, has_next=False)

    elif step_type == 'video':
        has_next = not is_file_required(options)
        keyboard = await Keyboards.get_navigation(chat.lang, has_next=has_next)

    elif step_type == 'document':
        keyboard = await Keyboards.get_navigation(chat.lang, has_next=False)

    elif step_type == 'photo':
        keyboard = await Keyboards.get_navigation(chat.lang, has_next=True)

    else:
        keyboard = await Keyboards.get_navigation(chat.lang)

    await context.bot.send_message(
        chat_id=chat.user_id,
        text=text,
        reply_markup=keyboard,
        parse_mode='html'
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Session):
    """
    Обработчик входящих текстовых сообщений.
    """
    if not chat.checklist_id or not chat.checklist_line:
        return

    line = chat.checklist_line
    step_type = line.get('type')
    options = line.get('options2')
    names = line.get('names')
    text = update.message.text

    checklist_completed = False
    update_result = False
    error_message = None

    # --- ЛОГИКА ОБРАБОТКИ ПО ТИПАМ ---

    if step_type == 'text':
        if check_string(text, options):
            # Сохраняем текст в БД
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
        # Поиск адреса: не переходим на следующий шаг, а обновляем клавиатуру результатами
        addresses = await geo_service.search_places(text, chat.lang)
        keyboard = await Keyboards.get_map_selection(addresses, chat.lang)

        # Отправляем сообщение с результатами (или с исходным текстом шага)
        msg = line.get('comment', 'Select address')
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='html')
        return

    elif step_type == 'select':
        # Фильтрация списка select по введенному тексту
        try:
            # Передаем введенный текст как фильтр для поиска ближайших совпадений
            keyboard = await Keyboards.get_select(options, chat.selectors_data, chat.lang, names, select_query=text)
            msg = line.get('comment', '')
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='html')
        except TypeError:
            pass
        return

    elif step_type == 'choice':
        # Фильтрация списка choice по введенному тексту
        try:
            # Передаем введенный текст как фильтр
            keyboard = await Keyboards.get_choice(options, chat.lang, names, select_query=text)
            msg = line.get('comment', '')
            await update.message.reply_text(msg, reply_markup=keyboard, parse_mode='html')
        except TypeError:
            pass
        return

    else:
        # Если пришел текст, а тип шага не предусматривает ввод текста (например, кнопки, фото, спиннер)
        # Мы просто повторяем сообщение текущего шага с клавиатурой
        await send_step_message(context, chat)
        return

    # --- РЕЗУЛЬТАТ ---

    if error_message:
        await update.message.reply_text(error_message)
        return

    if update_result:
        if checklist_completed:
            await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
        else:
            # Переходим к следующему шагу
            await send_step_message(context, chat)