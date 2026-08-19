from typing import Dict, Any
from common.media import BaseMediaHandler
from apps.max.client import max_client
from apps.max.handlers.messages import send_step_message
from utils.helpers import get_translation
from utils.logger import max_logger as logger


async def handle_media(message: Dict, session: Any):
    """
    Обработчик медиа-вложений для Max Messenger.
    Разбирает JSON вебхука и вызывает соответствующие методы BaseMediaHandler.
    """
    body = message.get('body', {})
    attachments = body.get('attachments', [])

    if not attachments:
        return

    # Обычно обрабатываем первое вложение, так как шаг чеклиста ожидает конкретный тип
    for att in attachments:
        att_type = att.get('type')
        payload = att.get('payload', {})

        # 1. Изображения (Image)
        # В Max тип может быть 'image' (новый) или 'photo' (старый)
        if att_type in ('image', 'photo'):
            # Согласно отчету, payload содержит 'url' (полный) и 'token' (ID файла)
            image_url = payload.get('url')
            uniq_photo_id = payload.get('photo_id')

            if not image_url:
                await logger.log(f"Max: Empty image URL for user {session.user_id}")
                continue

            # Вызываем общую бизнес-логику
            response_text = await BaseMediaHandler.process_photo(
                chat=session,
                file_path_url=image_url,
                unique_file_id=uniq_photo_id,
                folder='max_photos'
            )

            # Отправляем результат (например, "Фото загружено")
            await max_client.send_message(session.user_id, response_text)

            # Обновляем сообщение текущего шага (чтобы обновился счетчик фото)
            await send_step_message(session)

        # 2. Видео (Video)
        elif att_type == 'video':
            video_url = payload.get('url')
            if not video_url:
                await logger.log(f"Max: Empty video URL for user {session.user_id}")
                continue

            # Вызываем общую логику
            success, desc, next_step_key = await BaseMediaHandler.process_video(
                chat=session,
                file_path_url=video_url,
                folder='max_videos'
            )

            if success:
                await logger.log(f"Max: Video uploaded for step {session.checklist_line.get('key')}")
                # Переходим на следующий шаг
                checklist_completed = await session.next_step(next_step_key)

                if checklist_completed:
                    await max_client.send_message(session.user_id, "✅")
                else:
                    await max_client.send_message(session.user_id, "✅")
                    await send_step_message(session)
            else:
                await max_client.send_message(session.user_id, desc or "Error processing video")

        # 3. Документы (File)
        elif att_type == 'file':
            doc_url = payload.get('url')
            file_size = payload.get('size', 0)
            if not doc_url:
                await logger.log(f"Max: Empty document URL for user {session.user_id}")
                continue
            # Проверка размера (2 ГБ - лимит Max, но наш бот может иметь свои лимиты, например 20МБ)
            # В Telegram лимит 20МБ для ботов, для Max можно оставить или настроить в конфиге.
            # Используем логику из Telegram версии (20МБ) для единообразия,
            # либо доверяем BaseMediaHandler (но он пока не проверяет размер, это делал хендлер)
            if file_size > 20 * 1024 * 1024:
                msg = await get_translation('big-file', lang=session.lang)
                await max_client.send_message(session.user_id, msg)
                continue

            success, desc, next_step_key = await BaseMediaHandler.process_document(
                chat=session,
                file_path_url=doc_url,
                folder='max_documents'
            )

            if success:
                checklist_completed = await session.next_step(next_step_key)
                if checklist_completed:
                    await max_client.send_message(session.user_id, "✅")
                else:
                    await max_client.send_message(session.user_id, "✅")
                    await send_step_message(session)
            else:
                await max_client.send_message(session.user_id, desc or "Error processing document")

        # 4. Геопозиция (Location)
        elif att_type == 'location':
            lat = att.get('latitude')
            lon = att.get('longitude')

            if lat is None or lon is None:

                msg = await get_translation("location-error", lang=session.lang)
                await max_client.send_message(session.user_id, msg)
                continue

            success, desc, next_step_key = await BaseMediaHandler.process_location(
                chat=session,
                lat=lat,
                lon=lon
            )

            if success:
                checklist_completed = await session.next_step(next_step_key)
                # В Max Reply-кнопки (Request Geo) убираются отправкой новой клавиатуры или null.
                # send_step_message отправит новую клавиатуру следующего шага, что заменит старую.
                if checklist_completed:
                    await max_client.send_message(session.user_id, "✅", keyboard=None)
                else:
                    await max_client.send_message(session.user_id, "✅")
                    await send_step_message(session)
            else:
                msg = session.checklist_line.get('comment', 'Error')
                await max_client.send_message(session.user_id, desc or msg)

        else:
            # Неизвестный тип вложения
            await logger.log(f"Max: Unsupported attachment type {att_type}")
            # Можно отправить сообщение пользователю, если это критично
