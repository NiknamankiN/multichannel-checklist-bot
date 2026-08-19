from typing import Optional, Tuple, Any
from database.repository import repo
from utils.logger import logger

# Простой in-memory кеш для переводов: {(key, kit, lang): "Translation"}
_TRANSLATION_CACHE = {}


async def get_translation(key: str, kit: str = 'multichannel-bot', lang: str = 'ru') -> str:
    """
    Асинхронное получение перевода с кешированием.

    :param key: Ключ перевода (например, 'max-photo')
    :param kit: Набор переводов (по умолчанию 'multichannel-bot')
    :param lang: Язык (по умолчанию 'ru')
    :return: Переведенная строка или сам ключ, если перевод не найден.
    """
    cache_key = (key, kit, lang)

    if cache_key in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[cache_key]

    text = await repo.get_translation_text(key, kit, lang)

    if text:
        _TRANSLATION_CACHE[cache_key] = text
        return text

    await logger.log(f"Translation not found for: {key} ({lang})")
    return key


def is_float(element: Any) -> bool:
    """Проверяет, можно ли преобразовать значение в float."""
    if element is None:
        return False
    try:
        float(element)
        return True
    except ValueError:
        return False


def get_photo_limits(options: Optional[dict]) -> Tuple[int, int]:
    """
    Извлекает лимиты фото из опций шага.
    :param options: Словарь options2 из базы
    :return: (min_photo, max_photo)
    """
    min_photo, max_photo = 0, 1000
    if (options is not None
            and 'min' in options
            and 'max' in options
            and isinstance(options['min'], int)
            and isinstance(options['max'], int)):
        min_photo, max_photo = options['min'], options['max']
    return min_photo, max_photo

def get_spinner_data(spinner_options: Optional[dict]) -> tuple[int, int, int]:
    """
    Возвращает (min, default, max) для спиннера.
    """
    min_spinner, default_spinner, max_spinner = -10000, 0, 10000
    if spinner_options is None:
        return min_spinner, default_spinner, max_spinner
    if "min" in spinner_options:
        min_spinner = spinner_options["min"]
    if "max" in spinner_options:
        max_spinner = spinner_options["max"]
    if "default" in spinner_options:
        default_spinner = spinner_options["default"]
    return min_spinner, default_spinner, max_spinner
