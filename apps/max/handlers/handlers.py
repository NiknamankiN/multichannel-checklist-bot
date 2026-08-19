from typing import Dict, Any
from common.session import Session
from apps.max.handlers import commands, messages, callbacks, media
from database.repository import repo
from utils.logger import max_logger as logger


async def handle_incoming_event(data: Dict[str, Any]):
    """
    Главный диспетчер событий от Max Messenger.
    Принимает JSON-пейлоад вебхука.
    """
    update_type = data.get('update_type')

    # Извлекаем user_id и username в зависимости от типа события
    user_data = None
    if update_type == 'message_created':
        message = data.get('message', {})
        user_data = message.get('sender')
    elif update_type == 'message_callback':
        callback = data.get('callback', {})
        user_data = callback.get('user')
    elif update_type == 'bot_started':
        user_data = data.get('user')

    if not user_data:
        # Неизвестный тип события или отсутствие данных пользователя
        return

    user_id = user_data.get('user_id') or user_data.get('id')  # В разных событиях может быть по-разному
    first_name = user_data.get("first_name") or "unknown"
    last_name = user_data.get("last_name") or ""

    username = f"{first_name} {last_name}".strip()

    # 1. Получаем/Создаем сессию
    # Для Max lang может приходить в поле user_locale (ru-RU), нужно парсить
    lang_code = data.get('user_locale', 'ru-RU')
    lang = lang_code.split('-')[0] if lang_code else 'ru'

    try:
        session = await Session.get_or_create(
            user_id=user_id,
            bot_name='max',
            username=username,
            lang=lang
        )
    except Exception as e:
        await logger.log(f"Error creating session for Max user {user_id}: {e}")
        return

    try:
        text_to_log = None
        if update_type == 'message_created':
            msg_body = data.get('message', {}).get('body', {})
            text_to_log = msg_body.get('text')
            # Если текста нет, но есть вложения, помечаем это в логах
            if not text_to_log and msg_body.get('attachments'):
                text_to_log = "[Медиафайл / Вложение]"

        elif update_type == 'message_callback':
            cb = data.get('callback', {})
            # Логируем, какую именно кнопку нажал пользователь
            text_to_log = f"[Нажатие кнопки: {cb.get('payload', 'unknown')}]"

        elif update_type == 'bot_started':
            text_to_log = "[Bot started with payload]"

        if text_to_log:
            # outcome=False означает, что сообщение пришло ОТ пользователя
            await repo.log_message(
                bot_channel='max',
                chat_id=user_id,
                message=text_to_log,
                outcome=False,
                checklist_id=session.checklist_id,
                lang=session.lang
            )
    except Exception as e:
        await logger.log(f"Error logging incoming user action for Max: {e}")

    # 2. Обработка события
    try:
        if update_type == 'message_created':
            message = data.get('message', {})
            body = message.get('body', {})
            text = body.get('text')
            attachments = body.get('attachments')


            # А. Проверка на команды (/start, /help)
            if text and text.startswith('/'):
                await commands.handle_command(text, session)
                return

            # Б. Обработка вложений (Фото, Видео, Гео)
            if attachments:
                await media.handle_media(message, session)
                return

            # В. Обработка текста (ответ на вопрос чеклиста)
            if text:
                await messages.handle_text(text, session)

        elif update_type == 'message_callback':
            # Нажатие на кнопку
            await callbacks.handle_callback(data, session)

        elif update_type == 'bot_started':
            # Обработка первого запуска (аналог /start без параметров)
            payload = data.get('payload')
            args = [payload] if payload else []
            await commands.start(args, session)

    except Exception as e:
        await logger.log(f"Error handling Max event {update_type}: {e}")
