# -*- coding: utf-8 -*-
"""
SQLite база данных для MNEME бота.
Используется для хранения слов, прогресса пользователей и статистики.
"""

import sqlite3
import json
import logging
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path

# Логирование настраивается в bot.py через setup_logging()
logger = logging.getLogger(__name__)

# Загружаем .env для корректной инициализации путей БД/JSON
load_dotenv()

# Путь к БД
DB_PATH = os.getenv("DATABASE_PATH", "mnemo.db")
WORDS_JSON = os.getenv("WORDS_JSON_PATH", "words.json")

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

def get_connection():
    """Получает подключение к БД"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row  # Возвращает результаты как словари
    # Базовые настройки устойчивости для конкурентной записи
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db() -> None:
    """Инициализирует базу данных с нужными таблицами"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_activity TEXT,
            current_error_streak INTEGER DEFAULT 0,
            longest_error_streak INTEGER DEFAULT 0,
            current_level TEXT DEFAULT 'A1'
        )
    """)
    
    # Таблица слов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            translation TEXT NOT NULL,
            association TEXT,
            example TEXT,
            ipa TEXT,
            level TEXT DEFAULT 'A1',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # ✅ МИГРАЦИЯ: Добавляем колонку 'level' если она отсутствует
    try:
        cursor.execute("ALTER TABLE words ADD COLUMN level TEXT DEFAULT 'A1'")
        logging.info("✅ Добавлена колонка 'level' в таблицу 'words'")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            # Колонка уже существует, это нормально
            pass
        else:
            logging.warning(f"⚠️ Ошибка при добавлении колонки 'level': {e}")
    
    # Таблица прогресса пользователя по словам
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            mode TEXT DEFAULT 'learning',
            attempt_count INTEGER DEFAULT 0,
            next_review TEXT,
            last_reviewed TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, word_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(word_id) REFERENCES words(id)
        )
    """)
    
    # Таблица сеансов обучения
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            words_data TEXT NOT NULL,
            current_index INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    
    # Таблица логов сеансов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            duration_seconds INTEGER,
            words_count INTEGER,
            correct_answers INTEGER DEFAULT 0,
            incorrect_answers INTEGER DEFAULT 0,
            new_words_learned INTEGER DEFAULT 0,
            error_streak INTEGER DEFAULT 0,
            words_ids TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    
    # Таблица истории ошибок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            error_type TEXT,
            user_answer TEXT,
            correct_answer TEXT,
            session_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(word_id) REFERENCES words(id)
        )
    """)
    
    # Таблица квот пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_quotas (
            user_id INTEGER PRIMARY KEY,
            new_words INTEGER DEFAULT 5,
            review_words INTEGER DEFAULT 20,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    
    # Таблица достижений
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_name TEXT NOT NULL,
            earned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    
    # Индексы для оптимизации
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_progress_user ON user_progress(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_progress_word ON user_progress(word_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_progress_next_review ON user_progress(next_review)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_error_history_user ON error_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_logs_user ON session_logs(user_id)")
    
    conn.commit()
    conn.close()
    
    logging.info("✅ База данных инициализирована")


def sync_words_from_json() -> None:
    """Синхронизирует слова из JSON файла в БД"""
    try:
        if not Path(WORDS_JSON).exists():
            logging.warning(f"⚠️ Файл {WORDS_JSON} не найден")
            return
        
        with open(WORDS_JSON, 'r', encoding='utf-8') as f:
            words_data = json.load(f)
        
        if not isinstance(words_data, list):
            logging.error(f"❌ {WORDS_JSON} должен содержать массив слов")
            return
        
        conn = get_connection()
        cursor = conn.cursor()
        
        added_count = 0
        updated_count = 0
        
        for word in words_data:
            word_text = word.get('word', '')
            if not word_text:
                continue
            
            try:
                cursor.execute("SELECT id FROM words WHERE word = ?", (word_text,))
                existed = cursor.fetchone() is not None
                cursor.execute("""
                    INSERT INTO words (word, translation, association, example, ipa, level)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(word) DO UPDATE SET
                        translation = excluded.translation,
                        association = excluded.association,
                        example = excluded.example,
                        ipa = excluded.ipa,
                        level = excluded.level
                """, (
                    word_text,
                    word.get('translation', ''),
                    word.get('association', ''),
                    word.get('example', ''),
                    word.get('ipa', ''),
                    word.get('level', 'A1')
                ))
                if existed:
                    updated_count += 1
                else:
                    added_count += 1
            except sqlite3.IntegrityError:
                updated_count += 1
        
        conn.commit()
        conn.close()
        
        if added_count > 0 or updated_count > 0:
            logging.info(f"✅ Синхронизация слов: добавлено {added_count}, обновлено {updated_count}")
        
    except Exception as e:
        logging.error(f"❌ Ошибка при синхронизации слов из JSON: {e}")


# ==================== ОТСЛЕЖИВАНИЕ ИЗМЕНЕНИЙ ФАЙЛА ====================

_last_json_mtime = None

def check_words_json_updated() -> bool:
    """
    Проверяет, был ли обновлен файл words.json с последней синхронизации.
    Если да - перезагружает слова в БД.
    Возвращает True если файл был обновлен.
    """
    global _last_json_mtime
    
    try:
        json_path = Path(WORDS_JSON)
        if not json_path.exists():
            return False
        
        current_mtime = json_path.stat().st_mtime
        
        # Первый запуск или файл был изменен
        if _last_json_mtime is None:
            _last_json_mtime = current_mtime
            return False
        
        if current_mtime > _last_json_mtime:
            logging.info("🔄 Обнаружены изменения в words.json, обновляем слова...")
            _last_json_mtime = current_mtime
            sync_words_from_json()
            return True
        
        return False
        
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке обновлений JSON: {e}")
        return False



# ==================== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ====================

def register_user(user_id: int, username: str = None) -> None:
    """Регистрирует пользователя в БД"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, last_activity)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (user_id, username))
        
        cursor.execute("""
            INSERT OR IGNORE INTO user_quotas (user_id, new_words, review_words)
            VALUES (?, 5, 20)
        """, (user_id,))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при регистрации пользователя {user_id}: {e}")
    finally:
        conn.close()


def update_user_activity(user_id: int) -> None:
    """Обновляет время последней активности пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE users SET last_activity = CURRENT_TIMESTAMP WHERE user_id = ?
        """, (user_id,))
        conn.commit()
    finally:
        conn.close()


# ==================== РАБОТА СО СЛОВАМИ ====================

def add_word(word: str, translation: str, association: str = "", example: str = "", ipa: str = "", level: str = "A1") -> int:
    """Добавляет новое слово в БД, возвращает ID слова"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO words (word, translation, association, example, ipa, level)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (word, translation, association, example, ipa, level))
        
        conn.commit()
        word_id = cursor.lastrowid
        logging.info(f"✅ Добавлено слово '{word}' ({level}) с ID {word_id}")
        return word_id
    except sqlite3.IntegrityError:
        logging.warning(f"⚠️ Слово '{word}' уже существует")
        return None
    except Exception as e:
        logging.error(f"Ошибка при добавлении слова: {e}")
        return None
    finally:
        conn.close()


def get_word_by_id(word_id: int) -> Optional[Dict]:
    """Получает слово по ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM words WHERE id = ?", (word_id,))
        row = cursor.fetchone()
        
        if row:
            return {
                'id': row['id'],
                'word': row['word'],
                'translation': row['translation'],
                'association': row['association'],
                'example': row['example'],
                'ipa': row['ipa'],
                'level': row['level']
            }
        return None
    finally:
        conn.close()


def get_all_words() -> List[Dict]:
    """Получает все слова из БД"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM words ORDER BY id")
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_total_words() -> int:
    """Возвращает общее количество слов в БД"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) as count FROM words")
        result = cursor.fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()


def rebuild_word_ids() -> None:
    """Восстанавливает последовательность ID слов (1, 2, 3, ...)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Получаем все слова в порядке ID
        cursor.execute("SELECT id FROM words ORDER BY id")
        old_ids = [row['id'] for row in cursor.fetchall()]
        
        if not old_ids:
            return
        
        # Создаем новую таблицу с правильными ID
        cursor.execute("""
            CREATE TABLE words_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE NOT NULL,
                translation TEXT NOT NULL,
                association TEXT,
                example TEXT,
                ipa TEXT,
                level TEXT DEFAULT 'A1',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Копируем слова с новыми ID
        cursor.execute("""
            INSERT INTO words_new (word, translation, association, example, ipa, level, created_at)
            SELECT word, translation, association, example, ipa, level, created_at FROM words
            ORDER BY id
        """)
        
        # Обновляем ссылки на слова в других таблицах
        cursor.execute("SELECT id FROM words ORDER BY id")
        old_to_new = {old_id: i+1 for i, old_id in enumerate([row['id'] for row in cursor.fetchall()])}
        
        for old_id, new_id in old_to_new.items():
            cursor.execute("""
                UPDATE user_progress SET word_id = ? WHERE word_id = ?
            """, (new_id, old_id))
            cursor.execute("""
                UPDATE error_history SET word_id = ? WHERE word_id = ?
            """, (new_id, old_id))
        
        # Удаляем старую таблицу
        cursor.execute("DROP TABLE words")
        cursor.execute("ALTER TABLE words_new RENAME TO words")
        
        # Пересоздаем индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_progress_user ON user_progress(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_progress_word ON user_progress(word_id)")
        
        conn.commit()
        logging.info("✅ ID слов восстановлены")
        
    except Exception as e:
        logging.error(f"❌ Ошибка при восстановлении ID слов: {e}")
        conn.rollback()
    finally:
        conn.close()


# ==================== РАБОТА С ПРОГРЕССОМ ====================

def get_user_progress(user_id: int) -> Dict:
    """Получает полный прогресс пользователя"""
    register_user(user_id)  # Убеждаемся что пользователь зарегистрирован
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT up.word_id, up.mode, up.attempt_count, up.next_review
            FROM user_progress up
            WHERE up.user_id = ?
        """, (user_id,))
        
        rows = cursor.fetchall()
        
        words_progress = {}
        for row in rows:
            words_progress[str(row['word_id'])] = {
                'mode': row['mode'],
                'attempt_count': row['attempt_count'],
                'next_review': row['next_review']
            }
        
        return {'words': words_progress}
    finally:
        conn.close()


def add_or_update_word_progress(user_id: int, word_id: int, next_review: str, 
                                mode: str = "learning", attempt_count: int = 0) -> None:
    """Добавляет или обновляет прогресс слова для пользователя"""
    register_user(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO user_progress (user_id, word_id, mode, attempt_count, next_review, last_reviewed)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, word_id) DO UPDATE SET
                mode = excluded.mode,
                attempt_count = excluded.attempt_count,
                next_review = excluded.next_review,
                last_reviewed = CURRENT_TIMESTAMP
        """, (user_id, word_id, mode, attempt_count, next_review))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при обновлении прогресса слова: {e}")
    finally:
        conn.close()


def increment_word_errors(user_id: int, word_id: int) -> None:
    """Увеличивает счетчик ошибок для слова"""
    pass  # Ошибки логируются отдельно в error_history


def verify_user_progress(user_id: int) -> bool:
    """Проверяет корректность прогресса пользователя"""
    # Убеждаемся что все слова в прогрессе существуют в БД
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Удаляем ссылки на несуществующие слова
        cursor.execute("""
            DELETE FROM user_progress
            WHERE word_id NOT IN (SELECT id FROM words)
            AND user_id = ?
        """, (user_id,))
        
        conn.commit()
        return True
    finally:
        conn.close()


def get_learned_words(user_id: int) -> int:
    """Возвращает количество выученных слов (4+ успешных попыток в recall)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress
            WHERE user_id = ? AND attempt_count >= 4
        """, (user_id,))
        
        result = cursor.fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()


def get_words_to_review(user_id: int) -> int:
    """Возвращает количество слов на повторение (где next_review <= теперь)"""
    register_user(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress
            WHERE user_id = ? AND next_review IS NOT NULL
            AND datetime(next_review) <= datetime('now')
        """, (user_id,))
        
        result = cursor.fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()


# ==================== ФУНКЦИИ ДЛЯ СТАТИСТИКИ ПО УРОВНЮ ====================

def get_total_words_for_level(level: str) -> int:
    """Возвращает количество слов на определенном уровне"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) as count FROM words WHERE level = ?", (level,))
        result = cursor.fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()


def get_words_to_review_for_level(user_id: int, level: str) -> int:
    """Возвращает количество слов на повторение для определённого уровня"""
    register_user(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress up
            JOIN words w ON up.word_id = w.id
            WHERE up.user_id = ? AND w.level = ?
            AND up.next_review IS NOT NULL
            AND datetime(up.next_review) <= datetime('now')
            AND up.attempt_count < 4
        """, (user_id, level))
        
        result = cursor.fetchone()
        return result['count'] if result else 0
    finally:
        conn.close()


def get_user_progress_for_level(user_id: int, level: str) -> Dict:
    """
    Получает подробный прогресс пользователя по определённому уровню.
    Возвращает словарь с количеством:
    - всего слов на этом уровне
    - выученных слов
    - слов в процессе обучения
    - слов на повторение
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Всего слов на этом уровне
        cursor.execute("SELECT COUNT(*) as count FROM words WHERE level = ?", (level,))
        total_row = cursor.fetchone()
        total = total_row['count'] if total_row else 0
        
        # Выученные слова (attempt_count >= 4)
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress up
            JOIN words w ON up.word_id = w.id
            WHERE up.user_id = ? AND w.level = ? AND up.attempt_count >= 4
        """, (user_id, level))
        learned_row = cursor.fetchone()
        learned = learned_row['count'] if learned_row else 0
        
        # Слова в процессе (попытки < 4, но уже начинал)
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress up
            JOIN words w ON up.word_id = w.id
            WHERE up.user_id = ? AND w.level = ?
            AND (up.mode = 'learning' OR up.mode = 'recall')
            AND up.attempt_count < 4
        """, (user_id, level))
        learning_row = cursor.fetchone()
        learning = learning_row['count'] if learning_row else 0
        
        # Слова на повторение (next_review <= теперь)
        cursor.execute("""
            SELECT COUNT(*) as count FROM user_progress up
            JOIN words w ON up.word_id = w.id
            WHERE up.user_id = ? AND w.level = ?
            AND up.next_review IS NOT NULL
            AND datetime(up.next_review) <= datetime('now')
            AND up.attempt_count < 4
        """, (user_id, level))
        review_row = cursor.fetchone()
        to_review = review_row['count'] if review_row else 0
        
        return {
            'total': total,
            'learned': learned,
            'learning': learning,
            'to_review': to_review
        }
    finally:
        conn.close()


# ==================== РАБОТА С СЕАНСАМИ ====================

def save_session(user_id: int, session_data: Dict) -> None:
    """Сохраняет сеанс в БД"""
    session_id = f"{user_id}_{int(datetime.now().timestamp())}"
    words_json = json.dumps({
        'words': session_data.get('words', []),
        'current_index': session_data.get('current_index', 0),
        'correct_count': session_data.get('correct_count', 0),
        'error_count': session_data.get('error_count', 0),
        'dont_know_count': session_data.get('dont_know_count', 0),
        'error_streak': session_data.get('error_streak', 0),
        'newly_learned': session_data.get('newly_learned', 0),
        'start_time': session_data.get('start_time')
    }, ensure_ascii=False)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO sessions 
            (session_id, user_id, words_data, current_index)
            VALUES (?, ?, ?, ?)
        """, (
            session_id,
            user_id,
            words_json,
            session_data.get('current_index', 0)
        ))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при сохранении сеанса: {e}")
    finally:
        conn.close()


def load_session(user_id: int) -> Optional[Dict]:
    """Загружает активный сеанс пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT words_data, current_index FROM sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id,))
        
        row = cursor.fetchone()
        if row:
            try:
                payload = json.loads(row['words_data'])
                # Обратная совместимость: старый формат хранил только массив слов
                if isinstance(payload, list):
                    return {
                        'words': payload,
                        'current_index': row['current_index'],
                        'correct_count': 0,
                        'error_count': 0,
                        'dont_know_count': 0,
                        'error_streak': 0,
                        'newly_learned': 0,
                        'start_time': int(time.time())
                    }
                return {
                    'words': payload.get('words', []),
                    'current_index': payload.get('current_index', row['current_index']),
                    'correct_count': payload.get('correct_count', 0),
                    'error_count': payload.get('error_count', 0),
                    'dont_know_count': payload.get('dont_know_count', 0),
                    'error_streak': payload.get('error_streak', 0),
                    'newly_learned': payload.get('newly_learned', 0),
                    'start_time': payload.get('start_time', int(time.time()))
                }
            except json.JSONDecodeError:
                logging.warning(f"⚠️ Не удалось декодировать сеанс для пользователя {user_id}")
                return None
        return None
    finally:
        conn.close()


def delete_session(user_id: int) -> None:
    """Удаляет активный сеанс пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ==================== РАБОТА С КВОТАМИ ====================

def get_user_quotas(user_id: int) -> Dict:
    """Получает квоты пользователя"""
    register_user(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT new_words, review_words FROM user_quotas WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'new_words': row['new_words'],
                'review_words': row['review_words']
            }
        
        # Если записи нет, создаем стандартные квоты
        cursor.execute("""
            INSERT INTO user_quotas (user_id, new_words, review_words)
            VALUES (?, 5, 20)
        """, (user_id,))
        conn.commit()
        
        return {'new_words': 5, 'review_words': 20}
    finally:
        conn.close()


def update_user_quotas(user_id: int, new_words: int = None, review_words: int = None) -> Dict:
    """Обновляет квоты пользователя"""
    quotas = get_user_quotas(user_id)
    
    if new_words is not None:
        quotas['new_words'] = new_words
    if review_words is not None:
        quotas['review_words'] = review_words
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE user_quotas 
            SET new_words = ?, review_words = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (quotas['new_words'], quotas['review_words'], user_id))
        
        conn.commit()
    finally:
        conn.close()
    
    return quotas


def update_user_error_streak(user_id: int, streak: int = 0) -> None:
    """Обновляет счетчик ошибок пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE users 
            SET current_error_streak = ?, 
                longest_error_streak = MAX(longest_error_streak, ?)
            WHERE user_id = ?
        """, (streak, streak, user_id))
        
        conn.commit()
    finally:
        conn.close()


# ==================== РАБОТА С УРОВНЕМ ПОЛЬЗОВАТЕЛЯ ====================

def get_user_level(user_id: int) -> str:
    """Получает текущий уровень пользователя (A1, A2, B1, B2)"""
    register_user(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT current_level FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if row and row['current_level']:
            return row['current_level']
        return 'A1'  # Уровень по умолчанию
    finally:
        conn.close()


def set_user_level(user_id: int, level: str) -> None:
    """Устанавливает уровень пользователя"""
    register_user(user_id)
    
    # Проверяем валидность уровня
    if level not in ['A1', 'A2', 'B1', 'B2']:
        logging.warning(f"⚠️ Недопустимый уровень '{level}', установка A1")
        level = 'A1'
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE users SET current_level = ? WHERE user_id = ?
        """, (level, user_id))
        
        conn.commit()
        logging.info(f"✅ Пользователь {user_id} установил уровень {level}")
    finally:
        conn.close()


# ==================== РАБОТА С ЛОГАМИ И СТАТИСТИКОЙ ====================

def log_session(user_id: int, session_data: Dict) -> None:
    """Логирует завершенный сеанс"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        words_ids_str = json.dumps(session_data.get('words_ids', []))
        
        cursor.execute("""
            INSERT INTO session_logs 
            (user_id, duration_seconds, words_count, correct_answers, 
             incorrect_answers, new_words_learned, error_streak, words_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            session_data.get('duration_seconds', 0),
            session_data.get('words_count', 0),
            session_data.get('correct_answers', 0),
            session_data.get('incorrect_answers', 0),
            session_data.get('new_words_learned', 0),
            session_data.get('error_streak', 0),
            words_ids_str
        ))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при логировании сеанса: {e}")
    finally:
        conn.close()


def log_word_error(user_id: int, word_id: int, error_type: str, 
                  user_answer: str, correct_answer: str, session_id: str = None) -> None:
    """Логирует ошибку в ответе на слово"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO error_history 
            (user_id, word_id, error_type, user_answer, correct_answer, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, word_id, error_type, user_answer, correct_answer, session_id))
        
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка при логировании ошибки: {e}")
    finally:
        conn.close()


def get_learning_stats(user_id: int) -> Dict:
    """Получает статистику обучения пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COUNT(*) as total_sessions,
                SUM(duration_seconds) as total_seconds,
                SUM(correct_answers) as total_correct,
                SUM(incorrect_answers) as total_incorrect,
                SUM(new_words_learned) as total_new_words
            FROM session_logs WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        
        return {
            'total_sessions': row['total_sessions'] or 0,
            'total_study_minutes': (row['total_seconds'] or 0) // 60,
            'total_correct_answers': row['total_correct'] or 0,
            'total_incorrect_answers': row['total_incorrect'] or 0,
            'total_new_words_learned': row['total_new_words'] or 0
        }
    finally:
        conn.close()


def get_session_accuracy(correct: int, total: int) -> float:
    """Вычисляет точность сеанса в процентах"""
    if total == 0:
        return 0.0
    return (correct / total) * 100


def get_daily_stats(user_id: int) -> Dict:
    """Получает статистику за день"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                COUNT(*) as daily_sessions,
                SUM(correct_answers) as correct,
                SUM(incorrect_answers) as incorrect
            FROM session_logs 
            WHERE user_id = ? AND DATE(created_at) = DATE('now')
        """, (user_id,))
        
        row = cursor.fetchone()
        
        correct = row['correct'] or 0
        incorrect = row['incorrect'] or 0
        total = correct + incorrect
        accuracy = (correct / total * 100) if total > 0 else 0
        
        return {
            'daily_sessions': row['daily_sessions'] or 0,
            'correct': correct,
            'incorrect': incorrect,
            'accuracy': accuracy
        }
    finally:
        conn.close()


def get_error_history(user_id: int, word_id: int = None, limit: int = 10) -> List[Dict]:
    """Получает историю ошибок пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if word_id:
            cursor.execute("""
                SELECT * FROM error_history 
                WHERE user_id = ? AND word_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, word_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM error_history 
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_most_problematic_words(user_id: int, limit: int = 10) -> List[Dict]:
    """Получает слова, в которых пользователь часто ошибается"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                w.id, w.word, w.translation,
                COUNT(*) as error_count
            FROM error_history eh
            JOIN words w ON eh.word_id = w.id
            WHERE eh.user_id = ?
            GROUP BY w.id
            ORDER BY error_count DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def check_and_award_achievements(user_id: int) -> List[str]:
    """Проверяет и выдает достижения пользователю"""
    conn = get_connection()
    cursor = conn.cursor()
    new_achievements = []
    
    try:
        stats = get_learning_stats(user_id)
        learned_words = get_learned_words(user_id)
        
        achievements_to_check = [
            ('first_word', "🌱 Первое слово", learned_words >= 1),
            ('first_five', "🌿 Пять слов изучено", learned_words >= 5),
            ('first_ten', "🌳 Десять слов", learned_words >= 10),
            ('first_fifty', "🏆 Пятьдесят слов", learned_words >= 50),
            ('first_hundred', "👑 Сто слов", learned_words >= 100),
            ('first_session', "🚀 Первый сеанс", stats['total_sessions'] >= 1),
            ('ten_sessions', "📚 Десять сеансов", stats['total_sessions'] >= 10),
            ('study_hour', "⏱️ Час учебы", stats['total_study_minutes'] >= 60),
            ('perfect_session', "✨ Идеальный сеанс", False),  # Проверяется отдельно
            ('consistency', "🔥 Прилежание", stats['total_sessions'] >= 5),
        ]
        
        for achievement_id, achievement_name, condition in achievements_to_check:
            if condition:
                # Проверяем есть ли это достижение уже
                cursor.execute("""
                    SELECT id FROM achievements 
                    WHERE user_id = ? AND achievement_name = ?
                """, (user_id, achievement_name))
                
                if not cursor.fetchone():
                    # Добавляем достижение
                    cursor.execute("""
                        INSERT INTO achievements (user_id, achievement_name)
                        VALUES (?, ?)
                    """, (user_id, achievement_name))
                    
                    new_achievements.append(achievement_name)
        
        conn.commit()
        return new_achievements
    finally:
        conn.close()


def get_achievements(user_id: int) -> List[Dict]:
    """Получает все достижения пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT achievement_name, earned_at FROM achievements
            WHERE user_id = ?
            ORDER BY earned_at DESC
        """, (user_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_student_progress(user_id: int) -> Dict:
    """Получает полный прогресс студента для команды /stats"""
    stats = get_learning_stats(user_id)
    learned = get_learned_words(user_id)
    total = get_total_words()
    
    # Определяем уровень обучения
    if stats['total_sessions'] == 0:
        level = "Новичок"
        description = "Начните первый сеанс!"
    elif learned < 10:
        level = "Ученик"
        description = "Вы только начали"
    elif learned < 50:
        level = "Любитель"
        description = "Хороший прогресс!"
    elif learned < 100:
        level = "Эксперт"
        description = "Впечатляет!"
    else:
        level = "Мастер"
        description = "Вы великолепны!"
    
    return {
        'learning_level': {
            'level': level,
            'description': description
        },
        'statistics': {
            'total_words_learned': learned,
            'total_words_available': total,
            'total_sessions': stats['total_sessions'],
            'total_correct_answers': stats['total_correct_answers'],
            'total_incorrect_answers': stats['total_incorrect_answers'],
            'total_study_minutes': stats['total_study_minutes'],
            'average_accuracy': (
                (stats['total_correct_answers'] / (stats['total_correct_answers'] + stats['total_incorrect_answers']) * 100)
                if (stats['total_correct_answers'] + stats['total_incorrect_answers']) > 0 else 0
            ),
            'current_error_streak': 0,
            'longest_error_streak': 0
        }
    }


# ==================== РАБОТА С ВЫБОРОМ СЛОВ ====================

def get_words_for_session(user_id: int, words_per_session: int = 10, 
                         max_new_words: int = 5, max_review_words: int = 20, level: str = None) -> List[Dict]:
    """
    Получает слова для сеанса обучения.
    Сначала возвращает слова на повторение, потом новые слова.
    Если level не указан, берется из профиля пользователя.
    """
    register_user(user_id)
    
    # Если уровень не указан, получаем из профиля пользователя
    if level is None:
        level = get_user_level(user_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        session_words = []
        
        # 1. Получаем слова на повторение (где next_review <= сейчас и attempt_count < 4)
        cursor.execute("""
            SELECT w.* FROM words w
            JOIN user_progress up ON w.id = up.word_id
            WHERE up.user_id = ? 
                AND up.next_review IS NOT NULL
                AND datetime(up.next_review) <= datetime('now')
                AND up.attempt_count < 4
                AND w.level = ?
            ORDER BY up.next_review ASC
            LIMIT ?
        """, (user_id, level, max_review_words))
        
        review_words = cursor.fetchall()
        session_words.extend([dict(row) for row in review_words])
        
        # 2. Если нужно еще слов, добавляем новые (которые еще не начинали)
        if len(session_words) < words_per_session:
            needed = min(
                words_per_session - len(session_words),
                max_new_words
            )
            
            cursor.execute("""
                SELECT w.* FROM words w
                WHERE w.id NOT IN (
                    SELECT word_id FROM user_progress WHERE user_id = ?
                )
                AND w.level = ?
                ORDER BY w.id
                LIMIT ?
            """, (user_id, level, needed))
            
            new_words = cursor.fetchall()
            session_words.extend([dict(row) for row in new_words])
            
            # Инициализируем прогресс для новых слов
            for word in new_words:
                add_or_update_word_progress(
                    user_id=user_id,
                    word_id=word['id'],
                    next_review=datetime.now().isoformat(),
                    mode='learning',
                    attempt_count=0
                )
        
        return session_words
    finally:
        conn.close()


if __name__ == "__main__":
    # Инициализируем БД при прямом запуске
    init_db()
    sync_words_from_json()
    logging.info("✅ Database initialized successfully")
