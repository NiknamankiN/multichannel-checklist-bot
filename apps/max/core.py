import asyncio
from typing import Optional

from common.session import Session
from apps.max.client import max_client
from apps.max.handlers.messages import send_step_message
from database.repository import repo
from utils.logger import max_logger as logger
from utils.helpers import get_translation


class MaxBotCore:
    """
    Класс управления фоновыми процессами для Max бота.
    Запускается вместе с FastAPI сервером.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Запуск фоновых задач"""
        self._running = True
        self._task = asyncio.create_task(self.message_sender_job())
        await logger.log("Max Messenger background jobs started")

    async def stop(self):
        """Остановка фоновых задач"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await logger.log("Max Messenger background jobs stopped")

    async def message_sender_job(self):
        """
        Фоновая задача: проверяет очередь сообщений в БД и отправляет их в Max.
        """
        while self._running:
            try:
                # Получаем сообщения для канала 'max'
                pending_messages = await repo.fetch_pending_messages(bot_channel="max", lang="ru")

                for msg in pending_messages:
                    await asyncio.sleep(0.05)
                    msg_id, checklist_id, recipient, title, body, files, photos, result = msg

                    if not recipient:
                        await repo.update_message_state(msg_id, 'error', 'No recipient')
                        continue

                    user_id = int(recipient)

                    # --- ЛОГИКА ПОВТОРНЫХ ПОПЫТОК (RETRIES) ---
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            chat = await Session.get_or_create(user_id, "max", "unknown")

                            # 1. Сброс чеклиста
                            if body == "{BOT-RESET}":
                                await chat.complete_checklist()
                                reset_msg = await get_translation('checklist-reset', lang=chat.lang)
                                res = await max_client.send_message(user_id, reset_msg)
                                if res is None:
                                    await logger.log(f"Failed to send reset_msg: {msg_id}")
                                    raise ConnectionError(f"Failed to send reset_msg, msg_id: {msg_id}")

                                await repo.log_message(
                                    bot_channel="max",
                                    chat_id=user_id,
                                    message=reset_msg,
                                    outcome=True,
                                    checklist_id=None,
                                    lang=chat.lang
                                )
                                await repo.update_message_state(msg_id, 'done', None)
                                break  # Успех, выходим из цикла retries

                            # 2. Проверка активного чеклиста
                            if chat.is_active():
                                await repo.defer_message(msg_id=msg_id, reason="User has an active checklist",)
                                break  # Пропускаем, если активен

                            # 3. Отправка медиа
                            photo_attachments = []
                            file_attachments = []

                            # Загрузка фотографий
                            if photos:
                                for url in photos.split('\r\n'):
                                    if url.strip():
                                        att = await max_client.upload_media(url.strip(), 'image')
                                        if not att:
                                            await logger.log(f"Failed to upload photo, msg_id: {msg_id}")
                                            raise ConnectionError(f"Failed to upload photo, msg_id: {msg_id}")
                                        photo_attachments.append(att)

                            # Загрузка документов/видео
                            if files:
                                for url in files.split('\r\n'):
                                    if url.strip():
                                        # Пытаемся по расширению определить, видео ли это.
                                        # Остальное кидаем как 'file' (документ)
                                        url_clean = url.strip().lower()
                                        is_video = url_clean.endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm'))
                                        media_type = 'video' if is_video else 'file'

                                        att = await max_client.upload_media(url.strip(), media_type)
                                        if not att:
                                            await logger.log(f"Failed to upload file, msg_id: {msg_id}")
                                            raise ConnectionError(f"Failed to upload file, msg_id: {msg_id}")
                                        file_attachments.append(att)

                            # Делаем паузу, чтобы сервер Max успел обработать медиа (избегаем attachment.not.ready)
                            if photo_attachments or file_attachments:
                                await asyncio.sleep(2)

                            text_sent = False

                            # 4. Отправка фотографий (можно отправлять массивом в одном сообщении)
                            if photo_attachments:
                                res = await max_client.send_message(
                                    user_id=user_id,
                                    text=body if body else "",
                                    media_attachments=photo_attachments
                                )
                                if res is None:
                                    await logger.log(f"Failed to send photo_attachments, msg_id: {msg_id}")
                                    raise ConnectionError("Failed to send photo_attachments")
                                text_sent = True
                                await asyncio.sleep(1)  # небольшая пауза перед следующим блоком

                            # 5. Отправка файлов (каждый файл строго отдельным сообщением)
                            if file_attachments:
                                for i, f_att in enumerate(file_attachments):
                                    current_text = ""
                                    if not text_sent and i == 0:
                                        current_text = body if body else ""
                                        text_sent = True

                                    res = await max_client.send_message(
                                        user_id=user_id,
                                        text=current_text,
                                        media_attachments=[f_att]
                                    )
                                    if res is None:
                                        await logger.log(f"Failed to send file attachment, msg_id: {msg_id}")
                                        raise ConnectionError("Failed to send file_attachments")
                                    await asyncio.sleep(1)

                            # 6. Если был только текст
                            if body and not text_sent:
                                res = await max_client.send_message(user_id, body)
                                if res is None:
                                    await logger.log(f"Failed to send message, msg_id: {msg_id}")
                                    raise ConnectionError(f"Max API did not send message {msg_id}")

                            # 7. Назначение нового чеклиста
                            if checklist_id:
                                definition = await repo.get_checklist_definition(checklist_id, chat.lang)
                                if definition:
                                    await chat.start_new_checklist(checklist_id, definition)
                                    await send_step_message(chat)

                                    if chat.checklist_line:
                                        await repo.log_message(
                                            bot_channel="max",
                                            chat_id=user_id,
                                            message=chat.checklist_line.get('comment', ''),
                                            outcome=True,
                                            checklist_id=checklist_id,
                                            lang=chat.lang
                                        )

                            await repo.update_message_state(msg_id, 'done', None)
                            break  # Успех, выходим из цикла retries

                        except ConnectionError as e:
                            # Сетевая ошибка (Max API вернул None). Ждем 2 секунды и пробуем снова.
                            await logger.log(
                                f"Network error/Timeout for msg {msg_id} (Attempt {attempt + 1}/{max_retries}): {e}")
                            await asyncio.sleep(2)

                        except Exception as e:
                            # Фатальная ошибка (например, ошибка БД или разбора данных)
                            error_text = f"Fatal error processing msg {msg_id}: {e}"
                            await logger.log(error_text)
                            await repo.update_message_state(msg_id, 'error', str(e))
                            break  # Выходим из цикла повторных попыток

                    else:
                        # Блок else для цикла for срабатывает, если цикл завершился НЕ через break (3 раза упали)
                        error_text = f"Failed to send msg {msg_id} after {max_retries} retries due to network issues."
                        await logger.log(error_text)
                        await repo.update_message_state(msg_id, 'error', "Max retries exceeded")

            except Exception as e:
                await logger.log(f"Global Max message sender loop error: {e}")

            # Пауза между проверками БД
            await asyncio.sleep(15)
