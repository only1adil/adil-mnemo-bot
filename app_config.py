import logging
import os

from dotenv import load_dotenv


def setup_logging() -> None:
    """Настраивает логирование в консоль и файл."""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_file = os.getenv("LOG_FILE", None)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            print(f"✅ Логирование в файл: {log_file}")
        except Exception as e:
            print(f"⚠️  Не удалось открыть файл логов {log_file}: {e}")


def bootstrap_environment() -> str:
    """Загружает env, настраивает логирование и возвращает BOT_TOKEN."""
    load_dotenv()
    setup_logging()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("❌ BOT_TOKEN не найден в .env файле! Скопируй .env.example в .env и добавь свой токен.")
    return token
