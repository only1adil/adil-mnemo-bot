import html
from difflib import SequenceMatcher
from typing import Dict, Tuple


def normalize_answer(answer: str) -> str:
    """Нормализует ответ пользователя."""
    return answer.lower().strip()


def check_answer(user_answer: str, correct_answer: str) -> Tuple[bool, str]:
    """
    Проверяет ответ пользователя с нечеткой логикой.
    Возвращает (is_correct, status).
    """
    user_normalized = normalize_answer(user_answer)
    correct_normalized = normalize_answer(correct_answer)

    if user_normalized == correct_normalized:
        return True, "correct"

    similarity = SequenceMatcher(None, user_normalized, correct_normalized).ratio()
    if similarity >= 0.7:
        return True, "similar"

    if user_normalized in correct_normalized and len(user_normalized) > 2:
        return True, "similar"

    return False, "wrong"


def format_word_with_ipa(word: Dict) -> str:
    """Форматирует слово с IPA транскрипцией."""
    word_text = html.escape(word.get("word", ""))
    ipa = html.escape(word.get("ipa", ""))
    if ipa:
        return f"{word_text} — <i>{ipa}</i>"
    return word_text


def esc(value: str) -> str:
    """Экранирует текст для parse_mode='HTML'."""
    return html.escape(value or "")
