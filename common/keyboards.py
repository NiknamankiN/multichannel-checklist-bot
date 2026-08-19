from typing import Optional, Dict, Any, List, Set, Union
from rapidfuzz import process, fuzz
from abc import ABC, abstractmethod

from utils.helpers import get_translation


class BaseKeyboardGenerator(ABC):
    """
    Базовый класс для генерации клавиатур.
    Содержит общую логику парсинга настроек чеклиста.
    """

    @staticmethod
    @abstractmethod
    def _create_button(text: str, payload: str, **kwargs) -> Any:
        """
        Абстрактный метод создания кнопки.
        Должен быть реализован в Telegram/Max классах.
        """
        pass

    @classmethod
    async def _get_std_btn(cls, key: str, lang: str) -> str:
        return await get_translation(key, kit='buttons', lang=lang)

    @staticmethod
    def _get_name_from_dict(key: str, names: Optional[Dict]) -> Optional[str]:
        if names and key in names:
            return names[key].get('name')
        return None

    @classmethod
    async def _resolve_button_name(cls, item: Dict, lang: str, names: Optional[Dict]) -> str:
        key = item['key']
        name = cls._get_name_from_dict(key, names)

        if not name and 'name' in item:
            name = item['name']

        if not name:
            name = await get_translation(key, kit='buttons', lang=lang)

        return name

    @classmethod
    async def _get_filtered_keys(cls, options: Dict, lang: str, query: str, names: Optional[Dict], limit: int = 10) -> \
    Set[str]:
        candidates = []
        row_idx = 1
        while f"row {row_idx}" in options:
            for item in options[f"row {row_idx}"]:
                name = await cls._resolve_button_name(item, lang, names)
                candidates.append((name, item['key']))
            row_idx += 1

        if not candidates:
            return set()

        choices = [c[0] for c in candidates]
        results = process.extract(query, choices, limit=limit, scorer=fuzz.WRatio, score_cutoff=55)
        return {candidates[res[2]][1] for res in results}

    # --- Общие генераторы рядов ---

    @classmethod
    async def _build_select_rows(cls, options: Dict, selectors_data: Dict[str, int], lang: str,
                                 names: Optional[Dict] = None, select_query: Optional[str] = None) -> List[List[Any]]:
        rows = []
        row_idx = 1
        MAX_BUTTONS = 10
        buttons_count = 0

        allowed_keys = None
        if select_query:
            allowed_keys = await cls._get_filtered_keys(options, lang, select_query, names, limit=MAX_BUTTONS)

        while f"row {row_idx}" in options:
            row_items = options[f"row {row_idx}"]
            current_row_btns = []

            for item in row_items:
                key = item['key']
                if allowed_keys is not None and key not in allowed_keys:
                    continue

                unchangeable = item.get('unchangeable', False)
                name = await cls._resolve_button_name(item, lang, names)
                callback = f"select_{key}"

                if unchangeable:
                    name = "☑️ " + name
                    callback = "do_nothing"
                elif selectors_data.get(key, 0) == 1:
                    name = "✅ " + name

                current_row_btns.append(cls._create_button(name, callback))
                buttons_count += 1

                if buttons_count >= MAX_BUTTONS:
                    break

            if current_row_btns:
                rows.append(current_row_btns)

            if buttons_count >= MAX_BUTTONS:
                rows.append([cls._create_button("...", "do_nothing")])
                break
            row_idx += 1

        # Если поиск ничего не дал
        if select_query and buttons_count == 0:
            not_found_text = await get_translation('results-not-found', kit='multichannel-bot', lang=lang)
            rows.append([cls._create_button(not_found_text, "do_nothing")])

        # Кнопка подтверждения
        if options.get('choice', 1000) > 1:
            confirm_text = await cls._get_std_btn('confirm', lang)
            rows.append([cls._create_button(confirm_text, "select_confirm")])

        return rows

    @classmethod
    async def _build_choice_rows(cls, options: Dict, lang: str, names: Optional[Dict] = None,
                                 select_query: Optional[str] = None) -> List[List[Any]]:
        rows = []
        row_idx = 1
        MAX_BUTTONS = 5
        buttons_count = 0

        allowed_keys = None
        if select_query:
            allowed_keys = await cls._get_filtered_keys(options, lang, select_query, names, limit=MAX_BUTTONS)

        while f"row {row_idx}" in options:
            row_items = options[f"row {row_idx}"]
            current_row_btns = []

            for item in row_items:
                key = item['key']
                if allowed_keys is not None and key not in allowed_keys:
                    continue

                name = await cls._resolve_button_name(item, lang, names)
                callback = f"confirm_choice_{key}"
                current_row_btns.append(cls._create_button(name, callback))
                buttons_count += 1

                if buttons_count >= MAX_BUTTONS:
                    break

            if current_row_btns:
                rows.append(current_row_btns)

            if buttons_count >= MAX_BUTTONS:
                rows.append([cls._create_button("...", "do_nothing")])
                break
            row_idx += 1

        if select_query and buttons_count == 0:
            not_found_text = await get_translation('results-not-found', kit='multichannel-bot', lang=lang)
            rows.append([cls._create_button(not_found_text, "do_nothing")])

        back_text = await cls._get_std_btn('back', lang)
        rows.append([cls._create_button(back_text, "back")])

        return rows

    @classmethod
    async def _build_toggle_rows(cls, lang: str) -> List[List[Any]]:
        yes_text = await cls._get_std_btn('yes', lang)
        no_text = await cls._get_std_btn('no', lang)
        back_text = await cls._get_std_btn('back', lang)

        return [
            [
                cls._create_button(no_text, "False"),
                cls._create_button(yes_text, "True")
            ],
            [cls._create_button(back_text, "back")]
        ]

    @classmethod
    async def _build_rating_rows(cls, lang: str) -> List[List[Any]]:
        back_text = await cls._get_std_btn('back', lang)
        return [
            [cls._create_button(str(i), f"rating_{i}") for i in range(1, 6)],
            [cls._create_button(back_text, "back")]
        ]
