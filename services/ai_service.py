from typing import Optional, Tuple
from utils.logger import logger
from utils.helpers import get_translation
from services.http_client import http_client


class AIService:
    BASE_URL = "http://some-ai-service"
    PROMPT_KIT = "ai-prompts"

    async def check_photo(self, step_key: str, photo_url: str, options: dict, lang: str = 'ru') -> Tuple[bool, float]:
        """
        Главный метод проверки фото.
        Определяет, нужно ли проверять чек (bill) или соответствие предмета описанию (ai-check).

        :return: (is_valid, bill_amount)
                 is_valid: Прошла ли проверка
                 bill_amount: Сумма чека (если это был чек), иначе 0.0
        """
        # Если проверка не включена в опциях шага
        if 'ai-check' not in options or not options['ai-check']:
            return True, 0.0

        # Если это шаг с чеками (bill)
        if options.get('bill'):
            amount = await self._analyze_bill(photo_url, lang)
            if amount is not None:
                return True, amount
            return False, 0.0

        # Обычная проверка по ключу шага (соответствие предмету или описанию)
        is_valid = await self._analyze_image_by_key(step_key, photo_url, lang)
        return is_valid, 0.0

    async def _analyze_bill(self, photo_url: str, lang: str) -> Optional[float]:
        """
        Анализирует фото чека и возвращает сумму.
        """
        # Получение промпта из БД (через кеширующий хелпер)
        prompt = await get_translation('bills-total', kit=self.PROMPT_KIT, lang=lang)

        payload = {
            "image_url": photo_url,
            "prompt": prompt
        }

        # Используется глобальный клиент с таймаутом 30 секунд
        response = await http_client.post(f"{self.BASE_URL}/analyze_receipt_total/", json=payload, timeout=60.0)

        # Если вернулся None, значит была ошибка сети или таймаут (уже залогировано в http_client)
        if response is None:
            return None

        if response.status_code != 200:
            await logger.log(f"AI Bill Error: {response.status_code}")
            return None

        try:
            json_response = response.json()
            await logger.log(f"AI bill analysis completed")

            if 'result' in json_response and json_response['result']:
                return float(json_response['result'])
        except Exception as e:
            await logger.log(f"Error parsing bill JSON in AI: {e}")

        return None

    async def _analyze_image_by_key(self, step_key: str, photo_url: str, lang: str) -> bool:
        """
        Проверяет фото по ключу шага.
        Используется для проверки соответствия сфотографированного предмета или окружения описанию.
        """
        # Получение промпта для конкретного шага
        prompt = await get_translation(step_key, kit=self.PROMPT_KIT, lang=lang)

        payload = {
            "key": step_key,
            "image": photo_url,
            "prompt": prompt
        }

        # Использование глобального клиента с таймаутом 30 секунд
        response = await http_client.post(f"{self.BASE_URL}/analyze_image_key/", json=payload, timeout=30.0)

        # Fail-safe: если сервис лежит (сетевая ошибка) проверка считается пройденной
        if response is None:
            return True

        if response.status_code != 200:
            await logger.log(f"AI Photo Check Error: {response.status_code}")
            return True

        try:
            json_response = response.json()
            await logger.log(f"AI photo check completed")

            if 'result' in json_response:
                result = json_response.get("result")

                if isinstance(result, bool):
                    return result

                if isinstance(result, str):
                    return result.strip().lower() == "true"

                return False
        except Exception as e:
            await logger.log(f"Error parsing photo check JSON in AI: {e}")
        # Если что-то пошло не так при разборе, но ответ был 200, по умолчанию считается успешным
        return True


ai_service = AIService()
