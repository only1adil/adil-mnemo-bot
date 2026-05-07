import logging
from typing import Awaitable, Callable


async def auto_sync_words(sync_words_func: Callable[[], None]) -> None:
    """Автоматически синхронизирует слова из JSON файла каждый час."""
    try:
        logging.info("🔄 Проверка обновлений слов из JSON...")
        sync_words_func()
        logging.info("✅ Синхронизация слов завершена успешно")
    except Exception as e:
        logging.error(f"❌ Ошибка при синхронизации слов: {e}")


async def schedule_tasks(
    scheduler,
    send_daily_reminder: Callable[[], Awaitable[None]],
    auto_sync_callback: Callable[[], Awaitable[None]],
) -> None:
    """Планирует регулярные задачи."""
    try:
        scheduler.add_job(
            auto_sync_callback,
            "interval",
            hours=1,
            id="auto_sync_words",
            replace_existing=True,
        )
        logging.info("✅ Запланирована автоматическая синхронизация слов (каждый час)")

        scheduler.add_job(
            send_daily_reminder,
            "cron",
            hour=9,
            minute=0,
            id="daily_reminder",
        )
        logging.info("✅ Запланирована ежедневная задача напоминания (9:00)")
    except Exception as e:
        logging.error(f"Ошибка при планировании задач: {e}")
