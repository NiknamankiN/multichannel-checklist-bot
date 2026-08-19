from typing import List

from common.session import Session
from database.repository import repo
from apps.max.client import max_client
from utils.logger import max_logger as logger
from utils.helpers import get_translation


async def handle_command(text: str, chat: Session) -> bool:
    """
    Диспетчер команд.
    Возвращает True, если команда была обработана.
    """
    if not text.startswith('/'):
        return False

    parts = text.strip().split()
    command = parts[0].lower()
    args = parts[1:]

    if command == "/start":
        await start(args, chat)
        return True
    elif command == "/help":
        await help_command(chat)
        return True

    return False


async def start(args: List[str], chat: Session):
    """
    Обработчик команды /start <code.
    """

    # 1. Проверяем наличие аргументов (кода)
    if not args:
        error_text = await get_translation('no-auth-code', kit='multichannel-bot', lang=chat.lang)
        await max_client.send_message(chat.user_id, error_text)
        return

    command_string = args[0]
    user_id = chat.user_id
    masked_user_id = f"***{str(user_id)[-4:]}" if user_id is not None else "unknown"
    await logger.log(f"Handling /start command from user {masked_user_id}")

    try:
        # 2. Регистрируем попытку входа в БД (указываем канал 'max')
        await repo.register_user_action('max', command_string, chat.user_id, chat.lang)

        # 3. Получаем ответное сообщение
        response_message = await repo.get_auth_message('max', command_string, chat.lang)

        # 4. Отправляем ответ пользователю
        await max_client.send_message(chat.user_id, response_message)

        # 5. Логируем отправленное сообщение в историю БД
        await repo.log_message(
            bot_channel='max',
            chat_id=chat.user_id,
            message=response_message,
            outcome=True,  # Сообщение отправлено ботом
            checklist_id=chat.checklist_id,
            lang=chat.lang
        )

    except Exception as e:
        await logger.log(f"Error in start command (Max): {e}")
        await max_client.send_message(chat.user_id, "Internal error occurred.")


async def help_command(chat: Session):
    """
    Обработчик команды /help.
    """
    help_text = "Доступные команды:\n/start <код> - Авторизация"
    await max_client.send_message(chat.user_id, help_text)
