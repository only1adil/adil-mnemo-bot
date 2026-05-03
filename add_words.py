#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для удобного добавления новых слов в words.json
Использование: python add_words.py
"""

import json
from pathlib import Path
from datetime import datetime


def load_words():
    """Загружает существующие слова из JSON"""
    try:
        with open('words.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ Файл words.json не найден!")
        return []


def save_words(words):
    """Сохраняет слова в JSON"""
    try:
        with open('words.json', 'w', encoding='utf-8') as f:
            json.dump(words, f, ensure_ascii=False, indent=2)
        print(f"✅ Файл обновлен: {len(words)} слов в базе")
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении: {e}")
        return False


def get_next_id(words):
    """Находит следующий доступный ID"""
    if not words:
        return 1
    return max(w.get('id', 0) for w in words) + 1


def add_single_word():
    """Интерактивное добавление одного слова"""
    words = load_words()
    
    if not words:
        print("⚠️ База слов пуста, начинаем с ID=1")
        next_id = 1
    else:
        next_id = get_next_id(words)
    
    print(f"\n📝 Добавление нового слова (ID: {next_id})")
    print("=" * 50)
    
    word = {
        "id": next_id,
        "word": input("Слово на английском: ").strip(),
        "translation": input("Перевод на русский: ").strip(),
        "association": input("Ассоциация (мнемоника): ").strip(),
        "example": input("Пример предложения: ").strip(),
        "ipa": input("IPA транскрипция (опционально): ").strip() or None
    }
    
    # Проверяем все поля
    if not word['word'] or not word['translation']:
        print("❌ Слово и перевод обязательны!")
        return False
    
    # Проверяем дубликаты
    if any(w['word'].lower() == word['word'].lower() for w in words):
        print("⚠️ Это слово уже существует в базе!")
        return False
    
    words.append(word)
    
    if save_words(words):
        print(f"✅ Слово '{word['word']}' успешно добавлено!")
        print(f"📊 Всего слов в базе: {len(words)}")
        return True
    
    return False


def add_multiple_words():
    """Добавление нескольких слов из CSV или JSON"""
    print("\n📚 Выберите источник:")
    print("1. JSON файл")
    print("2. CSV файл")
    
    choice = input("Выбор (1 или 2): ").strip()
    
    if choice == "1":
        filename = input("Путь к JSON файлу: ").strip()
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                new_words = json.load(f)
        except Exception as e:
            print(f"❌ Ошибка при чтении JSON: {e}")
            return False
    
    elif choice == "2":
        filename = input("Путь к CSV файлу (формат: word,translation,association,example,ipa): ").strip()
        try:
            import csv
            new_words = []
            with open(filename, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    new_words.append({
                        'word': row.get('word', '').strip(),
                        'translation': row.get('translation', '').strip(),
                        'association': row.get('association', '').strip(),
                        'example': row.get('example', '').strip(),
                        'ipa': row.get('ipa', '').strip() or None
                    })
        except Exception as e:
            print(f"❌ Ошибка при чтении CSV: {e}")
            return False
    else:
        print("❌ Неверный выбор!")
        return False
    
    words = load_words()
    next_id = get_next_id(words)
    
    added_count = 0
    skipped_count = 0
    
    for new_word in new_words:
        if not new_word.get('word') or not new_word.get('translation'):
            skipped_count += 1
            continue
        
        # Проверяем дубликаты
        if any(w['word'].lower() == new_word['word'].lower() for w in words):
            print(f"⚠️ Слово '{new_word['word']}' уже существует, пропускаем")
            skipped_count += 1
            continue
        
        new_word['id'] = next_id
        words.append(new_word)
        next_id += 1
        added_count += 1
    
    if save_words(words):
        print(f"\n✅ Добавлено слов: {added_count}")
        print(f"⚠️ Пропущено (дубликаты/ошибки): {skipped_count}")
        print(f"📊 Всего слов в базе: {len(words)}")
        return True
    
    return False


def show_stats():
    """Показывает статистику по словам"""
    words = load_words()
    
    if not words:
        print("⚠️ База слов пуста")
        return
    
    print("\n📊 СТАТИСТИКА")
    print("=" * 50)
    print(f"Всего слов: {len(words)}")
    print(f"Первый ID: {min(w.get('id', 0) for w in words)}")
    print(f"Последний ID: {max(w.get('id', 0) for w in words)}")
    
    # Слова без IPA
    no_ipa = sum(1 for w in words if not w.get('ipa'))
    print(f"Без IPA транскрипции: {no_ipa}")
    
    # Слова без ассоциации
    no_assoc = sum(1 for w in words if not w.get('association'))
    print(f"Без ассоциации: {no_assoc}")


def list_words(limit=10):
    """Выводит последние добавленные слова"""
    words = load_words()
    
    if not words:
        print("⚠️ База слов пуста")
        return
    
    print(f"\n📚 Последние {min(limit, len(words))} слов:")
    print("=" * 50)
    
    for word in words[-limit:]:
        print(f"\n[{word.get('id')}] {word.get('word')}")
        print(f"  📖 {word.get('translation')}")
        print(f"  💡 {word.get('association')}")
        if word.get('ipa'):
            print(f"  🔊 {word.get('ipa')}")


def main():
    """Главное меню"""
    while True:
        print("\n" + "=" * 50)
        print("🎓 МЕНЕДЖЕР СЛОВ - Mneme Bot")
        print("=" * 50)
        print("1️⃣  Добавить одно слово вручную")
        print("2️⃣  Добавить несколько слов из файла")
        print("3️⃣  Показать статистику")
        print("4️⃣  Показать последние слова")
        print("0️⃣  Выход")
        print("=" * 50)
        
        choice = input("Выберите опцию: ").strip()
        
        if choice == "1":
            add_single_word()
            input("\nНажмите Enter для продолжения...")
        
        elif choice == "2":
            add_multiple_words()
            input("\nНажмите Enter для продолжения...")
        
        elif choice == "3":
            show_stats()
            input("\nНажмите Enter для продолжения...")
        
        elif choice == "4":
            limit = input("Сколько последних слов показать? (по умолчанию 10): ").strip()
            list_words(int(limit) if limit.isdigit() else 10)
            input("\nНажмите Enter для продолжения...")
        
        elif choice == "0":
            print("\n👋 До свидания!")
            break
        
        else:
            print("❌ Неверный выбор!")


if __name__ == "__main__":
    main()
