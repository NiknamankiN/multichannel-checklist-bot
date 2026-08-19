from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram_bot_calendar import DetailedTelegramCalendar
from datetime import date
from typing import Dict, Optional, Any, List

from common.keyboards import BaseKeyboardGenerator
from utils.helpers import get_translation


class Keyboards(BaseKeyboardGenerator):

    @staticmethod
    def _create_button(text: str, payload: str, **kwargs) -> InlineKeyboardButton:
        """Реализация создания кнопки для Telegram"""
        return InlineKeyboardButton(text, callback_data=payload)

    # --- Публичные методы, использующие общую логику из BaseKeyboardGenerator ---

    @classmethod
    async def get_select(cls, options: Dict, selectors_data: Dict[str, int], lang: str,
                         names: Optional[Dict] = None, select_query: Optional[str] = None) -> InlineKeyboardMarkup:
        rows = await cls._build_select_rows(options, selectors_data, lang, names, select_query)
        return InlineKeyboardMarkup(rows)

    @classmethod
    async def get_choice(cls, options: Dict, lang: str, names: Optional[Dict] = None,
                         select_query: Optional[str] = None) -> InlineKeyboardMarkup:
        rows = await cls._build_choice_rows(options, lang, names, select_query)
        return InlineKeyboardMarkup(rows)

    @classmethod
    async def get_toggle(cls, lang: str) -> InlineKeyboardMarkup:
        rows = await cls._build_toggle_rows(lang)
        return InlineKeyboardMarkup(rows)

    @classmethod
    async def get_rating(cls, lang: str) -> InlineKeyboardMarkup:
        rows = await cls._build_rating_rows(lang)
        return InlineKeyboardMarkup(rows)

    @classmethod
    async def get_navigation(cls, lang: str, has_next: bool = True, has_back: bool = True) -> InlineKeyboardMarkup:
        buttons = []
        if has_back:
            text = await cls._get_std_btn('back', lang)
            buttons.append(cls._create_button(text, "back"))
        if has_next:
            text = await cls._get_std_btn('next', lang)
            buttons.append(cls._create_button(text, "next"))

        return InlineKeyboardMarkup([buttons])

    # --- Специфичные методы (Спиннеры, Карты, Календарь) ---

    @classmethod
    async def get_spinner(cls, current_val: int, key: str, lang: str) -> InlineKeyboardMarkup:
        """
        Спиннер: [-] [Значение] [+] + Навигация
        """
        back_text = await cls._get_std_btn('back', lang)
        next_text = await cls._get_std_btn('next', lang)

        keyboard = [
            [
                cls._create_button('-', f'decrement_{key}'),
                cls._create_button(str(current_val), 'do_nothing'),
                cls._create_button('+', f'increment_{key}')
            ],
            [
                cls._create_button(back_text, "back"),
                cls._create_button(next_text, "next")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    async def get_multi_spinner(cls, options: Dict, spinners_data: Dict[str, int], checklist_key: str, lang: str,
                                names: Optional[Dict] = None) -> InlineKeyboardMarkup:
        """
        Мульти-спиннер. Использует _resolve_button_name из базы.
        """
        keyboard = []

        if 'title' in options:
            keyboard.append([cls._create_button(options['title'], 'do_nothing')])

        spinners_config = options.get('spinners', [])

        for i in range(0, len(spinners_config), 2):
            row_top = []  # Имена
            row_bottom = []  # Кнопки управления (- 0 +)

            # Левый элемент
            await cls._add_spinner_to_row(spinners_config[i], spinners_data, row_top, row_bottom, lang, names)

            # Правый элемент (если есть)
            if i + 1 < len(spinners_config):
                await cls._add_spinner_to_row(spinners_config[i + 1], spinners_data, row_top, row_bottom, lang, names)

            keyboard.append(row_top)
            keyboard.append(row_bottom)

        confirm_text = await cls._get_std_btn('confirm', lang)
        keyboard.append([cls._create_button(confirm_text, f"multi-spinner_{checklist_key}")])

        return InlineKeyboardMarkup(keyboard)

    @classmethod
    async def _add_spinner_to_row(cls, config, data_store, row_top, row_bottom, lang, names):
        key = config['key']
        name = await cls._resolve_button_name(config, lang, names)
        current_val = data_store.get(key, config.get('default', 0))

        row_top.append(cls._create_button(name, "do_nothing"))

        row_bottom.append(cls._create_button('-', f"decrement_{key}"))
        row_bottom.append(cls._create_button(str(current_val), "do_nothing"))
        row_bottom.append(cls._create_button('+', f"increment_{key}"))

    @staticmethod
    async def get_map_selection(addresses: List[Any], lang: str) -> Optional[InlineKeyboardMarkup]:
        """
        Клавиатура выбора адреса после поиска на карте.
        """
        keyboard = []
        for text, pos, postal_code in addresses:
            # pos - это "lon lat" строка
            keyboard.append([InlineKeyboardButton(text, callback_data=f"address_{pos}")])

        if not keyboard:
            return None

        return InlineKeyboardMarkup(keyboard)

    @classmethod
    async def get_map_confirm(cls, coords: str, lang: str) -> InlineKeyboardMarkup:
        """
        Кнопка подтверждения выбранного адреса.
        """
        confirm_text = await cls._get_std_btn('confirm', lang)
        back_text = await cls._get_std_btn('back', lang)

        keyboard = [
            [cls._create_button(confirm_text, f"confirm_address_{coords}")],
            [cls._create_button(back_text, "back")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    async def get_geo_request(lang: str) -> ReplyKeyboardMarkup:
        text = await get_translation('send-geoposition', kit='buttons', lang=lang)
        return ReplyKeyboardMarkup([[KeyboardButton(text, request_location=True)]], resize_keyboard=True)

    @staticmethod
    def get_calendar(options: Dict, lang: str, calendar_callback=None) -> InlineKeyboardMarkup:
        # (Код использования библиотеки DetailedTelegramCalendar без изменений)
        min_date = date.fromisoformat(options['min']) if 'min' in options else None
        max_date = date.fromisoformat(options['max']) if 'max' in options else None
        current_date = date.fromisoformat(options['current']) if 'current' in options else None
        locale = lang if lang in ['en', 'eo', 'ru'] else 'en'
        first_step = 'y'
        if 'step' in options and options['step'] and options['step'][0] in ['d', 'y', 'm']:
            first_step = options['step'][0]

        calendar = DetailedTelegramCalendar(
            calendar_id=0, min_date=min_date, max_date=max_date,
            current_date=current_date, locale=locale
        )
        calendar.first_step = first_step

        if not calendar_callback:
            keyboard, _ = calendar.build()
        else:
            result, keyboard, step = calendar.process(calendar_callback)
            if not keyboard:
                keyboard, _ = calendar.build()
        return keyboard