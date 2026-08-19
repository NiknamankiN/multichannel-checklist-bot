import hmac
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
import uvicorn

from database.postgres import db
from database.sqlite import sqlite_client
from services.http_client import http_client
from apps.max.handlers import handle_incoming_event
from apps.max.core import MaxBotCore
from apps.max.client import max_client
from config import MAX_WEBHOOK_URL, MAX_WEBHOOK_SECRET
from utils.logger import max_logger as logger

max_core = MaxBotCore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    """
    # --- STARTUP ---
    await logger.log("Starting Max Messenger Bot API...")

    # 1. Подключаемся к базам данных
    await db.connect()
    await sqlite_client.init_db()

    # 2. Проверка и установка вебхука (если задан URL)
    if MAX_WEBHOOK_URL:
        await logger.log("Checking MAX webhook subscription")
        try:
            # Получаем текущие подписки
            current_subs = await max_client.get_subscriptions()

            # Проверяем, есть ли наш URL в списке
            is_subscribed = False
            for sub in current_subs:
                if sub.get('url') == MAX_WEBHOOK_URL:
                    is_subscribed = True
                    break

            if not is_subscribed:
                await logger.log("Webhook not found. Registering...")
                success = await max_client.set_webhook(MAX_WEBHOOK_URL, MAX_WEBHOOK_SECRET)
                if success:
                    await logger.log("Max webhook registered successfully.")
                else:
                    await logger.log("Failed to register Max webhook.")
            else:
                await logger.log("Max webhook is already registered.")

        except Exception as e:
            await logger.log(f"Error checking/setting webhook: {e}")
    else:
        await logger.log("MAX_WEBHOOK_URL not set in config. Webhook registration skipped.")

    # 3. Запускаем фоновую задачу отправки сообщений
    await max_core.start()

    yield

    # --- SHUTDOWN ---
    await logger.log("Shutting down Max Messenger Bot API...")

    await max_core.stop()
    await db.close()
    await http_client.close()
    await sqlite_client.close()


app = FastAPI(lifespan=lifespan)


@app.post("/max/webhook")
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    if not MAX_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )

    received_secret = request.headers.get("X-Max-Bot-Api-Secret", "")

    if not hmac.compare_digest(received_secret, MAX_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        )

    update_type = data.get("update_type", "unknown")
    await logger.log(f"Received Max webhook: type={update_type}")

    background_tasks.add_task(handle_incoming_event, data)
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("apps.max.app:app", host="0.0.0.0", port=8000, reload=True)
