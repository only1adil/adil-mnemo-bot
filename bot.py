# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import os
import time  # ✅ ИСПРАВЛЕНО: Добавлен импорт в начало
from datetime import datetime
from typing import Dict, Tuple
from difflib import SequenceMatcher
from dotenv import load_dotenv

# ⚙️ КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ
def setup_logging():
    """Настраивает логирование в консоль и файл"""
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    log_file = os.getenv('LOG_FILE', None)
    
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level))
    
    # Формат для логов
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Логирование в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Логирование в файл (если указан)
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            print(f"✅ Логирование в файл: {log_file}")
        except Exception as e:
            print(f"⚠️  Не удалось открыть файл логов {log_file}: {e}")

# Загружаем переменные окружения до настройки логирования
load_dotenv()
setup_logging()

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from storage import (
    load_users, save_users, add_or_update_word_progress, get_user_progress, 
    init_user_quotas, get_user_quotas, update_user_quotas, update_user_error_streak,
    save_session, load_session, delete_session,  # Функции сеансов
    # Новые функции для отслеживания прогресса ученика
    log_session, log_word_error, check_and_award_achievements, get_achievements,
    # Функции для команд пользователя
    get_student_progress, get_most_problematic_words,
    # Функция для отслеживания изменений файла
    check_words_json_updated,
    # Функции для работы с уровнем пользователя
    get_user_level, set_user_level
)
from learning import (
    get_words_for_session,
    calculate_next_review,
    get_word_by_id,
    get_total_words,
    get_words_to_review,
    calculate_session_accuracy
)
from db import init_db, sync_words_from_json

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================
logging.info("🔧 Инициализация базы данных...")
init_db()
sync_words_from_json()
logging.info("✅ База данных готова!")

# ⚙️ КОНФИГУРАЦИЯ
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле! Скопируй .env.example в .env и добавь свой токен.")

logging.info("🚀 Запуск MNEME бота...")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Состояния FSM
class LearningState(StatesGroup):
    learning_mode = State()      # Режим обучения: показываем слово и кнопки
    recall_input = State()        # Ввод ответа в режиме recall
    choosing_level = State()      # Выбор уровня сложности


# Хранилище текущей сессии пользователя
user_sessions = {}


def normalize_answer(answer: str) -> str:
    """Нормализует ответ пользователя"""
    return answer.lower().strip()


def format_word_with_ipa(word: Dict) -> str:
    """Форматирует слово с IPA транскрипцией. Возвращает "word - /ipa/" или просто "word" если IPA нет"""
    word_text = word.get('word', '')
    ipa = word.get('ipa', '')
    if ipa:
        return f"{word_text} — <i>{ipa}</i>"
    return word_text


def check_answer(user_answer: str, correct_answer: str) -> Tuple[bool, str]:
    """
    Проверяет ответ пользователя с нечеткой логикой.
    Возвращает (is_correct, status)
    """
    user_normalized = normalize_answer(user_answer)
    correct_normalized = normalize_answer(correct_answer)
    
    # Точное совпадение
    if user_normalized == correct_normalized:
        return True, "correct"
    
    # Проверка подобия (для синонимов)
    similarity = SequenceMatcher(None, user_normalized, correct_normalized).ratio()
    if similarity >= 0.7:
        return True, "similar"
    
    # Проверка если правильный ответ содержит ответ пользователя как подстроку
    if user_normalized in correct_normalized and len(user_normalized) > 2:
        return True, "similar"
    
    return False, "wrong"


def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Учить слова")],
            [KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="⚙️ Уровень"), KeyboardButton(text="ℹ️ О боте")]
        ],
        resize_keyboard=True
    )
    return keyboard


async def register_user(user_id: int):
    """Регистрирует нового пользователя"""
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {"registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_users(users)
        # Инициализируем квоты для нового пользователя
        init_user_quotas(user_id)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    logging.info(f"Пользователь {user_id}: выполнена команда /start")
    
    await register_user(user_id)
    
    # Получаем текущий уровень пользователя
    current_level = get_user_level(user_id)
    
    welcome_text = (
        "👋 Добро пожаловать в Mneme - бот для изучения английских слов!\n\n"
        "🧠 Метод: Spaced Repetition (интервальное повторение)\n"
        f"📚 Всего слов: {get_total_words()}\n"
        f"📖 На повторение: {get_words_to_review(user_id)}\n\n"
        f"📊 <b>Ваш уровень: {current_level}</b>\n\n"
        "Хотите изменить уровень сложности?"
    )
    
    # Создаем инлайн-клавиатуру для выбора уровня
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 A1 (Beginner)", callback_data="level_A1"),
            InlineKeyboardButton(text="🟡 A2 (Elementary)", callback_data="level_A2"),
        ],
        [
            InlineKeyboardButton(text="🟠 B1 (Intermediate)", callback_data="level_B1"),
            InlineKeyboardButton(text="🔴 B2 (Upper-Int)", callback_data="level_B2"),
        ],
        [
            InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_to_main"),
        ]
    ])
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(F.text == "📚 Учить слова")
async def start_learning(message: types.Message, state: FSMContext):
    """Начинает сеанс обучения или восстанавливает сохраненный"""
    user_id = message.from_user.id
    
    try:
        # Проверяем, был ли файл words.json обновлен
        check_words_json_updated()
        
        # Сначала проверяем есть ли сохраненный сеанс
        saved_session = load_session(user_id)
        
        # ✅ ИСПРАВЛЕНО: Проверяем корректность сеанса
        if saved_session and len(saved_session["words"]) > 0:
            current_index = saved_session.get('current_index', 0)
            total_words = len(saved_session['words'])
            words_remaining = total_words - current_index
            
            # Если сеанс уже пройден (current_index >= len(words)), удаляем его
            if words_remaining <= 0:
                logging.warning(f"⚠️ Пользователь {user_id}: найден завершенный сеанс (index={current_index}/{total_words}), удаляем")
                delete_session(user_id)
                saved_session = None  # Принудительно создаем новый
            else:
                # Есть сохраненный сеанс с оставшимися словами
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_session"),
                        InlineKeyboardButton(text="🔄 Начать новый", callback_data="new_session"),
                    ]
                ])
                
                await message.answer(
                    f"📚 <b>У вас есть активный сеанс!</b>\n\n"
                    f"Осталось слов: {words_remaining}\n\n"
                    "Хотите продолжить или начать новый?",
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return
        
        # Нет сохраненного сеанса - создаем новый
        user_level = get_user_level(user_id)  # Получаем уровень пользователя
        words = get_words_for_session(user_id, words_per_session=10, level=user_level)
        
        if not words:
            logging.info(f"Пользователь {user_id}: нет слов для повторения")
            await message.answer(
                "🎉 Нет слов для повторения! Вы выучили все слова. Вернитесь завтра.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Создаем новую сессию
        user_sessions[user_id] = {
            "words": words,
            "current_index": 0,
            "correct_count": 0,
            "error_count": 0,
            "dont_know_count": 0,
            "error_streak": 0,
            "start_time": int(time.time()),  # ✅ НОВОЕ: Для отслеживания длительности
            "newly_learned": 0  # ✅ НОВОЕ: Слов переведено в recall
        }
        
        # Сохраняем в БД для персистентности
        save_session(user_id, user_sessions[user_id])
        
        logging.info(f"Пользователь {user_id}: начата новая сеанс с {len(words)} словами")
        
        # Показываем первое слово в режиме learning
        await show_learning_mode(message, state, user_id)
        
    except Exception as e:
        logging.error(f"Ошибка при начале сеанса для пользователя {user_id}: {e}")
        await message.answer(
            "❌ Ошибка при загрузке слов. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )


async def show_learning_mode(message: types.Message, state: FSMContext, user_id: int):
    """Показывает слово в режиме LEARNING"""
    session = user_sessions.get(user_id)
    if not session or session["current_index"] >= len(session["words"]):
        return
    
    current_word = session["words"][session["current_index"]]
    
    # ✅ НОВОЕ: Проверяем, что слово существует и имеет необходимые поля
    if not current_word or not current_word.get('id'):
        await message.answer(
            "❌ Ошибка: слово больше не существует. Сеанс был сброшен.",
            reply_markup=get_main_keyboard()
        )
        logging.warning(f"Пользователь {user_id}: попытка показать удаленное слово в режиме learning")
        if user_id in user_sessions:
            del user_sessions[user_id]
        delete_session(user_id)
        return
    
    # Кнопки для режима learning
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Запомнил", callback_data=f"learned_{current_word['id']}"),
        ],
        [
            InlineKeyboardButton(text="🔁 Ещё раз", callback_data=f"repeat_{current_word['id']}"),
        ],
        [
            InlineKeyboardButton(text="❌ Не понял", callback_data=f"not_understood_{current_word['id']}"),
        ]
    ])
    
    word_display = format_word_with_ipa(current_word)
    
    word_text = (
        f"📚 <b>learning mode</b>\n\n"
        f"<b>{word_display}</b>\n\n"
        f"📖 <b>Перевод:</b> {current_word['translation']}\n\n"
        f"💡 <b>Ассоциация:</b> {current_word['association']}\n\n"
        f"📝 <b>Пример:</b> <i>{current_word['example']}</i>\n\n"
        "Ты запомнил слово?"
    )
    
    await message.answer(word_text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(LearningState.learning_mode)


async def show_recall_mode(message: types.Message, state: FSMContext, user_id: int):
    """Показывает слово в режиме RECALL"""
    session = user_sessions.get(user_id)
    if not session or session["current_index"] >= len(session["words"]):
        return
    
    current_word = session["words"][session["current_index"]]
    
    # ✅ НОВОЕ: Проверяем, что слово существует и имеет необходимые поля
    if not current_word or not current_word.get('id'):
        await message.answer(
            "❌ Ошибка: слово больше не существует. Сеанс был сброшен.",
            reply_markup=get_main_keyboard()
        )
        logging.warning(f"Пользователь {user_id}: попытка показать удаленное слово в режиме recall")
        if user_id in user_sessions:
            del user_sessions[user_id]
        delete_session(user_id)
        return
    
    # Кнопки для режима recall
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤔 Не знаю", callback_data=f"dont_know_{current_word['id']}"),
        ]
    ])
    
    word_display = format_word_with_ipa(current_word)
    word_text = f"🔄 <b>recall mode</b>\n\n<b>{word_display}</b>\n\nПереведи это слово на русский 👇"
    
    await message.answer(word_text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(LearningState.recall_input)


async def finish_session(message: types.Message, state: FSMContext, user_id: int):
    """Завершает сеанс обучения с адаптацией нагрузки"""
    session = user_sessions.get(user_id)
    if not session:
        return
    
    correct = session.get("correct_count", 0)
    errors = session.get("error_count", 0)
    dont_know = session.get("dont_know_count", 0)
    error_streak = session.get("error_streak", 0)
    total = correct + errors
    
    # Вычисляем точность
    accuracy = calculate_session_accuracy(correct, total)
    
    # ✅ НОВОЕ: Логируем сеанс в БД для отслеживания прогресса
    # ✅ ИСПРАВЛЕНО: start_time может не существовать если сеанс загружен из БД
    if "start_time" not in session:
        session["start_time"] = int(time.time())
    
    session_start = session.get("start_time", int(time.time()))
    duration_seconds = max(60, int(time.time()) - session_start)  # Минимум 60 секунд
    
    # ✅ НОВОЕ: Защита от пустых сеансов (если все слова были удалены)
    words_ids = [w.get('id', 0) for w in session.get('words', []) if w.get('id')]
    if len(words_ids) == 0:
        logging.warning(f"⚠️ Сеанс пользователя {user_id} содержит 0 слов (возможно, все были удалены)")
        await message.answer(
            "⚠️ Ошибка: Слова в вашем сеансе больше не существуют. Начните новый сеанс.",
            reply_markup=get_main_keyboard()
        )
        if user_id in user_sessions:
            del user_sessions[user_id]
        delete_session(user_id)
        await state.clear()
        return
    
    log_session(user_id, {
        'duration_seconds': duration_seconds,
        'words_count': len(session['words']),
        'correct_answers': correct,
        'incorrect_answers': errors,
        'new_words_learned': session.get('newly_learned', 0),
        'error_streak': error_streak,
        'words_ids': words_ids
    })
    
    # ✅ НОВОЕ: Проверяем и выдаем достижения
    new_achievements = check_and_award_achievements(user_id)
    if new_achievements:
        achievements_text = "🏆 <b>Новые достижения!</b>\n\n"
        for ach in new_achievements:
            achievements_text += f"{ach}\n"
        await message.answer(achievements_text, parse_mode="HTML")
    
    logging.info(f"Пользователь {user_id}: завершен сеанс (всего: {total}, правильно: {correct}, ошибок: {errors}, точность: {accuracy:.1f}%)") 
    
    # 📊 Результат сеанса
    if errors == 0:
        end_message = (
            f"🎉 <b>Отлично!</b>\n\n"
            f"Ты справился со всеми {total} словами без ошибок! 🌟\n\n"
            f"Точность: <b>{accuracy:.1f}%</b>"
        )
    elif errors == 1:
        end_message = (
            f"👏 <b>Хороший результат!</b>\n\n"
            f"Правильно: {correct}/{total}\n"
            f"Точность: <b>{accuracy:.1f}%</b>"
        )
    else:
        end_message = (
            f"💪 <b>Продолжай в том же духе!</b>\n\n"
            f"Правильно: {correct}/{total}\n"
            f"Точность: <b>{accuracy:.1f}%</b>"
        )
    
    # Дополнительная информация если были ошибки подряд
    extra_info = ""
    if error_streak >= 3:
        extra_info += f"\n\n⚠️ <i>3 ошибки подряд - сосредоточься на повторениях старых слов.</i>"
    elif dont_know > 0:
        extra_info += f"\n\n💡 <i>Нажимал(а) 'не знаю' {dont_know} раз(а). Подумай о новых ассоциациях!</i>"
    
    await message.answer(end_message + extra_info, reply_markup=get_main_keyboard(), parse_mode="HTML")
    
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    # Удаляем сеанс из БД
    delete_session(user_id)
    
    await state.clear()


# ==================== ОБРАБОТЧИКИ ВЫБОРА УРОВНЯ ====================

@dp.callback_query(F.data.startswith("level_"))
async def handle_level_selection(query: types.CallbackQuery, state: FSMContext):
    """Обработка выбора уровня сложности"""
    user_id = query.from_user.id
    level = query.data.replace("level_", "")  # Извлекаем уровень (A1, A2, B1, B2)
    
    # Сохраняем уровень пользователя
    set_user_level(user_id, level)
    
    level_names = {
        'A1': '🟢 A1 (Beginner) - Начинающий',
        'A2': '🟡 A2 (Elementary) - Элементарный',
        'B1': '🟠 B1 (Intermediate) - Средний',
        'B2': '🔴 B2 (Upper-Intermediate) - Выше среднего'
    }
    
    response_text = f"✅ <b>Уровень изменен!</b>\n\nТеперь вы учите: {level_names.get(level, level)}\n\n💡 Слова будут отобраны соответствующего уровня сложности."
    
    await query.answer("✅ Уровень выбран!", show_alert=True)
    await query.message.edit_text(response_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_to_main")]
    ]))
    

@dp.callback_query(F.data == "continue_to_main")
async def handle_continue_to_main(query: types.CallbackQuery, state: FSMContext):
    """Переход в главное меню"""
    await query.answer()
    await query.message.edit_text("👋 Выберите действие:", reply_markup=get_main_keyboard())


# Обработчики для продолжения/нового сеанса
@dp.callback_query(F.data == "continue_session")
async def handle_continue_session(query: types.CallbackQuery, state: FSMContext):
    """Продолжить сохраненный сеанс"""
    user_id = query.from_user.id
    
    saved_session = load_session(user_id)
    if saved_session:
        # ✅ НОВОЕ: Проверяем, что сеанс содержит слова (они не были удалены)
        if not saved_session.get("words") or len(saved_session["words"]) == 0:
            await query.answer("⚠️ Слова в вашем сеансе больше не существуют. Начнем новый сеанс.", show_alert=True)
            delete_session(user_id)
            logging.info(f"Пользователь {user_id}: сеанс содержал удаленные слова, начинаем новый")
            await start_learning(query.message, state)
            return
        
        user_sessions[user_id] = saved_session
        logging.info(f"Пользователь {user_id}: возобновлен сеанс ({len(saved_session['words'])} слов)")
        
        await query.answer()
        
        # Получаем текущее слово
        if saved_session["current_index"] < len(saved_session["words"]):
            current_word = saved_session["words"][saved_session["current_index"]]
            next_word_progress = get_user_progress(user_id).get("words", {}).get(str(current_word["id"]), {})
            next_mode = next_word_progress.get("mode", "learning")
            
            if next_mode == "learning":
                await show_learning_mode(query.message, state, user_id)
            else:
                await show_recall_mode(query.message, state, user_id)
        else:
            # ✅ ИСПРАВЛЕНО: Была finish_learning_session, правильно finish_session
            await finish_session(query.message, state, user_id)
    else:
        await query.answer()


@dp.callback_query(F.data == "new_session")
async def handle_new_session(query: types.CallbackQuery, state: FSMContext):
    """Начать новый сеанс"""
    user_id = query.from_user.id
    
    # Удаляем сохраненный сеанс
    delete_session(user_id)
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    await query.answer()
    
    # Начинаем новый сеанс
    await start_learning(query.message, state)


@dp.callback_query(F.data.startswith("learned_"))
async def handle_learned(query: types.CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Запомнил' в режиме learning"""
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await query.answer("❌ Сессия не найдена", show_alert=True)
        return
    
    # ✅ НОВОЕ: Защита от выхода за границы массива
    if session["current_index"] >= len(session["words"]):
        logging.warning(f"⚠️ Пользователь {user_id}: current_index ({session['current_index']}) >= len(words) ({len(session['words'])})")
        await query.answer("⚠️ Ошибка: сеанс завершен. Начните новый.", show_alert=True)
        await finish_session(query.message, state, user_id)
        return
    
    current_word = session["words"][session["current_index"]]
    word_id = current_word["id"]
    
    logging.info(f"Пользователь {user_id}: запомнил слово '{current_word['word']}'")
    
    # Переводим слово в режим recall на немедленное повторение
    progress = get_user_progress(user_id)
    word_progress = progress.get("words", {}).get(str(word_id), {})
    attempt_count = word_progress.get("attempt_count", 0)
    
    next_review, new_attempt_count, new_mode = calculate_next_review(
        knew_it=True,
        attempt_count=attempt_count,
        mode="learning"
    )
    
    add_or_update_word_progress(
        user_id, word_id, next_review,
        mode=new_mode, attempt_count=new_attempt_count
    )
    
    await query.answer("✅ Отлично! Переходим к проверке...")
    
    # ✅ НОВОЕ: Считаем слова, переведенные в recall
    session["newly_learned"] = session.get("newly_learned", 0) + 1
    
    # Переходим в режим recall
    session["current_index"] += 1
    save_session(user_id, session)  # Сохраняем в БД
    
    if session["current_index"] < len(session["words"]):
        await show_recall_mode(query.message, state, user_id)
    else:
        await finish_session(query.message, state, user_id)


@dp.callback_query(F.data.startswith("repeat_"))
async def handle_repeat(query: types.CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Ещё раз' в режиме learning"""
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await query.answer("❌ Сессия не найдена", show_alert=True)
        return
    
    # ✅ НОВОЕ: Защита от выхода за границы массива
    if session["current_index"] >= len(session["words"]):
        logging.warning(f"⚠️ Пользователь {user_id}: current_index ({session['current_index']}) >= len(words) ({len(session['words'])})")
        await query.answer("⚠️ Ошибка: сеанс завершен. Начните новый.", show_alert=True)
        await finish_session(query.message, state, user_id)
        return
    
    current_word = session["words"][session["current_index"]]
    logging.info(f"Пользователь {user_id}: повтор слова '{current_word['word']}'")
    
    await query.answer("🔁 Давайте еще раз...")
    await show_learning_mode(query.message, state, user_id)


@dp.callback_query(F.data.startswith("not_understood_"))
async def handle_not_understood(query: types.CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Не понял' в режиме learning"""
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await query.answer("❌ Сессия не найдена", show_alert=True)
        return
    
    # ✅ НОВОЕ: Защита от выхода за границы массива
    if session["current_index"] >= len(session["words"]):
        logging.warning(f"⚠️ Пользователь {user_id}: current_index ({session['current_index']}) >= len(words) ({len(session['words'])})")
        await query.answer("⚠️ Ошибка: сеанс завершен. Начните новый.", show_alert=True)
        await finish_session(query.message, state, user_id)
        return
    
    current_word = session["words"][session["current_index"]]
    
    # Показываем упрощенное объяснение
    word_display = format_word_with_ipa(current_word)
    help_text = (
        f"<b>Помощь с {word_display}:</b>\n\n"
        f"<b>Простой перевод:</b> {current_word['translation']}\n\n"
        f"Попробуй еще раз запомнить это слово."
    )
    
    await query.message.answer(help_text, parse_mode="HTML")
    
    logging.info(f"Пользователь {user_id}: запросил помощь для '{current_word['word']}'")
    await query.answer("📚 Давайте еще раз...")
    
    # Остаемся в режиме learning
    await show_learning_mode(query.message, state, user_id)


@dp.callback_query(F.data.startswith("dont_know_"))
async def handle_dont_know(query: types.CallbackQuery, state: FSMContext):
    """Пользователь нажал 'Не знаю' в режиме recall"""
    user_id = query.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await query.answer("❌ Сессия не найдена", show_alert=True)
        return
    
    # ✅ НОВОЕ: Защита от выхода за границы массива
    if session["current_index"] >= len(session["words"]):
        logging.warning(f"⚠️ Пользователь {user_id}: current_index ({session['current_index']}) >= len(words) ({len(session['words'])})")
        await query.answer("⚠️ Ошибка: сеанс завершен. Начните новый.", show_alert=True)
        await finish_session(query.message, state, user_id)
        return
    
    current_word = session["words"][session["current_index"]]
    word_id = current_word["id"]
    
    session["error_count"] = session.get("error_count", 0) + 1
    session["dont_know_count"] = session.get("dont_know_count", 0) + 1
    session["error_streak"] = session.get("error_streak", 0) + 1
    
    logging.info(f"Пользователь {user_id}: не знает слово '{current_word['word']}'")
    
    # ✅ НОВОЕ: Логируем ошибку (тип "forgot" - забыл)
    log_word_error(
        user_id=user_id,
        word_id=word_id,
        error_type='forgot',
        user_answer='',
        correct_answer=current_word['translation'],
        session_id=None
    )
    
    # Показываем правильный ответ
    word_display = format_word_with_ipa(current_word)
    answer_text = (
        f"📌 <b>Вот правильный ответ:</b>\n\n"
        f"<b>{word_display}</b> — {current_word['translation']}\n\n"
        f"<b>Ассоциация:</b> {current_word['association']}\n\n"
        f"<b>Пример:</b> <i>{current_word['example']}</i>\n\n"
        "Это слово вернулось в режим обучения."
    )
    
    await query.message.answer(answer_text, parse_mode="HTML")
    
    # Переводим слово обратно в режим learning на 10 минут
    next_review, new_attempt_count, new_mode = calculate_next_review(
        knew_it=False,
        attempt_count=0,
        mode="recall"
    )
    
    add_or_update_word_progress(
        user_id, word_id, next_review,
        mode=new_mode, attempt_count=new_attempt_count
    )
    
    await query.answer("📚 Слово вернулось в обучение...")
    
    # Переходим к следующему слову
    session["current_index"] += 1
    
    if session["current_index"] < len(session["words"]):
        # Выбираем случайно: показываем learning или recall для следующего слова
        next_word = session["words"][session["current_index"]]
        next_word_progress = get_user_progress(user_id).get("words", {}).get(str(next_word["id"]), {})
        next_mode = next_word_progress.get("mode", "learning")
        
        if next_mode == "learning":
            await show_learning_mode(query.message, state, user_id)
        else:
            await show_recall_mode(query.message, state, user_id)
    else:
        await finish_session(query.message, state, user_id)


@dp.message(LearningState.recall_input)
async def handle_recall_answer(message: types.Message, state: FSMContext):
    """Обрабатывает ввод пользователя в режиме recall"""
    user_id = message.from_user.id
    session = user_sessions.get(user_id)
    
    if not session:
        await message.answer("❌ Сессия не найдена", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    # Проверка границ массива слов
    if session["current_index"] >= len(session["words"]):
        logging.warning(f"Пользователь {user_id}: индекс {session['current_index']} выходит за границы массива слов (всего {len(session['words'])})")
        await finish_session(message, state, user_id)
        return
    
    current_word = session["words"][session["current_index"]]
    word_id = current_word["id"]
    user_answer = message.text
    
    # Проверяем ответ
    is_correct, status = check_answer(user_answer, current_word["translation"])
    
    if is_correct:
        session["correct_count"] = session.get("correct_count", 0) + 1
        session["error_streak"] = 0  # Ресет ошибок на правильный ответ
        
        logging.info(f"Пользователь {user_id}: правильный ответ '{user_answer}' для '{current_word['word']}'")
        
        if status == "correct":
            response = "✅ <b>Точный ответ!</b>"
        else:
            response = f"✅ <b>Верно!</b>\n\nОсновной вариант: <i>{current_word['translation']}</i>"
        
        await message.answer(response, parse_mode="HTML")
        
        # Обновляем прогресс
        progress = get_user_progress(user_id)
        word_progress = progress.get("words", {}).get(str(word_id), {})
        attempt_count = word_progress.get("attempt_count", 0)
        
        next_review, new_attempt_count, new_mode = calculate_next_review(
            knew_it=True,
            attempt_count=attempt_count,
            mode="recall"
        )
        
        add_or_update_word_progress(
            user_id, word_id, next_review,
            mode=new_mode, attempt_count=new_attempt_count
        )
        
    else:
        session["error_count"] = session.get("error_count", 0) + 1
        session["error_streak"] = session.get("error_streak", 0) + 1
        
        logging.warning(f"Пользователь {user_id}: неправильный ответ '{user_answer}' для '{current_word['word']}' (серия: {session['error_streak']})")
        
        # ✅ НОВОЕ: Логируем ошибку в историю
        log_word_error(
            user_id=user_id,
            word_id=word_id,
            error_type='wrong_answer',
            user_answer=user_answer,
            correct_answer=current_word['translation'],
            session_id=None  # будет заполнено при логировании сеанса
        )
        
        word_display = format_word_with_ipa(current_word)
        wrong_text = (
            f"❌ <b>Неправильно!</b>\n\n"
            f"<b>Правильный ответ:</b> {current_word['translation']}\n\n"
            f"<b>Слово:</b> {word_display}\n\n"
            f"<b>Ассоциация:</b> {current_word['association']}"
        )
        
        await message.answer(wrong_text, parse_mode="HTML")
        
        # Переводим слово обратно в режим learning на 10 минут
        next_review, new_attempt_count, new_mode = calculate_next_review(
            knew_it=False,
            attempt_count=0,
            mode="recall"
        )
        
        add_or_update_word_progress(
            user_id, word_id, next_review,
            mode=new_mode, attempt_count=new_attempt_count
        )
    
    # Переходим к следующему слову
    session["current_index"] += 1
    save_session(user_id, session)  # Сохраняем в БД
    
    if session["current_index"] < len(session["words"]):
        next_word = session["words"][session["current_index"]]
        next_word_progress = get_user_progress(user_id).get("words", {}).get(str(next_word["id"]), {})
        next_mode = next_word_progress.get("mode", "learning")
        
        if next_mode == "learning":
            await show_learning_mode(message, state, user_id)
        else:
            await show_recall_mode(message, state, user_id)
    else:
        await finish_session(message, state, user_id)



@dp.message(F.text == "⚙️ Уровень")
async def change_level(message: types.Message):
    """Изменить уровень сложности"""
    user_id = message.from_user.id
    current_level = get_user_level(user_id)
    
    level_names = {
        'A1': '🟢 A1 (Beginner) - Начинающий',
        'A2': '🟡 A2 (Elementary) - Элементарный',
        'B1': '🟠 B1 (Intermediate) - Средний',
        'B2': '🔴 B2 (Upper-Intermediate) - Выше среднего'
    }
    
    text = f"📊 <b>Выбор уровня сложности</b>\n\nТекущий уровень: <b>{level_names.get(current_level, current_level)}</b>\n\nВыберите новый уровень:"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 A1 (Beginner)", callback_data="level_A1"),
            InlineKeyboardButton(text="🟡 A2 (Elementary)", callback_data="level_A2"),
        ],
        [
            InlineKeyboardButton(text="🟠 B1 (Intermediate)", callback_data="level_B1"),
            InlineKeyboardButton(text="🔴 B2 (Upper-Int)", callback_data="level_B2"),
        ],
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@dp.message(F.text == "📊 Мой прогресс")
async def show_progress(message: types.Message):
    """Показывает прогресс пользователя"""
    user_id = message.from_user.id
    
    total_words = get_total_words()
    words_to_review = get_words_to_review(user_id)
    
    # Подсчитываем выученные слова
    user_progress = get_user_progress(user_id)
    learned_count = 0
    learning_count = 0
    
    for word_id, word_data in user_progress.get("words", {}).items():
        if word_data.get("attempt_count", 0) >= 4:  # 4 правильных попытки = выучено
            learned_count += 1
        elif word_data.get("mode") == "learning" or word_data.get("mode") == "recall":
            learning_count += 1
    
    progress_text = (
        f"📊 <b>Твой прогресс:</b>\n\n"
        f"📚 <b>Всего слов:</b> {total_words}\n"
        f"📖 <b>На повторение сегодня:</b> {words_to_review}\n"
        f"🧠 <b>В процессе обучения:</b> {learning_count}\n"
        f"✅ <b>Выучено:</b> {learned_count}\n\n"
        f"💪 Продолжай в том же духе!"
    )
    
    await message.answer(progress_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    """Информация о боте"""
    user_id = message.from_user.id
    quotas = get_user_quotas(user_id)
    
    about_text = (
        "ℹ️ <b>О боте Mneme:</b>\n\n"
        "Этот бот поможет тебе выучить английские слова методом <b>Spaced Repetition</b> "
        "(интервальное повторение) с адаптивной нагрузкой.\n\n"
        
        "<b>📚 Как это работает:</b>\n\n"
        "<b>1️⃣ Режим обучения (Learning):</b>\n"
        "Видишь слово с переводом и ассоциацией\n"
        "• ✅ Запомнил — переходим к проверке\n"
        "• 🔁 Ещё раз — повторяем это же слово\n"
        "• ❌ Не понял — показываем дополнительную помощь\n\n"
        
        "<b>2️⃣ Режим проверки (Recall):</b>\n"
        "Видишь англ. слово и пишешь перевод\n"
        "• ✅ Правильный ответ → интервал повторения\n"
        "• ❌ Неправильный ответ → обратно в обучение\n"
        "• 🤔 Не знаю → показываем ответ и обучение\n\n"
        
        "<b>⏱️ Интервалы повторения:</b>\n"
        "1-й правильный ответ → 10 минут\n"
        "2-й правильный ответ → 1 день\n"
        "3-й правильный ответ → 3 дня\n"
        "4-й правильный ответ → 7 дней\n"
        "Ошибка → обратно на 10 минут\n\n"
        
        "<b>📊 Адаптивная нагрузка:</b>\n"
        f"🎯 Твои текущие параметры:\n"
        f"• Новые слова в день: <b>{quotas.get('new_words', 5)}</b>\n"
        f"• Повторений в день: <b>{quotas.get('review_words', 20)}</b>\n\n"
        f"Нагрузка автоматически адаптируется после каждого сеанса в зависимости от твоей точности.\n\n"
        
        "<b>💡 Советы:</b>\n"
        "• Не спешите с нажатием 'Запомнил'\n"
        "• Ассоциации помогают запомнить лучше\n"
        "• Консистентность важнее интенсивности!\n"
    )
    
    await message.answer(about_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Показывает расширенную статистику ученика"""
    user_id = message.from_user.id
    
    # ✅ ИСПРАВЛЕНО: Функции теперь импортированы в начале
    try:
        progress = get_student_progress(user_id)
        stats = progress.get('statistics', {})
        level = progress.get('learning_level', {})
        achievements = get_achievements(user_id)
        
        stats_text = f"""
📊 <b>Ваша подробная статистика</b>

<b>🎯 Уровень:</b> {level.get('level', 'Новичок')}
{level.get('description', '')}

<b>📚 Прогресс:</b>
• Выучено слов: <b>{stats.get('total_words_learned', 0)}</b>
• Всего сеансов: <b>{stats.get('total_sessions', 0)}</b>
• Правильных ответов: <b>{stats.get('total_correct_answers', 0)}</b>
• Ошибок: <b>{stats.get('total_incorrect_answers', 0)}</b>

<b>📈 Точность и время:</b>
• Средняя точность: <b>{stats.get('average_accuracy', 0):.1f}%</b>
• Минут учебы: <b>{stats.get('total_study_minutes', 0)}</b>

<b>🔥 Полосы ошибок:</b>
• Текущая: <b>{stats.get('current_error_streak', 0)}</b>
• Максимальная: <b>{stats.get('longest_error_streak', 0)}</b>
        """.strip()
        
        if achievements:
            stats_text += f"\n\n🏆 <b>Достижения:</b>\n"
            for ach in achievements[:5]:  # Показываем первые 5
                stats_text += f"• {ach['achievement_name']}\n"
            if len(achievements) > 5:
                stats_text += f"• ... и еще {len(achievements) - 5} достижений"
        
        await message.answer(stats_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка при получении статистики для {user_id}: {e}")
        await message.answer(
            "❌ Ошибка при загрузке статистики. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )


@dp.message(Command("learn"))
async def cmd_learn(message: types.Message, state: FSMContext):
    """Обработчик команды /learn"""
    await start_learning(message, state)


@dp.message(Command("difficult"))
async def cmd_difficult(message: types.Message):
    """Показывает слова, в которых пользователь часто ошибается"""
    user_id = message.from_user.id
    
    try:
        difficult = get_most_problematic_words(user_id, limit=10)
        
        if not difficult:
            await message.answer(
                "✅ <b>Отличная работа!</b>\n\n"
                "Нет слов, в которых вы часто ошибаетесь. Продолжайте учиться!",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            return
        
        difficult_text = "⚠️ <b>Слова, в которых вы часто ошибаетесь:</b>\n\n"
        
        for i, word in enumerate(difficult, 1):
            difficult_text += f"{i}. <b>{word['word']}</b> — {word['translation']}\n"
            difficult_text += f"   Ошибок: {word['error_count']}\n\n"
        
        difficult_text += "💡 Рекомендуем повторить эти слова чаще!"
        
        await message.answer(difficult_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка при получении трудных слов для {user_id}: {e}")
        await message.answer(
            "❌ Ошибка при загрузке данных. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )


@dp.message(Command("achievements"))
async def cmd_achievements(message: types.Message):
    """Показывает все полученные достижения"""
    user_id = message.from_user.id
    
    try:
        achievements = get_achievements(user_id)
        
        if not achievements:
            await message.answer(
                "📭 <b>Достижений пока нет</b>\n\n"
                "Продолжайте учиться и вы скоро разблокируете первые достижения! 🚀",
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
            return
        
        achievements_text = "🏆 <b>Ваши достижения:</b>\n\n"
        
        for ach in achievements:
            earned_date = ach['earned_at'].split('T')[0] if 'T' in ach.get('earned_at', '') else ach.get('earned_at', 'неизвестная дата')
            achievements_text += f"{ach['achievement_name']} — {earned_date}\n"
        
        achievements_text += f"\n<b>Всего достижений: {len(achievements)}</b>"
        
        await message.answer(achievements_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка при получении достижений для {user_id}: {e}")
        await message.answer(
            "❌ Ошибка при загрузке достижений. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отменяет текущий сеанс"""
    user_id = message.from_user.id
    
    if user_id in user_sessions:
        session = user_sessions[user_id]
        logging.info(f"Пользователь {user_id}: отменен сеанс")
        
        # Сохраняем сеанс в БД для возможности продолжения позже
        save_session(user_id, session)
        
        await message.answer(
            "❌ <b>Сеанс отменен</b>\n\n"
            "Твой прогресс сохранен. Можешь продолжить когда захочешь!",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
        del user_sessions[user_id]
        await state.clear()
    else:
        await message.answer(
            "ℹ️ На данный момент нет активного сеанса",
            reply_markup=get_main_keyboard()
        )


async def send_daily_reminder():
    """Отправляет напоминание о обучении"""
    users = load_users()
    
    for user_id_str in users.keys():
        try:
            user_id = int(user_id_str)
            words_to_review = get_words_to_review(user_id)
            
            if words_to_review > 0:
                await bot.send_message(
                    user_id,
                    f"📚 <b>Напоминание:</b> У вас {words_to_review} слов(а) на повторение!\n\n"
                    "Нажмите на кнопку 📚 Учить слова чтобы начать сеанс.",
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML"
                )
        except Exception as e:
            logging.error(f"Ошибка при отправке напоминания пользователю {user_id_str}: {e}")


# ==================== АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ СЛОВ ====================

async def auto_sync_words():
    """Автоматически синхронизирует слова из JSON файла каждый час"""
    try:
        logging.info("🔄 Проверка обновлений слов из JSON...")
        sync_words_from_json()
        logging.info("✅ Синхронизация слов завершена успешно")
    except Exception as e:
        logging.error(f"❌ Ошибка при синхронизации слов: {e}")


async def schedule_tasks():
    """Планирует регулярные задачи"""
    try:
        # Добавляем задачу для автоматической синхронизации слов (каждый час)
        scheduler.add_job(
            auto_sync_words,
            "interval",
            hours=1,
            id="auto_sync_words",
            replace_existing=True  # Заменяет задачу если она уже была
        )
        logging.info("✅ Запланирована автоматическая синхронизация слов (каждый час)")
        
        # Добавляем задачу для отправки ежедневных напоминаний
        scheduler.add_job(
            send_daily_reminder,
            "cron",
            hour=9,
            minute=0,
            id="daily_reminder"
        )
        logging.info("✅ Запланирована ежедневная задача напоминания (9:00)")
    except Exception as e:
        logging.error(f"Ошибка при планировании задач: {e}")


async def main():
    """Главная функция для запуска бота"""
    # Добавляем все задачи в планировщик
    await schedule_tasks()
    
    # Стартуем планировщик (без await - это синхронный вызов)
    scheduler.start()
    logging.info("✅ Планировщик задач запущен")
    
    # Запускаем диспетчер (это блокирующий вызов)
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logging.info("📛 Получен сигнал остановки бота")
    finally:
        logging.info("🛑 Бот остановлен")


if __name__ == "__main__":
    print("🚀 Бот запущен с новой системой Learning/Recall...")
    asyncio.run(main())
