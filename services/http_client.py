import httpx
from typing import Optional, Any
from utils.logger import logger
from urllib.parse import urlsplit

def get_safe_host(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.hostname or "unknown"


class GlobalHTTPClient:
    """
    Глобальный HTTP-клиент для всего приложения.
    Обеспечивает переиспользование соединений (Connection Pooling)
    и централизованную обработку ошибок.
    """

    def __init__(self):
        self.client = httpx.AsyncClient()

    async def request(self, method: str, url: str, **kwargs) -> Optional[httpx.Response]:
        """
        Универсальный метод для отправки запросов с перехватом ошибок.
        В kwargs можно передавать params, json, data, timeout и т.д.
        """
        try:
            response = await self.client.request(method, url, **kwargs)
            # Если раскомментировать строку ниже, httpx будет выбрасывать HTTPStatusError для 4xx/5xx кодов
            # response.raise_for_status()
            return response
        except httpx.TimeoutException:
            await logger.log(
                f"HTTP timeout: method={method}, "
                f"host={get_safe_host(url)}"
            )

        except httpx.RequestError as exc:
            # Ошибки сети (DNS, разрыв связи, отказ сервера)
            await logger.log(
                f"HTTP request error: method={method}, "
                f"host={get_safe_host(url)}, "
                f"type={type(exc).__name__}"
            )
        except Exception as exc:
            # Непредвиденные ошибки
            await logger.log(f"Unexpected HTTP Error, host={get_safe_host(url)}, type={type(exc).__name__}")

        return None

    async def get(self, url: str, **kwargs) -> Optional[httpx.Response]:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> Optional[httpx.Response]:
        return await self.request("POST", url, **kwargs)

    async def close(self):
        """Закрытие пула соединений при остановке бота."""
        await self.client.aclose()


http_client = GlobalHTTPClient()
