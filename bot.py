# -*- coding: utf-8 -*-
import asyncio
import logging
import random
import time  # ✅ ИСПРАВЛЕНО: Добавлен импорт в начало
from datetime import datetime
from typing import Dict

from app_config import bootstrap_environment

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scheduler_tasks import auto_sync_words, schedule_tasks
from storage import (
    initialize_storage,
    load_users, save_users, add_or_update_word_progress, get_user_progress, 
    init_user_quotas, get_user_quotas,
    save_session, load_session, delete_session,  # Функции сеансов
    # Новые функции для отслеживания прогресса ученика
    log_session, log_word_error, check_and_award_achievements, get_achievements,
    # Функции для команд пользователя
    get_student_progress, get_most_problematic_words,
    # Функция для отслеживания изменений файла
    check_words_json_updated,
    # Функции для работы с уровнем пользователя
    get_user_level, set_user_level,
    # ✅ Новые функции для статистики по уровню
    get_user_progress_for_level
)
from learning import (
    get_words_for_session,
    calculate_next_review,
    get_total_words,
    get_words_to_review,
    calculate_session_accuracy
)
from db import sync_words_from_json
from handlers_profile import register_profile_handlers
from text_utils import check_answer, esc, format_word_with_ipa
from ui import get_main_keyboard
# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================
logging.info("🔧 Инициализация базы данных...")
initialize_storage()
logging.info("✅ База данных готова!")

# ⚙️ КОНФИГУРАЦИЯ
TOKEN = bootstrap_environment()

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

register_profile_handlers(
    dp=dp,
    get_main_keyboard=get_main_keyboard,
    get_user_level=get_user_level,
    set_user_level=set_user_level,
    get_user_progress_for_level=get_user_progress_for_level,
    get_user_quotas=get_user_quotas,
    get_student_progress=get_student_progress,
    get_achievements=get_achievements,
    get_most_problematic_words=get_most_problematic_words,
)


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
        f"📖 <b>Перевод:</b> {esc(current_word.get('translation', ''))}\n\n"
        f"💡 <b>Ассоциация:</b> {esc(current_word.get('association', ''))}\n\n"
        f"📝 <b>Пример:</b> <i>{esc(current_word.get('example', ''))}</i>\n\n"
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

@dp.callback_query(F.data == "continue_to_main")
async def handle_continue_to_main(query: types.CallbackQuery, state: FSMContext):
    """Переход в главное меню"""
    await query.answer()
    await query.message.delete()
    await query.message.answer("👋 Выберите действие:", reply_markup=get_main_keyboard())


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
        f"<b>Простой перевод:</b> {esc(current_word.get('translation', ''))}\n\n"
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
        f"<b>{word_display}</b> — {esc(current_word.get('translation', ''))}\n\n"
        f"<b>Ассоциация:</b> {esc(current_word.get('association', ''))}\n\n"
        f"<b>Пример:</b> <i>{esc(current_word.get('example', ''))}</i>\n\n"
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
    save_session(user_id, session)
    
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


@dp.message(LearningState.recall_input, F.text)
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
    user_answer = message.text or ""
    
    # Проверяем ответ
    is_correct, status = check_answer(user_answer, current_word["translation"])
    
    if is_correct:
        session["correct_count"] = session.get("correct_count", 0) + 1
        session["error_streak"] = 0  # Ресет ошибок на правильный ответ
        
        logging.info(f"Пользователь {user_id}: правильный ответ '{user_answer}' для '{current_word['word']}'")
        
        if status == "correct":
            response = "✅ <b>Точный ответ!</b>"
        else:
            response = f"✅ <b>Верно!</b>\n\nОсновной вариант: <i>{esc(current_word.get('translation', ''))}</i>"
        
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
            f"<b>Правильный ответ:</b> {esc(current_word.get('translation', ''))}\n\n"
            f"<b>Слово:</b> {word_display}\n\n"
            f"<b>Ассоциация:</b> {esc(current_word.get('association', ''))}"
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


@dp.message(LearningState.recall_input)
async def handle_recall_non_text(message: types.Message):
    """Отсекает non-text сообщения в режиме recall"""
    await message.answer("✍️ Введите перевод текстом, пожалуйста.")



@dp.message(Command("learn"))
async def cmd_learn(message: types.Message, state: FSMContext):
    """Обработчик команды /learn"""
    await start_learning(message, state)


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

async def main():
    """Главная функция для запуска бота"""
    # Добавляем все задачи в планировщик
    await schedule_tasks(
        scheduler=scheduler,
        send_daily_reminder=send_daily_reminder,
        auto_sync_callback=lambda: auto_sync_words(sync_words_from_json),
    )
    
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
