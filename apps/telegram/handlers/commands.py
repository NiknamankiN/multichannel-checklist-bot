from telegram import Update
from telegram.ext import ContextTypes

# Предполагается, что Session теперь живет в common, как мы обсуждали ранее
from common.session import Session
from database.repository import repo
from utils.logger import tg_logger as logger
from utils.helpers import get_translation


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Session):
    """
    Обработчик команды /start.
    Принимает аргумент (код авторизации), например: /start 12345
    """
    user_id = getattr(chat, 'user_id', None)

    # 1. Проверяем наличие аргументов (кода)
    if not context.args:
        error_text = await get_translation('no-auth-code', kit='multichannel-bot', lang=chat.lang)
        await update.message.reply_text(error_text)
        return

    command_string = context.args[0]
    masked_user_id = f"***{str(user_id)[-4:]}" if user_id is not None else "unknown"
    await logger.log(f"Handling /start command from user {masked_user_id}")

    try:
        # 2. Регистрируем попытку входа в БД
        await repo.register_user_action('telegram', command_string, user_id, chat.lang)

        # 3. Получаем ответное сообщение (успех или описание ошибки)
        response_message = await repo.get_auth_message('telegram', command_string, chat.lang)

        # 4. Отправляем ответ пользователю
        await update.message.reply_text(response_message, parse_mode="html")

        # 5. Логируем отправленное сообщение в историю БД
        await repo.log_message(
            bot_channel='telegram',
            chat_id=user_id,
            message=response_message,
            outcome=True,  # Сообщение отправлено ботом
            checklist_id=chat.checklist_id,
            lang=chat.lang
        )

    except Exception as e:
        await logger.log(f"Error in start command: {e}")
        await update.message.reply_text("Internal error occurred.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Session):
    """
    Обработчик команды /help (если потребуется).
    """
    help_text = "Доступные команды:\n/start <код> - Авторизация"
    await update.message.reply_text(help_text)
