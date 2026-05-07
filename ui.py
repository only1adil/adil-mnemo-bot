from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Учить слова")],
            [KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="⚙️ Уровень"), KeyboardButton(text="ℹ️ О боте")],
        ],
        resize_keyboard=True,
    )
