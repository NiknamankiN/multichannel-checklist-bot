import aiofiles
import os
import datetime
from config import TELEGRAM_BOT_LOG_FILENAME, MAX_BOT_LOG_FILENAME

class AsyncLogger:
    def __init__(self, file_name: str, base_log_dir="logs"):
        """
        :param file_name: Имя файла для этого конкретного логгера.
        :param base_log_dir: Имя папки для логов. По умолчанию 'logs'.
        """
        self.file_name = file_name
        self.base_log_dir = base_log_dir

        current_file_path = os.path.abspath(__file__)
        utils_dir = os.path.dirname(current_file_path)
        self.project_root = os.path.dirname(utils_dir)

    async def log(self, text: str):
        """
        Асинхронно записывает лог в файл, заданный при инициализации логгера.
        """
        now = datetime.datetime.now()
        year, month, day = str(now.year), str(now.month), str(now.day)

        logs_path = os.path.join(self.project_root, self.base_log_dir, year, month, day)
        file_path = os.path.join(logs_path, self.file_name)

        if not os.path.exists(logs_path):
            try:
                os.makedirs(logs_path, exist_ok=True)
            except OSError as e:
                print(f"Error creating log directory {logs_path}: {e}")
                return

        log_entry = f"{now.strftime('%Y-%m-%d, %H:%M:%S')} | {text}\n"

        try:
            async with aiofiles.open(file_path, 'a+', encoding="utf-8") as f:
                await f.write(log_entry)
        except Exception as e:
            print(f"CRITICAL LOGGING ERROR: {e} | Original message: {text}")


tg_logger = AsyncLogger(file_name=TELEGRAM_BOT_LOG_FILENAME, base_log_dir="logs/telegram")
max_logger = AsyncLogger(file_name=MAX_BOT_LOG_FILENAME, base_log_dir="logs/max")

logger = AsyncLogger(file_name="common_logs.txt", base_log_dir="logs/common")
