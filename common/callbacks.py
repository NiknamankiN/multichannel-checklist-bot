from typing import Tuple, Optional, Any
from common.session import Session
from database.repository import repo
from common.validators import check_toggle, is_file_required
from utils.helpers import get_translation, get_photo_limits, get_spinner_data
from utils.logger import logger


class ChecklistLogic:
    """
    Общая бизнес-логика обработки действий пользователя в чеклисте.
    Не зависит от платформы (Telegram/Max).
    """

    @staticmethod
    async def on_back(chat: Session) -> None:
        """Обработка нажатия Назад"""
        await chat.back_step()

    @staticmethod
    async def on_next(chat: Session) -> Tuple[bool, Optional[str], bool]:
        """
        Обработка нажатия Далее.
        Возвращает: (success, error_message, checklist_completed)
        """
        line = chat.checklist_line
        step_type = line.get('type')
        options = line.get('options2') or {}

        # 1. Валидация (фото, видео)
        if step_type == 'photo':
            min_photo, _ = get_photo_limits(options)
            if chat.photo_num < min_photo:
                msg_tpl = await get_translation('min-photo', lang=chat.lang)
                return False, msg_tpl.replace('{min-photo}', str(min_photo)), False

            if 'bills-sum-step' in options:
                sum_step_key = options['bills-sum-step']
                target_amount_val = await repo.get_step_value(chat.user_id, chat.checklist_id, sum_step_key)

                if target_amount_val is not None:
                    try:
                        target_amount = float(target_amount_val)
                        if abs(target_amount - chat.bills_sum) > 10:
                            msg = await get_translation('wrong-bills-photo', lang=chat.lang)
                            return False, msg, False
                    except ValueError:
                        pass

        if (step_type in ('video', 'document') and is_file_required(options)) or step_type == 'map':
            msg = await get_translation('wrong-answer', lang=chat.lang)
            return False, msg, False

        # 2. Сохранение данных
        success, desc, next_step_key = False, None, None

        if step_type == 'spinner':
            success, desc, next_step_key = await repo.update_checklist_step(
                bot_name=chat.bot_name,
                chat_id=chat.user_id,
                checklist_id=chat.checklist_id,
                step_key=line['key'],
                rating=chat.cur_spinner,
                lang=chat.lang
            )
        elif step_type == 'photo':
            photo_urls = chat.photos_urls
            photo_state = 'complete'
            if options.get('ai-check'):
                photo_state = 'confirmed'
            if not photo_urls and chat.bad_photos_urls:
                photo_urls = chat.bad_photos_urls
                photo_state = 'error'

            photos_str = '\r\n'.join(photo_urls) if photo_urls else None

            success, desc, next_step_key = await repo.update_checklist_step(
                bot_name=chat.bot_name,
                chat_id=chat.user_id,
                checklist_id=chat.checklist_id,
                step_key=line['key'],
                value=photos_str,
                status=photo_state,
                lang=chat.lang
            )
        else:
            # Для остальных типов (пропуск шага)
            success, desc, next_step_key = await repo.update_checklist_step(
                bot_name=chat.bot_name,
                chat_id=chat.user_id,
                checklist_id=chat.checklist_id,
                step_key=line['key'],
                status='complete',
                lang=chat.lang
            )

        if success:
            is_completed = await chat.next_step(next_step_key)
            return True, None, is_completed

        return False, desc or "Error", False

    @staticmethod
    async def on_toggle(chat: Session, value: bool) -> Tuple[bool, Optional[str], bool]:
        options = chat.checklist_line.get('options2')

        if not check_toggle(value, options):
            msg = await get_translation('wrong-answer', lang=chat.lang)
            return False, msg, False

        success, desc, next_step_key = await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            toggle=value,
            lang=chat.lang
        )

        if success:
            is_completed = await chat.next_step(next_step_key)
            return True, None, is_completed
        return False, desc, False

    @staticmethod
    async def on_rating(chat: Session, value: int) -> Tuple[bool, Optional[str], bool]:
        success, desc, next_step_key = await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            rating=value,
            lang=chat.lang
        )
        if success:
            is_completed = await chat.next_step(next_step_key)
            return True, None, is_completed
        return False, desc, False

    @staticmethod
    async def on_spinner_change(chat: Session, action: int) -> Tuple[bool, str]:
        """
        Изменяет значение спиннера в сессии.
        Возвращает (success, error_message).
        """
        options = chat.checklist_line.get('options2')
        min_val, default_val, max_val = get_spinner_data(options)

        if chat.cur_spinner is None:
            chat.cur_spinner = default_val

        new_val = chat.cur_spinner + action

        if min_val <= new_val <= max_val:
            chat.cur_spinner = new_val
            return True, ""
        else:
            msg_tpl = await get_translation('spinner-out-range', kit='errors', lang=chat.lang)
            msg = msg_tpl.replace('{min-num}', str(min_val)).replace('{max-num}', str(max_val))
            return False, msg

    @staticmethod
    async def on_multi_spinner_change(chat: Session, key: str, action: int) -> Tuple[bool, str]:
        """
        Изменяет значение конкретного элемента в мульти-спиннере.
        :param key: Ключ элемента (из options['spinners'])
        :param action: +1 или -1
        """
        options = chat.checklist_line.get('options2') or {}
        spinners_conf = options.get('spinners', [])

        # Ищем конфигурацию конкретного спиннера
        conf = next((s for s in spinners_conf if s['key'] == key), None)

        if not conf:
            return False, "Item not found"

        current = chat.spinners_data.get(key, conf.get('default', 0))
        new_val = current + action

        min_val = conf.get('min', -10000)
        max_val = conf.get('max', 10000)

        if min_val <= new_val <= max_val:
            chat.spinners_data[key] = new_val
            return True, ""
        else:
            msg_tpl = await get_translation('spinner-out-range', kit='errors', lang=chat.lang)
            msg = msg_tpl.replace('{min-num}', str(min_val)).replace('{max-num}', str(max_val))
            return False, msg

    @staticmethod
    async def on_select_toggle(chat: Session, key: str) -> Tuple[bool, Optional[str]]:
        options = chat.checklist_line.get('options2') or {}
        max_choice = options.get('choice', 1000)

        current = chat.selectors_data.get(key, 0)
        new_val = 1 if current == 0 else 0

        if new_val == 1:
            current_count = sum(1 for v in chat.selectors_data.values() if v == 1)
            if current_count >= max_choice:
                msg = await get_translation('many-select-alert', kit='multichannel-bot', lang=chat.lang)
                return False, msg.replace('{num}', str(max_choice))

        chat.selectors_data[key] = new_val
        return True, None

    @staticmethod
    async def on_select_confirm(chat: Session) -> Tuple[bool, Optional[str], bool]:
        options = chat.checklist_line.get('options2') or {}

        selected_keys = []
        row = 1
        while f"row {row}" in options:
            for item in options[f"row {row}"]:
                k = item['key']
                is_selected = chat.selectors_data.get(k, item.get('default', 0)) == 1
                is_unchangeable = item.get('unchangeable', False)
                if is_selected or is_unchangeable:
                    selected_keys.append(k)
            row += 1

        result_str = ",".join(selected_keys)

        return await ChecklistLogic._save_value_step(chat, result_str)

    @staticmethod
    async def on_choice(chat: Session, key: str) -> Tuple[bool, Optional[str], bool]:
        return await ChecklistLogic._save_value_step(chat, key)

    @staticmethod
    async def on_save_value(chat: Session, value: Any, json_data: Any = None) -> Tuple[bool, Optional[str], bool]:
        if json_data is not None:
            return await ChecklistLogic._save_json_step(chat, json_data)
        return await ChecklistLogic._save_value_step(chat, value)

    @staticmethod
    async def _save_value_step(chat: Session, value: str) -> Tuple[bool, Optional[str], bool]:
        success, desc, next_step_key = await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            value=value,
            lang=chat.lang
        )
        if success:
            is_comp = await chat.next_step(next_step_key)
            return True, None, is_comp
        return False, desc, False

    @staticmethod
    async def _save_json_step(chat: Session, data: Any) -> Tuple[bool, Optional[str], bool]:
        success, desc, next_step_key = await repo.update_checklist_step(
            bot_name=chat.bot_name,
            chat_id=chat.user_id,
            checklist_id=chat.checklist_id,
            step_key=chat.checklist_line['key'],
            json_data=data,
            lang=chat.lang
        )
        if success:
            is_comp = await chat.next_step(next_step_key)
            return True, None, is_comp
        return False, desc, False
