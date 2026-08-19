import re
from typing import Optional, Dict, Any
from utils.helpers import is_float
from config import ALLOWED_MEDIA_HOSTS
from urllib.parse import urlparse



def check_string(text: str, pattern: Optional[Dict[str, Any]]) -> bool:
    """
    Проверяет строку на соответствие паттерну (длина, регулярное выражение).
    Функция СИНХРОННАЯ.

    :param text: Текст для проверки.
    :param pattern: Словарь настроек из options2 (min, max, regular).
    """
    if pattern is None:
        return True

    # Проверка минимальной длины
    if 'min' in pattern and len(text) < pattern['min']:
        return False

    # Проверка максимальной длины
    if 'max' in pattern and len(text) > pattern['max']:
        return False

    # Проверка по регулярному выражению
    if 'regular' in pattern and pattern['regular']:
        try:
            if not re.fullmatch(pattern['regular'], text):
                return False
        except re.error as exc:
            print(f"Invalid validation regex: {exc}")
            return False

    return True


def check_amount(amount_str: str, pattern: Optional[Dict[str, Any]]) -> bool:
    """
    Проверяет, является ли ввод числом и входит ли оно в диапазон.

    :param amount_str: Строка с числом.
    :param pattern: Словарь настроек (min, max).
    """
    if not is_float(amount_str):
        return False

    value = float(amount_str)

    if pattern is not None:
        if 'min' in pattern and 'max' in pattern:
            min_val = pattern['min']
            max_val = pattern['max']

            if is_float(min_val) and is_float(max_val):
                if value < float(min_val) or value > float(max_val):
                    return False

    return True


def check_toggle(toggle_value: bool, pattern: Optional[Dict[str, Any]]) -> bool:
    """
    Проверяет переключатель (Да/Нет).
    В основном проверяет обязательность положительного ответа (required).
    """
    if pattern is None:
        return True

    # Если стоит флаг required, то значение должно быть True
    if pattern.get('required') and not toggle_value:
        return False

    return True


def is_file_required(options: Optional[Dict[str, Any]]) -> bool:
    """
    Проверяет, обязательно ли прикрепление файла (видео, документа) в текущем шаге.
    """
    if options is None:
        return False

    if options.get('min') == 1:
        return True

    return False

def validate_media_url(file_url: str) -> bool:
    parsed = urlparse(file_url)

    return (
        parsed.scheme == "https"
        and parsed.hostname in ALLOWED_MEDIA_HOSTS
        and not parsed.username
        and not parsed.password
    )
