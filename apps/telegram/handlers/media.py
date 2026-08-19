from typing import Any
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from utils.logger import tg_logger as logger
from utils.helpers import get_translation
from apps.telegram.handlers.messages import send_step_message
from common.media import BaseMediaHandler


async def handle_photo(update: Update, chat: Any) -> str:
    """
    Хендлер фото для Telegram.
    """
    # 1. Извлекаем файл
    try:
        photo_file = await update.message.photo[-1].get_file()
    except Exception as e:
        await logger.log(f"Telegram get_file error: {e}")
        return await get_translation('photo-error', lang=chat.lang)

    # 2. Вызываем общую логику
    # file_path в Telegram - это относительный путь, который storage_service умеет скачивать
    result_text = await BaseMediaHandler.process_photo(
        chat=chat,
        file_path_url=photo_file.file_path,
        unique_file_id=photo_file.file_unique_id,
        folder='telegram_photo'
    )

    return result_text


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Any):
    """
    Хендлер видео для Telegram.
    """
    video = update.message.video
    # Проверка размера (бизнес-логика, но специфична для транспорта Telegram API limits)
    if video.file_size and video.file_size >= 20971520:  # 20MB limit
        msg = await get_translation('big-video', lang=chat.lang)
        await update.message.reply_text(msg)
        return

    try:
        video_file = await video.get_file()

        # Вызываем общую логику
        success, desc, next_step_key = await BaseMediaHandler.process_video(
            chat=chat,
            file_path_url=video_file.file_path,
            folder='telegram_video'
        )

        # Обработка результата (UI)
        if success:
            await logger.log(f"Video uploaded for step {chat.checklist_line['key']}")
            checklist_completed = await chat.next_step(next_step_key)
            if checklist_completed:
                await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
            else:
                await send_step_message(context, chat)
        else:
            await update.message.reply_text(desc or "Error updating checklist")

    except Exception as e:
        await logger.log(f"Video handling error: {e}")
        msg = await get_translation('video-error', lang=chat.lang)
        await update.message.reply_text(msg)


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Any):
    """
    Хендлер локации для Telegram.
    """
    lat = update.message.location.latitude
    lon = update.message.location.longitude

    # Вызываем общую логику
    success, desc, next_step_key = await BaseMediaHandler.process_location(chat, lat, lon)

    if success:
        checklist_completed = await chat.next_step(next_step_key)
        await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())

        if not checklist_completed:
            await send_step_message(context, chat)
    else:
        msg = chat.checklist_line.get('comment', 'Error')
        await update.message.reply_text(desc or msg)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, chat: Any):
    """
    Хендлер документов для Telegram.
    """
    doc = update.message.document
    if doc.file_size and doc.file_size >= 20971520:
        msg = await get_translation('big-file', lang=chat.lang)
        await update.message.reply_text(msg)
        return

    try:
        doc_file = await doc.get_file()

        # Вызываем общую логику
        success, desc, next_step_key = await BaseMediaHandler.process_document(
            chat=chat,
            file_path_url=doc_file.file_path,
            folder='telegram_documents'
        )

        if success:
            checklist_completed = await chat.next_step(next_step_key)
            if checklist_completed:
                await update.message.reply_text("✅", reply_markup=ReplyKeyboardRemove())
            else:
                await send_step_message(context, chat)
        else:
            await update.message.reply_text(desc or "Error")

    except Exception as e:
        await logger.log(f"Document handling error: {e}")
        msg = await get_translation('document-error', lang=chat.lang)
        await update.message.reply_text(msg)