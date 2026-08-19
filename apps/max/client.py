from typing import Optional, Dict, Any, Union, List
from services.http_client import http_client
from utils.logger import max_logger as logger
from config import MAX_BOT_TOKEN, MAX_BOT_API_URL
from common.validators import validate_media_url

MAX_MEDIA_SIZE = 100 * 1024 * 1024

class MaxClient:
    """
    Клиент для взаимодействия с API Max Messenger.
    """

    def __init__(self):
        self.base_url = MAX_BOT_API_URL
        self.headers = {
            "Authorization": MAX_BOT_TOKEN,
            "Content-Type": "application/json"
        }

    @staticmethod
    def _extract_token(data: Any) -> Optional[str]:
        """
        Рекурсивно ищет ключ 'token' в любом JSON-ответе.
        Решает проблему с вложенными ответами вида:
        {'photos': {'ID': {'token': '...token_value...'}}}
        """
        if isinstance(data, dict):
            if 'token' in data and isinstance(data['token'], str):
                return data['token']
            for val in data.values():
                res = MaxClient._extract_token(val)
                if res:
                    return res
        elif isinstance(data, list):
            for item in data:
                res = MaxClient._extract_token(item)
                if res:
                    return res
        return None

    async def upload_media(self, file_url: str, media_type: str) -> Optional[Dict]:
        """
        Скачивает файл по ссылке и загружает его на сервера Max.
        media_type: 'image', 'video', 'audio', 'file'
        Возвращает словарь для добавления в attachments.
        """
        # 1. Скачиваем исходный файл во временную память
        if not validate_media_url(file_url):
            await logger.log(f"File url was not validated. File type {media_type}")
            return None
        try:
            file_response = await http_client.get(file_url, timeout=120.0)
            if not file_response or file_response.status_code != 200:
                await logger.log(f"Max Upload: Failed to download source file, type {media_type}")
                return None
            content_length = file_response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_MEDIA_SIZE:
                await logger.log(f"Max media exceeds size limit, type={media_type}")
                return None

            if len(file_response.content) > MAX_MEDIA_SIZE:
                await logger.log(f"Max media exceeds size limit, type={media_type}")
                return None
            file_bytes = file_response.content
            # Вытаскиваем имя файла из URL, иначе задаем стандартное
            filename = file_url.split('/')[-1].split('?')[0]
            if not filename:
                filename = f"upload.{media_type}"
        except Exception as e:
            await logger.log(f"Max Upload: Error downloading file, type {media_type}: {e}")
            return None

        # 2. Запрашиваем URL для загрузки у Max API
        upload_url_req = f"{self.base_url}/uploads"
        params = {"type": media_type}

        api_response = await http_client.post(upload_url_req, params=params, headers=self.headers)
        if not api_response or api_response.status_code != 200:
            await logger.log(
                f"Max Upload: Failed to get upload URL. {api_response.text if api_response else 'No response'}")
            return None

        api_data = api_response.json()
        upload_url = api_data.get("url")
        video_token = api_data.get("token")  # Токен для видео/аудио приходит на 1-м шаге

        if not upload_url:
            return None

        # 3. Отправляем файл (Multipart Upload)
        # ВАЖНО: для multipart/form-data мы НЕ передаем Content-Type: application/json
        # Библиотека httpx сама установит правильный Content-Type и boundary
        upload_headers = {"Authorization": self.headers["Authorization"]}
        files = {'data': (filename, file_bytes)}

        try:
            up_resp = await http_client.post(upload_url, files=files, headers=upload_headers, timeout=120.0)
            if not up_resp or up_resp.status_code != 200:
                await logger.log(f"Max Upload: File upload failed. {up_resp.text if up_resp else 'No response'}")
                return None

            up_data = up_resp.json()

            # 4. Формируем итоговый payload с токеном
            token = None
            if media_type in ['video', 'audio']:
                token = video_token
            else:
                token = self._extract_token(up_data)

            if token:
                return {
                    "type": media_type,
                    "payload": {"token": token}
                }
            else:
                await logger.log(f"Max Upload: Token not found.")
                return None

        except Exception as e:
            await logger.log(f"Max Upload: Exception during multipart upload: {e}")
            return None

    async def send_message(self, user_id: Union[int, str], text: str, keyboard: Optional[Dict] = None,
                           location: Optional[Dict[str, float]] = None,
                           media_attachments: Optional[List[Dict]] = None) -> Optional[Dict]:
        """
        Отправка сообщения пользователю.
        Поддерживает прикрепление клавиатуры, геолокации и медиафайлов.
        """
        url = f"{self.base_url}/messages"
        if (isinstance(user_id, int) and user_id > 0) or (isinstance(user_id, str) and len(user_id) > 0 and user_id[0] != '-'):
            params = {"user_id": str(user_id)}
        else:
            params = {"chat_id": str(user_id)}

        payload = {
            "text": text,
            "format": "html"
        }
        attachments = []

        # Геолокация
        if location:
            attachments.append({
                "type": "location",
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude")
            })

        # Клавиатура
        if keyboard:
            attachments.append({
                "type": "inline_keyboard",
                "payload": keyboard
            })

        # Медиафайлы (фото, видео, документы)
        if media_attachments:
            attachments.extend(media_attachments)

        if attachments:
            payload["attachments"] = attachments

        response = await http_client.post(url, params=params, json=payload, headers=self.headers)

        if response and response.status_code == 200:
            return response.json()

        if response:
            await logger.log(f"Max send_message failed: {response.status_code} | {response.text}")
        return None

    async def callback_answer(self, user_id: Union[int, str], callback_id: str, keyboard: Optional[Dict] = None) -> \
    Optional[Dict]:
        """
        Ответ на callback(нажатие на кнопку)
        """
        url = f"{self.base_url}/answers?callback_id={callback_id}"
        payload = {}

        if keyboard:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard
            }]
        else:
            payload["attachments"] = []
        callback_payload = {"message": payload}

        response = await http_client.request("POST", url, json=callback_payload, headers=self.headers)

        if response and response.status_code == 200:
            return response.json()

        if response:
            await logger.log(f"Max callback_answer failed: {response.status_code} | {response.text}")
        return None

    async def callback_notification(self, user_id: Union[int, str], callback_id: str, notification_text: str) -> \
    Optional[Dict]:
        """
        Ответ на callback(нажатие на кнопку) в виде уведомления
        """
        url = f"{self.base_url}/answers?callback_id={callback_id}"
        payload = {}

        callback_payload = {"notification": notification_text}

        response = await http_client.request("POST", url, json=callback_payload, headers=self.headers)

        if response and response.status_code == 200:
            return response.json()

        if response:
            await logger.log(f"Max callback_answer failed: {response.status_code} | {response.text}")
        return None

    async def edit_message(self, user_id: Union[int, str], message_id: str, keyboard: Optional[Dict] = None) -> \
    Optional[Dict]:
        """
        Редактирование сообщения.
        """
        url = f"{self.base_url}/messages/{message_id}"
        payload = {}

        if keyboard:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard
            }]
        else:
            payload["attachments"] = []

        response = await http_client.request("PUT", url, json=payload, headers=self.headers)

        if response and response.status_code == 200:
            return response.json()

        if response:
            await logger.log(f"Max edit_message failed: {response.status_code} | {response.text}")
        return None

    # --- Методы управления подписками (Webhooks) ---

    async def get_subscriptions(self) -> List[Dict]:
        """
        Получение списка активных вебхуков.
        GET /subscriptions
        """
        url = f"{self.base_url}/subscriptions"
        response = await http_client.get(url, headers=self.headers)

        if response and response.status_code == 200:
            # Ответ: {"subscriptions": [...]}
            return response.json().get("subscriptions", [])

        if response:
            await logger.log(f"Max get_subscriptions failed: {response.status_code} | {response.text}")
        return []

    async def set_webhook(self, url: str, secret: str = None) -> bool:
        """
        Регистрация нового вебхука.
        POST /subscriptions
        """
        api_url = f"{self.base_url}/subscriptions"
        payload = {
            "url": url,
            # Подписываемся на основные события
            "update_types": ["message_created", "message_callback", "bot_started"],
        }

        if secret:
            payload["secret"] = secret

        response = await http_client.post(api_url, json=payload, headers=self.headers)

        if response and response.status_code == 200:
            res_json = response.json()
            return res_json.get("success", False)

        if response:
            await logger.log(f"Max set_webhook failed: {response.status_code} | {response.text}")
        return False


# Создаем глобальный экземпляр
max_client = MaxClient()
