import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from html import escape
from urllib.parse import urlparse

from database.repository import repo
from utils.logger import logger
from config import ONE_DAY_IN_SECONDS



class Session:
    """
    Универсальный класс управления состоянием (для Telegram и Max).
    """
    # Кэш: { (user_id, bot_name): Session }
    _cache: Dict[tuple, 'Session'] = {}

    def __init__(self, user_id: int, bot_name: str, username: str, lang: str):
        self.user_id = user_id  # Бывший chat_id
        self.bot_name = bot_name  # 'telegram' или 'max'
        self.username = username
        self.lang = lang

        # ... (Остальные поля без изменений) ...
        self.checklist_id: Optional[int] = None
        self.current_process: Optional[int] = None
        self.status: Optional[str] = None
        self.step: int = 0
        self.photo_num: int = 0
        self.checklist_line: Optional[Dict[str, Any]] = None
        self.checklist_size: int = 0
        self.checklist_changed: datetime = datetime.now()
        self.bills_sum: float = 0.0
        self.photos_urls: List[str] = []
        self.bad_photos_urls: List[str] = []
        self.cur_spinner: int = 0
        self.spinners_data: Dict[str, int] = {}
        self.selectors_data: Dict[str, int] = {}
        self.choices_data: Dict[str, Any] = {}
        self.ai_request_failed: bool = False

    @classmethod
    async def get_or_create(cls, user_id: int, bot_name: str, username: str, lang: str = 'ru') -> 'Session':
        """
        Фабрика сессий. Ключ кэша теперь составной: (user_id, bot_name).
        """
        cache_key = (user_id, bot_name)

        if cache_key in cls._cache:
            session = cls._cache[cache_key]
            if username: session.username = username
            if lang: session.lang = lang
            return session

        session = cls(user_id, bot_name, username, lang)
        await session._load_from_db()

        cls._cache[cache_key] = session
        return session

    async def _load_from_db(self):
        # Передаем bot_name в репозиторий
        state = await repo.get_user_state(self.bot_name, self.user_id)

        if state:
            # Маппинг полей из БД (порядок должен совпадать с SQL запросом)
            # user_id, bot_type, current_process, checklist_id, status, step, ...
            self.current_process = state[2]
            self.checklist_id = state[3]
            self.status = state[4]
            self.step = state[5] if state[5] is not None else 0
            self.photo_num = state[6] if state[6] is not None else 0
        else:
            await repo.create_new_user(self.bot_name, self.user_id, self.username, self.lang)

        if self.checklist_id:
            await self.load_current_checklist_line()

    async def start_new_checklist(self, checklist_id: int, full_checklist_data: List[Dict]):
        self.checklist_id = checklist_id
        self.checklist_size = len(full_checklist_data)
        self.step = 0
        self.photo_num = 0
        self.bills_sum = 0
        self.checklist_changed = datetime.now()
        self.photos_urls.clear()
        self.bad_photos_urls.clear()
        self.spinners_data.clear()
        self.selectors_data.clear()

        # Очистка и сохранение с учетом bot_name
        await repo.clear_checklist(self.bot_name, self.user_id)

        for pos, line in enumerate(full_checklist_data):
            line = self._normalize_line(line)
            if line.get('type') == 'toggle' and isinstance(line.get('options2'), dict):
                url = line['options2'].get('url')
                parsed = urlparse(url)
                if parsed.scheme in {"http", "https"}:
                    line["comment"] = (
                        f'<a href="{escape(url, quote=True)}">'
                        f'{escape(line["comment"])}</a>'
                    )

            await repo.save_checklist_line(self.bot_name, self.user_id, pos, line)

        await self.load_current_checklist_line()

    def _normalize_line(self, line: Dict[str, Any]) -> Dict[str, Any]:
        """
        Приводит структуру шага чеклиста к безопасному виду.
        Гарантирует, что options2 и names всегда являются словарями.
        """
        if not line:
            return {}

        # Обработка options2
        opt2 = line.get('options2')
        if opt2 is None:
            line['options2'] = {}
        elif isinstance(opt2, str):
            try:
                # Если options2 пришел как строка (JSON), парсим его
                line['options2'] = json.loads(opt2)
            except (json.JSONDecodeError, TypeError):
                # Если парсинг не удался, ставим пустой словарь и логируем
                print(f"Warning: Invalid options2 JSON for step {line.get('key')}: {opt2}")
                line['options2'] = {}
        elif not isinstance(opt2, dict):
            # Если это число или список (чего быть не должно), сбрасываем
            line['options2'] = {}

        # Аналогично обрабатываем names
        names = line.get('names')
        if names is None:
            line['names'] = {}
        elif isinstance(names, str):
            try:
                line['names'] = json.loads(names)
            except (json.JSONDecodeError, TypeError):
                line['names'] = {}
        elif not isinstance(names, dict):
            line['names'] = {}

        return line

    async def load_current_checklist_line(self):
        if self.checklist_id is None:
            return

        # Передаем bot_name
        line_data = await repo.get_checklist_line(self.bot_name, self.user_id, self.step)

        if line_data:
            try:
                raw_line = json.loads(line_data)
                self.checklist_line = self._normalize_line(raw_line)
            except json.JSONDecodeError:
                self.checklist_line = None
        else:
            definition = await repo.get_checklist_definition(self.checklist_id, self.lang)
            if definition:
                await self.start_new_checklist(self.checklist_id, definition)

    async def next_step(self, next_step_key: str = None) -> bool:
        if next_step_key:
            # Передаем bot_name
            target_step = await repo.find_step_by_key(self.bot_name, self.user_id, next_step_key)
            if target_step is not None:
                self.step = target_step
            else:
                await logger.log(f"Step key {next_step_key} not found")
                self.step += 1
        else:
            self.step += 1

        self.photo_num = 0
        self.cur_spinner = 0
        self.photos_urls.clear()
        self.bad_photos_urls.clear()
        self.bills_sum = 0

        await self.save_field('step', self.step)
        await self.save_field('photo_number', 0)

        count = await repo.get_checklist_size(self.bot_name, self.user_id)
        if self.step >= count:
            await self.complete_checklist()
            return True

        await self.load_current_checklist_line()
        return False

    async def back_step(self):
        if self.step > 0:
            self.step -= 1
            self.photo_num = 0
            self.cur_spinner = 0
            self.photos_urls.clear()
            self.bad_photos_urls.clear()

            await self.save_field('step', self.step)
            await self.load_current_checklist_line()

    async def complete_checklist(self):
        # Завершение в Postgres не требует bot_name (там только ID чеклиста)
        # НО локальная очистка требует
        await repo.complete_checklist(self.bot_name, self.user_id, self.checklist_id, self.lang)
        self.checklist_id = None
        self.checklist_line = None
        await self.save_field('checklist_id', None)

    async def save_field(self, field: str, value: Any):
        # Передаем bot_name
        await repo.update_user_field(self.bot_name, self.user_id, field, value)

        if field == 'step':
            self.step = value
        elif field == 'photo_number':
            self.photo_num = value
        elif field == 'checklist_id':
            self.checklist_id = value

    def is_active(self) -> bool:
        if not self.checklist_id:
            return False
        delta = datetime.now() - self.checklist_changed
        return delta.total_seconds() < ONE_DAY_IN_SECONDS
