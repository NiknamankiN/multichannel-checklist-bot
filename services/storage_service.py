from io import BytesIO
from PIL import Image
from config import DRIVE_LINK, API_KEY
from utils.logger import logger
from services.http_client import http_client


class StorageService:
    def __init__(self):
        self.base_url = DRIVE_LINK
        self.api_key = API_KEY

    async def upload_file(self, file_path_url: str, file_type: str, folder: str) -> str | None:
        """
        Загружает файл на сервер.
        """
        params = {
            "url": file_path_url,
            "key": self.api_key,
            "type": file_type,
            "folder": folder
        }

        # Используется глобальный клиент. Он сам поймает таймауты и ошибки сети,
        # вернув None в случае падения запроса на уровне TCP/DNS.
        # timeout=60.0 важен, так как загрузка файлов/видео может идти долго.
        await logger.log(f"Uploading {file_type} to storage, folder={folder}")
        response = await http_client.get(self.base_url, params=params, timeout=60.0)
        if response is not None:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'error_message' not in data and 'photo_url' in data:
                        return data['photo_url']
                    else:
                        await logger.log(f"Storage API logical error")
                except Exception as e:
                    await logger.log(f"Storage API JSON parse error: {e}")
            else:
                await logger.log(f"Storage API status error: {response.status_code}")

        return None

    async def download_image_as_jpeg(self, photo_url: str) -> BytesIO | None:
        """
        Скачивает изображение по ссылке и конвертирует его в JPEG (RGB).
        """
        response = await http_client.get(photo_url, timeout=60.0)

        if response is not None:
            if response.status_code == 200:
                try:
                    bio = BytesIO()
                    img = Image.open(BytesIO(response.content))
                    img.convert('RGB').save(bio, "JPEG")
                    bio.seek(0)
                    return bio
                except Exception as e:
                    await logger.log(f"Image conversion error: {e}")
            else:
                await logger.log(f"Image download failed with status: {response.status_code}")

        return None


storage_service = StorageService()
