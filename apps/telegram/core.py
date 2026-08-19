import asyncio
from typing import Callable, Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from telegram.error import TimedOut, NetworkError, RetryAfter, TelegramError

from config import BOT_KEY
from common.session import Session
from apps.telegram.handlers import commands, messages, callbacks, media
from database.repository import repo
from database.postgres import db
from database.sqlite import sqlite_client
from services.http_client import http_client
from utils.logger import tg_logger as logger


class BotCore:
    def __init__(self):
        self.app = ApplicationBuilder().token(BOT_KEY).read_timeout(60).write_timeout(60).connect_timeout(
            60).build()
        self.register_handlers()
        self.register_jobs()

    def _wrap(self, handler_func: Callable) -> Callable:
        """
        Декоратор/Обертка для хендлеров.
        """

        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user = update.effective_user
            if not user: return
            lang = user.language_code or 'ru'

            try:
                # Явно указываем имя бота 'telegram'
                chat_session = await Session.get_or_create(
                    user_id=update.effective_chat.id,
                    bot_name="telegram",
                    username=user.username,
                    lang=lang
                )
                # --- ЛОГИРОВАНИЕ ВХОДЯЩИХ ДЕЙСТВИЙ (MIDDLEWARE) ---
                try:
                    text_to_log = None
                    if update.message:
                        if update.message.text:
                            text_to_log = f"[Text message, length={len(update.message.text)}]"
                        elif update.message.photo or update.message.video or update.message.document:
                            text_to_log = "[Медиафайл / Вложение]"
                        elif update.message.location:
                            text_to_log = "[Геопозиция]"
                    elif update.callback_query:
                        text_to_log = f"[Нажатие кнопки]"

                    if text_to_log:
                        await repo.log_message(
                            bot_channel="telegram",
                            chat_id=update.effective_chat.id,
                            message=text_to_log,
                            outcome=False,
                            checklist_id=chat_session.checklist_id,
                            lang=chat_session.lang
                        )
                except Exception as log_e:
                    await logger.log(f"Error logging incoming user action for Telegram: {log_e}")

                await handler_func(update, context, chat_session)

            except Exception as e:
                await logger.log(f"Error in handler {handler_func.__name__}: {e}")

        return wrapper

    def register_handlers(self):
        # 1. Команды
        self.app.add_handler(CommandHandler("start", self._wrap(commands.start)))

        # 2. Callbacks
        self.app.add_handler(CallbackQueryHandler(self._wrap(callbacks.handle_callback)))

        # 3. Медиа
        self.app.add_handler(MessageHandler(filters.PHOTO, self._wrap_photo_handler))
        self.app.add_handler(MessageHandler(filters.VIDEO, self._wrap(media.handle_video)))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self._wrap(media.handle_document)))
        self.app.add_handler(MessageHandler(filters.LOCATION, self._wrap(media.handle_location)))

        # 4. Текст
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._wrap(messages.handle_text)))

    async def _wrap_photo_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user: return

        chat_session = await Session.get_or_create(
            user_id=update.effective_chat.id,
            bot_name="telegram",
            username=user.username,
            lang=user.language_code or 'ru'
        )

        # --- ЛОГИРОВАНИЕ ВХОДЯЩИХ ДЕЙСТВИЙ (MIDDLEWARE) ---
        try:
            await repo.log_message(
                bot_channel="telegram",
                chat_id=update.effective_chat.id,
                message="[Медиафайл / Вложение]",
                outcome=False,
                checklist_id=chat_session.checklist_id,
                lang=chat_session.lang
            )
        except Exception as log_e:
            await logger.log(f"Error logging incoming photo for Telegram: {log_e}")

        response_text = await media.handle_photo(update, chat_session)

        from apps.telegram.handlers.messages import send_step_message
        await update.message.reply_text(response_text, parse_mode=ParseMode.HTML)
        await send_step_message(context, chat_session)

    def register_jobs(self):
        job_queue = self.app.job_queue
        job_queue.run_repeating(self.message_sender_job, interval=15, first=5)

    async def message_sender_job(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Фоновая задача: отправка сообщений с умными повторными попытками.
        """
        from telegram import InputMediaPhoto, InputMediaDocument
        from apps.telegram.handlers.messages import send_step_message
        from utils.helpers import get_translation

        try:
            # Получаем сообщения только для telegram
            pending_messages = await repo.fetch_pending_messages(bot_channel="telegram", lang="ru")

            for msg in pending_messages:
                # Пауза 50мс перед каждым сообщением, чтобы не превысить лимиты Telegram (~20 сообщ/сек)
                await asyncio.sleep(0.05)

                msg_id, checklist_id, recipient, title, body, files, photos, result = msg

                if not recipient:
                    await repo.update_message_state(msg_id, 'error', 'No recipient')
                    continue

                chat_id = int(recipient)

                # --- ЛОГИКА ПОВТОРНЫХ ПОПЫТОК (RETRIES) ---
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        chat = await Session.get_or_create(chat_id, "telegram", "unknown")

                        # Логика сброса чеклиста
                        if body == "{BOT-RESET}":
                            await chat.complete_checklist()  # Очищает данные в БД
                            reset_msg = await get_translation('checklist-reset', lang=chat.lang)
                            await context.bot.send_message(chat_id, reset_msg)

                            await repo.log_message(
                                bot_channel="telegram",
                                chat_id=chat_id,
                                message=reset_msg,
                                outcome=True,
                                checklist_id=None,
                                lang=chat.lang
                            )
                            await repo.update_message_state(msg_id, 'done', None)
                            break  # Успех, выходим из цикла retries

                        if chat.is_active():
                            await repo.defer_message(msg_id=msg_id, reason="User has an active checklist",)
                            break  # Пропускаем, если активен (возможно, стоит помечать как error или done?)

                        # Медиа: Разделяем фото и документы
                        photo_group = []
                        if photos:
                            for url in photos.split('\r\n'):
                                if url.strip():
                                    photo_group.append(InputMediaPhoto(media=url.strip()))

                        doc_group = []
                        if files:
                            for url in files.split('\r\n'):
                                if url.strip():
                                    doc_group.append(InputMediaDocument(media=url.strip()))

                        text_sent = False

                        if photo_group:
                            text_sent = True
                            await context.bot.send_media_group(chat_id, caption=body, parse_mode='html',
                                                               media=photo_group)

                        if doc_group:
                            text_sent = True
                            await context.bot.send_media_group(chat_id, caption=body, parse_mode='html',
                                                               media=doc_group)

                        if body and not text_sent:
                            await context.bot.send_message(chat_id, body, parse_mode='html')

                        if checklist_id:
                            definition = await repo.get_checklist_definition(checklist_id, chat.lang)
                            if definition:
                                await chat.start_new_checklist(checklist_id, definition)
                                await send_step_message(context, chat)

                                if chat.checklist_line:
                                    await repo.log_message(
                                        bot_channel="telegram",
                                        chat_id=chat_id,
                                        message=chat.checklist_line.get('comment', ''),
                                        outcome=True,
                                        checklist_id=checklist_id,
                                        lang=chat.lang
                                    )

                        # Если код дошел сюда без исключений, значит сообщение успешно отправлено
                        await repo.update_message_state(msg_id, 'done', None)
                        break  # Выходим из цикла повторных попыток

                    except RetryAfter as e:
                        # Telegram просит подождать (превышен лимит отправки)
                        await logger.log(
                            f"Flood control exceeded for msg {msg_id}. Sleeping for {e.retry_after} seconds.")
                        await asyncio.sleep(e.retry_after)

                    except (TimedOut, NetworkError) as e:
                        # Сетевая ошибка или таймаут. Ждем 2 секунды и пробуем снова.
                        await logger.log(
                            f"Network error/Timeout for msg {msg_id} (Attempt {attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(2)

                    except Exception as e:
                        # Фатальная ошибка (например, юзер заблокировал бота: Forbidden)
                        # Нет смысла пробовать снова, помечаем как error
                        error_text = f"Fatal error processing msg {msg_id}: {e}"
                        await logger.log(error_text)
                        await repo.update_message_state(msg_id, 'error', str(e))
                        break  # Выходим из цикла повторных попыток

                else:
                    # Блок else для цикла for срабатывает, если цикл завершился НЕ через break
                    # Это означает, что все 3 попытки были с ошибкой TimedOut/NetworkError
                    error_text = f"Failed to send msg {msg_id} after {max_retries} retries due to network issues."
                    await logger.log(error_text)
                    await repo.update_message_state(msg_id, 'error', "Max retries exceeded")

        except Exception as e:
            await logger.log(f"Global message sender loop error: {e}")

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.run_until_complete(db.connect())
        loop.run_until_complete(sqlite_client.init_db())

        print("Bot started...")

        try:
            self.app.run_polling(close_loop=False)
        except Exception as e:
            loop.run_until_complete(logger.log(f"Bot crash: {e}"))
        finally:
            try:
                loop.run_until_complete(self.shutdown())
            except Exception as e:
                print(f"Error during shutdown: {e}")
            finally:
                loop.close()

    async def shutdown(self):
        await http_client.close()
        await db.close()
        await sqlite_client.close()
        print("Bot stopped.")
