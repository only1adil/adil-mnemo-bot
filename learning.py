from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from storage import (
    load_words, 
    get_user_progress, 
    get_user_quotas,
    add_or_update_word_progress,
    get_words_to_review as storage_get_words_to_review
)
from db import (
    get_word_by_id as db_get_word_by_id,
    get_total_words as db_get_total_words,
    get_words_for_session as db_get_words_for_session
)


def get_words_for_session(user_id: int, words_per_session: int = 5, errors_in_session: int = 0, level: str = None) -> List[Dict]:
    """
    Получает слова для сеанса обучения, учитывая квоты пользователя.
    Сначала возвращает слова на повторение, затем новые слова (если квота позволяет).
    
    Args:
        user_id: ID пользователя
        words_per_session: Количество слов в сеансе
        errors_in_session: Количество ошибок в сеансе (не используется)
        level: Уровень сложности (A1, A2, B1, B2). Если None, берется из профиля
    """
    quotas = get_user_quotas(user_id)
    max_new_words = quotas.get("new_words", 5)
    max_review_words = quotas.get("review_words", 20)
    
    # Используем оптимизированную функцию из db.py
    return db_get_words_for_session(
        user_id=user_id,
        words_per_session=words_per_session,
        max_new_words=max_new_words,
        max_review_words=max_review_words,
        level=level  # ✅ Передаём уровень
    )


def calculate_next_review(knew_it: bool, attempt_count: int = 0, mode: str = "learning") -> tuple[str, int, str]:
    """
    Вычисляет дату следующего повторения и новый режим.
    
    Args:
        knew_it: Пользователь ответил правильно?
        attempt_count: Количество успешных попыток в режиме recall
        mode: Текущий режим ("learning" или "recall")
    
    Returns:
        (next_datetime, new_attempt_count, new_mode)
        next_datetime возвращается в формате ISO string для сохранения информации о времени
        Это обеспечивает возвращение к типу recall через несколько часов, даже в тот же день
    """
    if not knew_it:
        # Ошибка - вернуть в режим learning на 10 минут
        # Сохраняем точное время для повторения в течение дня
        next_datetime = datetime.now() + timedelta(minutes=10)
        return next_datetime.isoformat(), 0, "learning"
    
    if mode == "learning":
        # Запомнил слово в режиме learning → переходим в recall (сразу)
        next_datetime = datetime.now()
        return next_datetime.isoformat(), 1, "recall"
    
    # Режим recall - правильный ответ
    attempt_count += 1
    intervals = {
        1: timedelta(minutes=10),    # 1-й правильный → 10 минут
        2: timedelta(days=1),         # 2-й правильный → 1 день
        3: timedelta(days=3),         # 3-й правильный → 3 дня
        4: timedelta(days=7),         # 4-й правильный → 7 дней
    }
    
    interval = intervals.get(attempt_count, timedelta(days=7))  # Максимум 7 дней
    next_datetime = datetime.now() + interval
    
    return next_datetime.isoformat(), attempt_count, "recall"



def get_word_by_id(word_id: int) -> Dict | None:
    """Получает слово по ID"""
    return db_get_word_by_id(word_id)


def get_total_words() -> int:
    """Возвращает общее количество слов"""
    return db_get_total_words()


def get_words_to_review(user_id: int) -> int:
    """Возвращает количество слов на повторение"""
    return storage_get_words_to_review(user_id)


def calculate_session_accuracy(correct: int, total: int) -> float:
    """Вычисляет точность сеанса в процентах"""
    if total == 0:
        return 0.0
    return (correct / total) * 100
