from typing import Any, Tuple, Optional
from utils.logger import logger
from utils.helpers import get_translation, get_photo_limits
from database.repository import repo
from services.storage_service import storage_service
from services.ai_service import ai_service


class BaseMediaHandler:
    """
    Базовый класс обработчика медиа.
    Содержит бизнес-логику проверки, загрузки и сохранения данных,
    не зависящую от конкретного мессенджера.
    """

    @staticmethod
    async def process_photo(chat: Any, file_path_url: str, unique_file_id: str, folder: str = "bot_photos") -> str:
        """
        Обрабатывает фото: загрузка, AI-проверка, проверка уникальности, обновление состояния сессии.
        Возвращает текст сообщения для пользователя.
        """
        options = chat.checklist_line.get('options2') or {}
        _, max_photo = get_photo_limits(options)

        # 1. Проверка лимита
        if chat.photo_num >= max_photo:
            return await get_translation('max-photo', lang=chat.lang)

        # 2. Загрузка на сервер
        photo_url = await storage_service.upload_file(file_path_url, 'photo', folder)

        if not photo_url:
            await logger.log(f"Storage upload error for user {chat.user_id}")
            return await get_translation('photo-error', lang=chat.lang)

        await logger.log(f"Photo uploaded on step {chat.checklist_line['key']}")

        # 3. AI Проверка
        is_valid, bill_amount = await ai_service.check_photo(
            step_key=chat.checklist_line['key'],
            photo_url=photo_url,
            options=options,
            lang=chat.lang
        )

        if not is_valid:
            chat.bad_photos_urls.append(photo_url)
            await logger.log(f"AI check failed on step {chat.checklist_line['key']}")
            error_template = await get_translation('wrong-item-photo', lang=chat.lang)
            step_name = chat.checklist_line.get('name', '')
            return error_template.replace('{step-name}', step_name.lower())

        if bill_amount > 0:
            chat.bills_sum += bill_amount
            await logger.log(f"Bill added: {bill_amount}, Total: {chat.bills_sum}")

        # 4. Проверка уникальности (хэш/ID файла)
        # Если это чек (bill), уникальность не проверяем (или проверяем иначе)
        is_bill_step = options.get('bill', False)
        if not is_bill_step:
            is_unique = await repo.check_photo_unique(chat.bot_name, chat.user_id, unique_file_id)
            if not is_unique:
                return await get_translation('same-photo-exists', lang=chat.lang)

        # 5. Обновление состояния сессии
        chat.photos_urls.append(photo_url)
        chat.photo_num += 1
        await chat.save_field('photo_number', chat.photo_num)

        return await get_translation('photo-loaded', lang=chat.lang)

    @staticmethod
    async def process_video(chat: Any, file_path_url: str, folder: str = "bot_videos") -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Обрабатывает видео: загрузка и обновление шага чеклиста.
        Возвращает (success, description, next_step_key).
        """
        if chat.checklist_line.get('type') != 'video':
            mgs = await get_translation('wrong-answer', lang=chat.lang)
            return False, mgs, None

        video_url = await storage_service.upload_file(file_path_url, 'video', folder)

        if not video_url:
            msg = await get_translation('video-error', lang=chat.lang)
            return False, msg, None

        # Сохранение в БД
        return await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            value=video_url,
            lang=chat.lang
        )

    @staticmethod
    async def process_document(chat: Any, file_path_url: str, folder: str = "bot_documents") -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Обрабатывает документ.
        """
        if chat.checklist_line.get('type') != 'document':
            msg = await get_translation('wrong-answer', lang=chat.lang)
            return False, msg, None

        doc_url = await storage_service.upload_file(file_path_url, 'document', folder)

        if not doc_url:
            msg = await get_translation('document-error', lang=chat.lang)
            return False, msg, None

        return await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            value=doc_url,
            lang=chat.lang
        )

    @staticmethod
    async def process_location(chat: Any, lat: float, lon: float) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Обрабатывает геопозицию.
        """
        if chat.checklist_line.get('type') != 'geo-position':
            msg = await get_translation('wrong-answer', lang=chat.lang)
            return False, msg, None

        coordinates = f"{lat}, {lon}"

        return await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            value=coordinates,
            lang=chat.lang
        )
