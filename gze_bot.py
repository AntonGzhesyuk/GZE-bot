#!/usr/bin/env python3
"""
GZE Group AI Assistant Bot - ИСПРАВЛЕННАЯ ВЕРСИЯ
Простой и надежный Telegram бот
"""

import os
import json
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from anthropic import Anthropic

# Загружаем переменные окружения
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

print(f"[INFO] Токен загружен: {bool(TELEGRAM_TOKEN)}")
print(f"[INFO] API ключ загружен: {bool(ANTHROPIC_API_KEY)}")

if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY:
    print("[ERROR] Не найдены переменные окружения!")
    exit(1)

# ===================== БАЗА ДАННЫХ =====================

def init_db():
    """Инициализация SQLite базы данных"""
    try:
        conn = sqlite3.connect("gze_finance.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                type TEXT NOT NULL,
                category TEXT,
                amount REAL NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_name TEXT NOT NULL,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                user_id INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
        print("[INFO] База данных инициализирована")
    except Exception as e:
        print(f"[ERROR] Ошибка БД: {e}")

def add_transaction(project_name: str, trans_type: str, amount: float, description: str, user_id: int):
    """Добавить финансовую операцию"""
    try:
        conn = sqlite3.connect("gze_finance.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (project_name, type, amount, description, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (project_name, trans_type, amount, description, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] Ошибка при добавлении транзакции: {e}")

def add_task(partner_name: str, task_description: str, user_id: int):
    """Добавить задачу партнёру"""
    try:
        conn = sqlite3.connect("gze_finance.db")
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tasks (partner_name, task_description, user_id)
            VALUES (?, ?, ?)
        ''', (partner_name, task_description, user_id))
        conn.commit()
        task_id = cursor.lastrowid
        conn.close()
        return task_id
    except Exception as e:
        print(f"[ERROR] Ошибка при добавлении задачи: {e}")
        return None

def get_tasks(user_id: int):
    """Получить список задач"""
    try:
        conn = sqlite3.connect("gze_finance.db")
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, partner_name, task_description, status, created_at
            FROM tasks
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        ''', (user_id,))
        tasks = cursor.fetchall()
        conn.close()
        return tasks
    except Exception as e:
        print(f"[ERROR] Ошибка при получении задач: {e}")
        return []

def get_financial_report(user_id: int):
    """Получить финансовый отчёт"""
    try:
        conn = sqlite3.connect("gze_finance.db")
        cursor = conn.cursor()
        cursor.execute('''
            SELECT project_name, type, amount
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 100
        ''', (user_id,))
        transactions = cursor.fetchall()
        conn.close()
        
        report = "📊 *ФИНАНСОВЫЙ ОТЧЁТ*\n\n"
        
        projects_data = {}
        for proj_name, trans_type, amount in transactions:
            if proj_name not in projects_data:
                projects_data[proj_name] = {'income': 0, 'expense': 0}
            
            if trans_type == 'income':
                projects_data[proj_name]['income'] += amount
            else:
                projects_data[proj_name]['expense'] += amount
        
        if not projects_data:
            return "📊 Нет операций в финансовом учёте"
        
        for proj, data in projects_data.items():
            profit = data['income'] - data['expense']
            report += f"📦 *{proj}*\n"
            report += f"  ✅ Доход: ₽{data['income']:,.0f}\n"
            report += f"  ❌ Расход: ₽{data['expense']:,.0f}\n"
            report += f"  💰 Прибыль: ₽{profit:,.0f}\n\n"
        
        return report
    except Exception as e:
        print(f"[ERROR] Ошибка при создании отчёта: {e}")
        return "❌ Ошибка при создании отчёта"

# ===================== CLAUDE AI =====================

def get_claude_response(user_message: str, user_id: int) -> str:
    """Получить ответ от Claude"""
    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        
        system_prompt = """Ты - личный AI ассистент для владельца компании GZE Group.
Компания занимается поставкой строительных материалов.

Твои обязанности:
1. Помогать с управлением задачами для партнёров
2. Вести финансовый учёт (доходы, расходы, прибыль)
3. Анализировать цены и рассчитывать наценки
4. Помогать с документами и организацией

Общайся кратко, по делу. Используй эмодзи.
Отвечай на русском языке."""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )
        
        return response.content[0].text
    except Exception as e:
        print(f"[ERROR] Ошибка Claude: {e}")
        return "❌ Ошибка при обработке сообщения. Попробуй позже."

# ===================== TELEGRAM HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    welcome_text = """🚀 *Добро пожаловать в GZE Group AI Assistant!*

Я помогу тебе с:
✅ Управлением задачами
💰 Финансовым учётом
📊 Анализом цен
📁 Работой с документами

Команды:
/tasks - показать задачи
/finance - финансовый отчёт
/help - справка

Просто пиши мне, и я помогу! 💬
"""
    try:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Ошибка при отправке /start: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений"""
    try:
        user_id = update.effective_user.id
        user_message = update.message.text
        
        # Показываем "печатает"
        await update.message.chat.send_action("typing")
        
        # Анализируем сообщение
        lower_msg = user_message.lower()
        
        response = None
        
        # Команда: добавить доход
        if 'доход' in lower_msg:
            try:
                # Пытаемся извлечь сумму
                import re
                numbers = re.findall(r'\d+', user_message)
                if numbers:
                    amount = float(numbers[0])
                    project = "Стройматериалы"
                    add_transaction(project, "income", amount, user_message, user_id)
                    response = f"✅ Доход ₽{amount:,.0f} добавлен по проекту '{project}'"
                else:
                    response = "❌ Укажи сумму дохода (например: 'Доход 100000')"
            except Exception as e:
                print(f"[ERROR] Ошибка при добавлении дохода: {e}")
                response = "❌ Ошибка при добавлении дохода"
        
        # Команда: добавить расход
        elif 'расход' in lower_msg or 'потратил' in lower_msg:
            try:
                import re
                numbers = re.findall(r'\d+', user_message)
                if numbers:
                    amount = float(numbers[0])
                    project = "Стройматериалы"
                    add_transaction(project, "expense", amount, user_message, user_id)
                    response = f"✅ Расход ₽{amount:,.0f} добавлен по проекту '{project}'"
                else:
                    response = "❌ Укажи сумму расхода (например: 'Расход 50000')"
            except Exception as e:
                print(f"[ERROR] Ошибка при добавлении расхода: {e}")
                response = "❌ Ошибка при добавлении расхода"
        
        # Команда: создать задачу
        elif 'задача' in lower_msg or 'отправь' in lower_msg:
            try:
                # Извлекаем партнёра и описание
                if 'задача' in lower_msg:
                    parts = user_message.split('задача')
                    if len(parts) > 1:
                        task_text = parts[1].strip()
                        partner = "Партнёр"
                        task_id = add_task(partner, task_text, user_id)
                        if task_id:
                            response = f"✅ Задача #{task_id} создана для партнёра"
                        else:
                            response = "❌ Ошибка при создании задачи"
                    else:
                        response = "❌ Укажи описание задачи (например: 'Задача: проверить цены')"
                else:
                    response = "❌ Используй команду 'задача: описание'"
            except Exception as e:
                print(f"[ERROR] Ошибка при создании задачи: {e}")
                response = "❌ Ошибка при создании задачи"
        
        # Если ответ не был установлен - используем Claude
        if response is None:
            response = get_claude_response(user_message, user_id)
        
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Ошибка при обработке сообщения: {e}")
        try:
            await update.message.reply_text("❌ Произошла ошибка. Попробуй ещё раз.")
        except:
            pass

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tasks"""
    try:
        user_id = update.effective_user.id
        tasks = get_tasks(user_id)
        
        response = "📋 *ЗАДАЧИ*\n\n"
        
        if tasks:
            for task_id, partner, desc, status, created_at in tasks:
                emoji = "⏳" if status == "pending" else "✅"
                response += f"{emoji} #{task_id} @{partner}: {desc}\n"
        else:
            response += "Нет задач"
        
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Ошибка в /tasks: {e}")
        await update.message.reply_text("❌ Ошибка при получении задач")

async def finance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /finance"""
    try:
        user_id = update.effective_user.id
        report = get_financial_report(user_id)
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Ошибка в /finance: {e}")
        await update.message.reply_text("❌ Ошибка при создании отчёта")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    try:
        help_text = """📚 *СПРАВКА*

*Команды:*
/start - начало
/tasks - список задач
/finance - финансовый отчёт
/help - эта справка

*Примеры:*

💰 Добавить доход:
"Получил доход 50000"

❌ Добавить расход:
"Потратил 30000"

📋 Создать задачу:
"Задача: проверить цены на кирпич"

*Просто пиши мне что нужно!* 🤖
"""
        await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        print(f"[ERROR] Ошибка в /help: {e}")

# ===================== MAIN =====================

def main():
    """Главная функция"""
    print("[INFO] Инициализация бота...")
    
    # Инициализируем БД
    init_db()
    
    try:
        # Создаём приложение
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("tasks", tasks_command))
        app.add_handler(CommandHandler("finance", finance_command))
        app.add_handler(CommandHandler("help", help_command))
        
        # Добавляем обработчик для обычных сообщений
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("[INFO] 🚀 Бот запущен! Ожидание сообщений...")
        app.run_polling(allowed_updates=[])
    except Exception as e:
        print(f"[FATAL ERROR] Ошибка при запуске бота: {e}")
        exit(1)

if __name__ == "__main__":
    main()
