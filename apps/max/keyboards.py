from typing import Dict, Optional, Any, List
from common.keyboards import BaseKeyboardGenerator
from utils.helpers import get_translation
import calendar
from datetime import date, timedelta


class MaxKeyboards(BaseKeyboardGenerator):
    """
    Генератор клавиатур для Max Messenger.
    Формирует словари, соответствующие структуре 'payload' вложения 'inline_keyboard'.
    """

    @staticmethod
    def _create_button(text: str, payload: Optional[str] = None, btn_type: str = "callback", **kwargs) -> Dict[
        str, Any]:
        """
        Реализация создания кнопки для Max API.
        Возвращает словарь формата: {"type": "...", "text": "...", "payload": "..."}
        """
        btn = {"type": btn_type, "text": text}
        # Payload нужен только для callback кнопок
        if btn_type == "callback" and payload is not None:
            btn["payload"] = payload

        # Дополнительные поля (например, quick: true для гео, url для ссылок)
        if kwargs:
            btn.update(kwargs)

        return btn

    # --- Публичные методы, использующие общую логику (возвращают Dict) ---

    @classmethod
    async def get_select(cls, options: Dict, selectors_data: Dict[str, int], lang: str,
                         names: Optional[Dict] = None, select_query: Optional[str] = None) -> Dict[str, Any]:
        rows = await cls._build_select_rows(options, selectors_data, lang, names, select_query)
        return {"buttons": rows}

    @classmethod
    async def get_choice(cls, options: Dict, lang: str, names: Optional[Dict] = None,
                         select_query: Optional[str] = None) -> Dict[str, Any]:
        rows = await cls._build_choice_rows(options, lang, names, select_query)
        return {"buttons": rows}

    @classmethod
    async def get_toggle(cls, lang: str) -> Dict[str, Any]:
        rows = await cls._build_toggle_rows(lang)
        return {"buttons": rows}

    @classmethod
    async def get_rating(cls, lang: str) -> Dict[str, Any]:
        rows = await cls._build_rating_rows(lang)
        return {"buttons": rows}

    @classmethod
    async def get_navigation(cls, lang: str, has_next: bool = True, has_back: bool = True) -> Optional[Dict[str, Any]]:
        buttons = []
        if has_back:
            text = await cls._get_std_btn('back', lang)
            buttons.append(cls._create_button(text, "back"))
        if has_next:
            text = await cls._get_std_btn('next', lang)
            buttons.append(cls._create_button(text, "next"))

        return {"buttons": [buttons]} if buttons else None

    # --- Специфичные методы (Спиннеры, Карты, Календарь, Гео) ---

    @classmethod
    async def get_spinner(cls, current_val: int, key: str, lang: str) -> Dict[str, Any]:
        """
        Спиннер: [-] [Значение] [+] + Навигация
        """
        back_text = await cls._get_std_btn('back', lang)
        next_text = await cls._get_std_btn('next', lang)

        row1 = [
            cls._create_button('-', f'decrement_{key}'),
            cls._create_button(str(current_val), 'do_nothing'),
            cls._create_button('+', f'increment_{key}')
        ]
        row2 = [
            cls._create_button(back_text, "back"),
            cls._create_button(next_text, "next")
        ]
        return {"buttons": [row1, row2]}

    @classmethod
    async def get_multi_spinner(cls, options: Dict, spinners_data: Dict[str, int], checklist_key: str, lang: str,
                                names: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Мульти-спиннер (несколько счетчиков на одном экране).
        """
        keyboard_rows = []

        if 'title' in options:
            keyboard_rows.append([cls._create_button(options['title'], 'do_nothing')])

        spinners_config = options.get('spinners', [])

        for i in range(0, len(spinners_config), 2):
            row_top = []  # Имена
            row_bottom = []  # Кнопки управления (- 0 +)

            # Левый спиннер
            await cls._add_spinner_to_row(spinners_config[i], spinners_data, row_top, row_bottom, lang, names)

            # Правый спиннер (если есть)
            if i + 1 < len(spinners_config):
                await cls._add_spinner_to_row(spinners_config[i + 1], spinners_data, row_top, row_bottom, lang, names)

            keyboard_rows.append(row_top)
            keyboard_rows.append(row_bottom)

        confirm_text = await cls._get_std_btn('confirm', lang)
        keyboard_rows.append([cls._create_button(confirm_text, f"multi-spinner_{checklist_key}")])

        return {"buttons": keyboard_rows}

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
    def get_calendar(options: Dict, lang: str, calendar_callback=None) -> Dict[str, Any]:
        """
        Упрощенная реализация календаря для Max (список дней текущего месяца).
        Добавлена локализация (ru/en) и безопасная проверка границ min/max.
        """
        # Если передан коллбек (смена месяца), парсим его.
        # Формат: cal_YEAR_MONTH
        min_date = date.fromisoformat(options['min']) if 'min' in options else None
        max_date = date.fromisoformat(options['max']) if 'max' in options else None
        curr_date = date.fromisoformat(options['current']) if 'current' in options else date.today()

        if calendar_callback and calendar_callback.startswith("cal_"):
            parts = calendar_callback.split("_")
            if len(parts) == 3:
                try:
                    year, month = int(parts[1]), int(parts[2])
                    curr_date = date(year, month, 1)
                except ValueError:
                    pass

        year, month = curr_date.year, curr_date.month
        month_days = calendar.monthcalendar(year, month)

        keyboard_rows = []

        # --- ЛОКАЛИЗАЦИЯ ---
        MONTH_NAMES = {
            'ru': {1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь',
                   7: 'Июль', 8: 'Август', 9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'},
            'en': {1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May', 6: 'June',
                   7: 'July', 8: 'August', 9: 'September', 10: 'October', 11: 'November', 12: 'December'}
        }
        WEEK_DAYS = {
            'ru': ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
            'en': ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        }

        # Определяем язык по умолчанию, если пришел неизвестный код
        safe_lang = lang if lang in MONTH_NAMES else 'en'

        # Заголовок с Месяцем и Годом (локализованный)
        month_name = MONTH_NAMES[safe_lang][month]
        keyboard_rows.append([MaxKeyboards._create_button(f"{month_name} {year}", "do_nothing")])

        # Дни недели (локализованные)
        week_header = [MaxKeyboards._create_button(day, "do_nothing") for day in WEEK_DAYS[safe_lang]]
        keyboard_rows.append(week_header)

        # Сетка дней
        for week in month_days:
            row = []
            for day in week:
                if day == 0:
                    row.append(MaxKeyboards._create_button("·", "do_nothing"))
                else:
                    curr_d = date(year, month, day)
                    # БЕЗОПАСНАЯ проверка границ: сравниваем, только если min_date / max_date не None
                    if (min_date and curr_d < min_date) or (max_date and curr_d > max_date):
                        row.append(MaxKeyboards._create_button("·", "do_nothing"))
                    else:
                        # Дата в формате dd_mm_yyyy для отправки в базу
                        date_val = curr_d.strftime("%d_%m_%Y")
                        row.append(MaxKeyboards._create_button(str(day), date_val))
            keyboard_rows.append(row)

        # Навигация по месяцам
        prev_m = curr_date.replace(day=1) - timedelta(days=1)
        next_m = (curr_date.replace(day=28) + timedelta(days=4)).replace(day=1)

        nav_row = [
            MaxKeyboards._create_button("<", f"cal_{prev_m.year}_{prev_m.month}"),
            MaxKeyboards._create_button(">", f"cal_{next_m.year}_{next_m.month}")
        ]
        keyboard_rows.append(nav_row)

        return {"buttons": keyboard_rows}

    @staticmethod
    async def get_map_selection(addresses: List[Any], lang: str) -> Optional[Dict[str, Any]]:
        """
        Клавиатура выбора адреса после поиска на карте.
        """
        keyboard_rows = []
        for text, pos, postal_code in addresses:
            keyboard_rows.append([MaxKeyboards._create_button(text, f"address_{pos}")])

        if not keyboard_rows:
            return None

        return {"buttons": keyboard_rows}

    @classmethod
    async def get_map_confirm(cls, coords: str, lang: str) -> Dict[str, Any]:
        """
        Кнопка подтверждения выбранного адреса.
        """
        confirm_text = await cls._get_std_btn('confirm', lang)
        back_text = await cls._get_std_btn('back', lang)

        row1 = [cls._create_button(confirm_text, f"confirm_address_{coords}")]
        row2 = [cls._create_button(back_text, "back")]

        return {"buttons": [row1, row2]}

    @classmethod
    async def get_geo_request(cls, lang: str) -> Dict[str, Any]:
        """
        Кнопка запроса геопозиции для Max.
        """
        text = await get_translation('send-geoposition', kit='buttons', lang=lang)
        # quick: True отправляет гео без лишних подтверждений
        btn = cls._create_button(text, btn_type="request_geo_location", quick=True)
        return {"buttons": [[btn]]}