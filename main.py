import argparse


def start_telegram_bot():
    """
    Запуск Telegram бота (Long Polling).
    """
    from apps.telegram.core import BotCore
    print("Starting Telegram Bot...")
    bot = BotCore()
    bot.run()


def start_max_bot():
    """
    Запуск Max Messenger бота (FastAPI Webhook).
    """
    import uvicorn

    print("Starting Max Messenger Bot (FastAPI)...")
    # uvicorn.run блокирует поток, поэтому вызываем его напрямую
    # Указываем путь к объекту app в формате "module:attribute"
    uvicorn.run("apps.max.app:app", host="0.0.0.0", port=8000, reload=True)


def show_status():
    """Публичная заглушка для исключённой диагностической команды."""
    print(
        "Status inspection is unavailable in the public showcase: "
        "database integrations are intentionally omitted."
    )


def main():
    parser = argparse.ArgumentParser(description="Multi-Bot Runner")

    # Аргумент для выбора действия
    parser.add_argument(
        'action',
        choices=['run_telegram', 'run_max', 'status'],
        nargs='?',
        default='run_telegram',
        help="Action to perform: run_telegram (default), run_max, or status"
    )

    args = parser.parse_args()

    if args.action == 'status':
        show_status()
    elif args.action == 'run_telegram':
        start_telegram_bot()
    elif args.action == 'run_max':
        start_max_bot()


if __name__ == "__main__":
    main()
