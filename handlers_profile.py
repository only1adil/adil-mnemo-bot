import logging
from typing import Callable

from aiogram import F, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def register_profile_handlers(
    dp: Dispatcher,
    get_main_keyboard: Callable[[], types.ReplyKeyboardMarkup],
    get_user_level: Callable[[int], str],
    set_user_level: Callable[[int, str], None],
    get_user_progress_for_level: Callable[[int, str], dict],
    get_user_quotas: Callable[[int], dict],
    get_student_progress: Callable[[int], dict],
    get_achievements: Callable[[int], list],
    get_most_problematic_words: Callable[[int, int], list],
) -> None:
    @dp.callback_query(F.data.startswith("level_"))
    async def handle_level_selection(query: types.CallbackQuery):
        user_id = query.from_user.id
        level = query.data.replace("level_", "")

        set_user_level(user_id, level)

        level_names = {
            "A1": "🟢 A1 (Beginner) - Начинающий",
            "A2": "🟡 A2 (Elementary) - Элементарный",
            "B1": "🟠 B1 (Intermediate) - Средний",
            "B2": "🔴 B2 (Upper-Intermediate) - Выше среднего",
        }

        response_text = (
            "✅ <b>Уровень изменен!</b>\n\n"
            f"Теперь вы учите: {level_names.get(level, level)}\n\n"
            "💡 Слова будут отобраны соответствующего уровня сложности."
        )

        await query.answer("✅ Уровень выбран!", show_alert=True)
        await query.message.edit_text(
            response_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_to_main")]]
            ),
        )

    @dp.message(F.text == "⚙️ Уровень")
    async def change_level(message: types.Message):
        user_id = message.from_user.id
        current_level = get_user_level(user_id)

        level_names = {
            "A1": "🟢 A1 (Beginner) - Начинающий",
            "A2": "🟡 A2 (Elementary) - Элементарный",
            "B1": "🟠 B1 (Intermediate) - Средний",
            "B2": "🔴 B2 (Upper-Intermediate) - Выше среднего",
        }

        text = (
            "📊 <b>Выбор уровня сложности</b>\n\n"
            f"Текущий уровень: <b>{level_names.get(current_level, current_level)}</b>\n\n"
            "Выберите новый уровень:"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🟢 A1 (Beginner)", callback_data="level_A1"),
                    InlineKeyboardButton(text="🟡 A2 (Elementary)", callback_data="level_A2"),
                ],
                [
                    InlineKeyboardButton(text="🟠 B1 (Intermediate)", callback_data="level_B1"),
                    InlineKeyboardButton(text="🔴 B2 (Upper-Int)", callback_data="level_B2"),
                ],
            ]
        )

        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    @dp.message(F.text == "📊 Мой прогресс")
    async def show_progress(message: types.Message):
        user_id = message.from_user.id
        current_level = get_user_level(user_id)
        progress = get_user_progress_for_level(user_id, current_level)

        level_names = {
            "A1": "🟢 A1 (Beginner)",
            "A2": "🟡 A2 (Elementary)",
            "B1": "🟠 B1 (Intermediate)",
            "B2": "🔴 B2 (Upper-Int)",
        }

        level_display = level_names.get(current_level, current_level)
        total = progress.get("total", 0)
        learned = progress.get("learned", 0)
        progress_percent = int((learned / total * 100) if total > 0 else 0)

        filled = progress_percent // 10
        empty = 10 - filled
        progress_bar = "█" * filled + "░" * empty

        progress_text = (
            f"📊 <b>Твой прогресс: {level_display}</b>\n\n"
            f"📚 <b>Всего слов на этом уровне:</b> {learned}/{total}\n"
            f"<code>[{progress_bar}] {progress_percent}%</code>\n\n"
            f"📖 <b>На повторение сегодня:</b> {progress.get('to_review', 0)}\n"
            f"🧠 <b>В процессе обучения:</b> {progress.get('learning', 0)}\n"
            f"✅ <b>Выучено:</b> {progress.get('learned', 0)}\n\n"
        )

        if progress_percent == 100:
            progress_text += "🎉 <b>Вы освоили этот уровень!</b>\n"
            progress_text += "Попробуйте перейти на следующий уровень через команду ⚙️"
        elif progress_percent == 0 and progress.get("learning", 0) == 0:
            progress_text += "🚀 Начните учить слова нажав 📚 Учить слова"
        else:
            progress_text += "💪 Продолжай в том же духе!"

        await message.answer(progress_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

    @dp.message(F.text == "ℹ️ О боте")
    async def about_bot(message: types.Message):
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
            "🎯 Твои текущие параметры:\n"
            f"• Новые слова в день: <b>{quotas.get('new_words', 5)}</b>\n"
            f"• Повторений в день: <b>{quotas.get('review_words', 20)}</b>\n\n"
            "Нагрузка автоматически адаптируется после каждого сеанса в зависимости от твоей точности.\n\n"
            "<b>💡 Советы:</b>\n"
            "• Не спешите с нажатием 'Запомнил'\n"
            "• Ассоциации помогают запомнить лучше\n"
            "• Консистентность важнее интенсивности!\n"
        )

        await message.answer(about_text, reply_markup=get_main_keyboard(), parse_mode="HTML")

    @dp.message(Command("stats"))
    async def cmd_stats(message: types.Message):
        user_id = message.from_user.id
        try:
            progress = get_student_progress(user_id)
            stats = progress.get("statistics", {})
            level = progress.get("learning_level", {})
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
                stats_text += "\n\n🏆 <b>Достижения:</b>\n"
                for ach in achievements[:5]:
                    stats_text += f"• {ach['achievement_name']}\n"
                if len(achievements) > 5:
                    stats_text += f"• ... и еще {len(achievements) - 5} достижений"

            await message.answer(stats_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        except Exception as e:
            logging.error(f"Ошибка при получении статистики для {user_id}: {e}")
            await message.answer(
                "❌ Ошибка при загрузке статистики. Попробуйте позже.",
                reply_markup=get_main_keyboard(),
            )

    @dp.message(Command("difficult"))
    async def cmd_difficult(message: types.Message):
        user_id = message.from_user.id
        try:
            difficult = get_most_problematic_words(user_id, limit=10)

            if not difficult:
                await message.answer(
                    "✅ <b>Отличная работа!</b>\n\n"
                    "Нет слов, в которых вы часто ошибаетесь. Продолжайте учиться!",
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML",
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
                reply_markup=get_main_keyboard(),
            )

    @dp.message(Command("achievements"))
    async def cmd_achievements(message: types.Message):
        user_id = message.from_user.id
        try:
            achievements = get_achievements(user_id)

            if not achievements:
                await message.answer(
                    "📭 <b>Достижений пока нет</b>\n\n"
                    "Продолжайте учиться и вы скоро разблокируете первые достижения! 🚀",
                    reply_markup=get_main_keyboard(),
                    parse_mode="HTML",
                )
                return

            achievements_text = "🏆 <b>Ваши достижения:</b>\n\n"
            for ach in achievements:
                earned_date = (
                    ach["earned_at"].split("T")[0]
                    if "T" in ach.get("earned_at", "")
                    else ach.get("earned_at", "неизвестная дата")
                )
                achievements_text += f"{ach['achievement_name']} — {earned_date}\n"
            achievements_text += f"\n<b>Всего достижений: {len(achievements)}</b>"

            await message.answer(achievements_text, reply_markup=get_main_keyboard(), parse_mode="HTML")
        except Exception as e:
            logging.error(f"Ошибка при получении достижений для {user_id}: {e}")
            await message.answer(
                "❌ Ошибка при загрузке достижений. Попробуйте позже.",
                reply_markup=get_main_keyboard(),
            )
