"""
Слой хранилища для MNEME бота - использует SQLite (через db.py)
Сохраняет совместимость с существующим API
"""

import logging
from typing import Dict, List, Any, Optional
from db import (
    init_db, sync_words_from_json, rebuild_word_ids, register_user, add_word, get_all_words, get_word_by_id,
    get_total_words, get_user_progress as db_get_user_progress, 
    add_or_update_word_progress as db_add_or_update_word_progress,
    increment_word_errors, get_user_quotas as db_get_user_quotas, 
    update_user_quotas as db_update_user_quotas,
    update_user_error_streak, get_words_to_review, get_learned_words,
    get_learning_stats, get_words_for_session, get_session_accuracy,
    save_session, load_session, delete_session, verify_user_progress,
    # Новые функции для отслеживания прогресса ученика
    log_session, log_word_error, get_student_progress, get_daily_stats,
    get_error_history, get_most_problematic_words, check_and_award_achievements, 
    get_achievements,
    # Функция для отслеживания изменений файла
    check_words_json_updated
)

logging.basicConfig(level=logging.INFO)


# ==================== ПРОВЕРКА И ИСПРАВЛЕНИЕ ID ====================

def check_and_fix_word_ids() -> None:
    """
    Проверяет целостность ID слов и исправляет нарушения последовательности.
    Автоматически вызывается при инициализации для обеспечения корректности.
    """
    try:
        words = get_all_words()
        
        if not words:
            logging.info("📊 База слов пуста")
            return
            
        # Проверяем, есть ли пробелы в ID
        word_ids = sorted([w["id"] for w in words])
        expected_ids = list(range(1, len(word_ids) + 1))
        
        if word_ids != expected_ids:
            logging.warning(f"⚠️ Обнаружены проблемы с ID слов!")
            logging.warning(f"   Найдены ID: {word_ids}")
            logging.warning(f"   Ожидаются: {expected_ids}")
            logging.info("🔧 Начинается восстановление последовательности ID...")
            
            rebuild_word_ids()
            logging.info("✅ ID слов успешно восстановлены")
        else:
            logging.info(f"✓ ID слов корректны (всего {len(words)} слов)")
            
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке ID: {e}")

# Инициализируем БД при импорте
try:
    init_db()
    sync_words_from_json()  # Синхронизируем слова из words.json
    check_and_fix_word_ids()  # Проверяем и исправляем ID если нужно
except Exception as e:
    logging.error(f"❌ Ошибка при инициализации БД: {e}")


# ==================== СОВМЕСТИМОСТЬ С СУЩЕСТВУЮЩИМ API ====================

def load_users() -> Dict:
    """Загружает словарь всех пользователей (для совместимости)"""
    logging.warning("⚠ load_users() устарела - используйте get_user_progress(user_id)")
    return {}


def save_users(users: Dict) -> None:
    """Устарела - используйте add_or_update_word_progress()"""
    logging.warning("⚠ save_users() устарела - БД автоматически сохраняет")


def load_words() -> List[Dict]:
    """Получает список всех слов"""
    return get_all_words()


def save_words(words: List[Dict]) -> None:
    """Добавляет новые слова в БД"""
    for word in words:
        try:
            add_word(
                word=word.get("word", ""),
                translation=word.get("translation", ""),
                association=word.get("association", ""),
                example=word.get("example", "")
            )
        except Exception as e:
            logging.warning(f"⚠ Ошибка при добавлении слова: {e}")


def init_user_quotas(user_id: int):
    """Инициализирует квоты пользователя"""
    register_user(user_id)


def get_user_progress(user_id: int) -> Dict:
    """Получает прогресс пользователя"""
    return db_get_user_progress(user_id)


def save_user_progress(user_id: int, progress: Dict) -> None:
    """Сохраняет прогресс пользователя"""
    if "words" in progress:
        for word_id_str, word_progress in progress["words"].items():
            try:
                word_id = int(word_id_str)
                add_or_update_word_progress(
                    user_id=user_id,
                    word_id=word_id,
                    next_review=word_progress.get("next_review"),
                    mode=word_progress.get("mode", "learning"),
                    attempt_count=word_progress.get("attempt_count", 0)
                )
            except Exception as e:
                logging.warning(f"⚠ Ошибка при сохранении прогресса: {e}")


def add_or_update_word_progress(user_id: int, word_id: int, next_review: str, 
                               mode: str = "learning", attempt_count: int = 0) -> None:
    """Добавляет или обновляет прогресс слова"""
    db_add_or_update_word_progress(user_id, word_id, next_review, mode, attempt_count)


def get_user_quotas(user_id: int) -> Dict:
    """Получает квоты пользователя"""
    return db_get_user_quotas(user_id)


def update_user_quotas(user_id: int, accuracy: float = None, error_streak: int = 0) -> Dict:
    """
    Обновляет квоты пользователя.
    Сигнатура менялась - поддерживаем оба варианта для совместимости.
    """
    quotas = db_get_user_quotas(user_id)
    
    # Если вызвано со старой сигнатурой (accuracy параметр)
    if accuracy is not None:
        return quotas  # Для совместимости, но не применяем адаптацию сейчас
    
    return quotas


def update_user_error_streak(user_id: int, streak: int = None) -> int:
    """Обновляет счетчик ошибок пользователя"""
    if streak is not None:
        from db import update_user_error_streak as db_update_user_error_streak
        db_update_user_error_streak(user_id, streak)
    return 0


