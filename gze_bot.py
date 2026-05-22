#!/usr/bin/env python3
"""
GZE Group AI Assistant Bot
Telegram бот для управления задачами, документами и финансами
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from anthropic import Anthropic

# Загружаем переменные окружения
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Инициализируем Anthropic клиент
client = Anthropic()

# ===================== БАЗА ДАННЫХ =====================

def init_db():
    """Инициализация SQLite базы данных"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    # Таблица финансовых операций
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
    
    # Таблица задач
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
    
    # Таблица проектов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def get_project_balance(project_name: str) -> dict:
    """Получить баланс по проекту"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
            SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
        FROM transactions
        WHERE project_name = ?
    ''', (project_name,))
    
    income, expense = cursor.fetchone()
    conn.close()
    
    income = income or 0
    expense = expense or 0
    
    return {
        'income': income,
        'expense': expense,
        'profit': income - expense
    }

def add_transaction(project_name: str, trans_type: str, category: str, 
                   amount: float, description: str, user_id: int):
    """Добавить финансовую операцию"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO transactions 
        (project_name, type, category, amount, description, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (project_name, trans_type, category, amount, description, user_id))
    
    conn.commit()
    conn.close()

def add_task(partner_name: str, task_description: str, user_id: int) -> int:
    """Добавить задачу партнёру"""
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

def get_tasks(status: str = None, user_id: int = None) -> list:
    """Получить список задач"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    if status:
        cursor.execute('''
            SELECT id, partner_name, task_description, status, created_at
            FROM tasks
            WHERE status = ? AND user_id = ?
            ORDER BY created_at DESC
        ''', (status, user_id))
    else:
        cursor.execute('''
            SELECT id, partner_name, task_description, status, created_at
            FROM tasks
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (user_id,))
    
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def complete_task(task_id: int):
    """Отметить задачу как выполненную"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE tasks
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (task_id,))
    
    conn.commit()
    conn.close()

def get_financial_report(user_id: int) -> str:
    """Получить финансовый отчёт"""
    conn = sqlite3.connect("gze_finance.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT project_name, type, category, amount, description, created_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    ''', (user_id,))
    
    transactions = cursor.fetchall()
    conn.close()
    
    report = "📊 ФИНАНСОВЫЙ ОТЧЁТ (последние операции):\n\n"
    
    projects_data = {}
    for proj_name, trans_type, category, amount, desc, created_at in transactions:
        if proj_name not in projects_data:
            projects_data[proj_name] = {'income': 0, 'expense': 0}
        
        if trans_type == 'income':
            projects_data[proj_name]['income'] += amount
        else:
            projects_data[proj_name]['expense'] += amount
    
    for proj, data in projects_data.items():
        profit = data['income'] - data['expense']
        report += f"📦 *{proj}*\n"
        report += f"  ✅ Доход: ₽{data['income']:,.0f}\n"
        report += f"  ❌ Расход: ₽{data['expense']:,.0f}\n"
        report += f"  💰 Прибыль: ₽{profit:,.0f}\n\n"
    
    return report

# ===================== CLAUDE AI =====================

def get_claude_response(user_message: str, conversation_history: list) -> str:
    """Получить ответ от Claude"""
    
    system_prompt = """Ты - личный AI ассистент для владельца компании GZE Group.
Компания занимается поставкой строительных материалов.

Твои обязанности:
1. Помогать с управлением задачами для партнёров
2. Вести финансовый учёт (доходы, расходы, прибыль)
3. Анализировать цены и рассчитывать наценки
4. Помогать с документами и организацией
5. Давать советы по оптимизации бизнеса

Общайся кратко, по делу. Используй эмодзи.
При обработке команд предлагай конкретные действия."""
    
    conversation_history.append({
        "role": "user",
        "content": user_message
    })
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1000,
        system=system_prompt,
        messages=conversation_history
    )
    
    assistant_message = response.content[0].text
    conversation_history.append({
        "role": "assistant",
        "content": assistant_message
    })
    
    # Сохраняем только последние 10 сообщений в памяти
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]
    
    return assistant_message

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
    await update.message.reply_text(welcome_text, parse_mode="Markdown")
    
    # Инициализируем беседу для пользователя
    if 'conversation' not in context.user_data:
        context.user_data['conversation'] = []

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Инициализируем беседу если нужно
    if 'conversation' not in context.user_data:
        context.user_data['conversation'] = []
    
    # Показываем "печатает"
    await update.message.chat.send_action("typing")
    
    # Анализируем сообщение на предмет команд
    lower_msg = user_message.lower()
    
    # Команда: добавить доход
    if 'доход' in lower_msg or 'получил' in lower_msg:
        response = "Понял, что добавить доход. Укажи:\n💰 Сумму\n📦 Проект\n📝 Описание"
        context.user_data['action'] = 'add_income'
        
    # Команда: добавить расход
    elif 'расход' in lower_msg or 'потратил' in lower_msg:
        response = "Понял. Для расхода скажи:\n💰 Сумму\n📦 Проект\n📝 Описание"
        context.user_data['action'] = 'add_expense'
        
    # Команда: создать задачу
    elif 'задача' in lower_msg or 'отправь' in lower_msg or 'партнер' in lower_msg:
        response = "Для задачи укажи:\n👤 Имя партнёра\n📝 Что сделать"
        context.user_data['action'] = 'add_task'
        
    # Команда: проверить цены
    elif 'цена' in lower_msg or 'наценка' in lower_msg or 'маржа' in lower_msg:
        response = "Помогу рассчитать наценку! 📊\n\nУкажи:\n💰 Оптовая цена\n📦 Товар\n🏙️ Город"
        context.user_data['action'] = 'calc_price'
        
    else:
        # Используем Claude для ответа
        response = get_claude_response(user_message, context.user_data['conversation'])
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /tasks - показать задачи"""
    user_id = update.effective_user.id
    
    pending = get_tasks(status='pending', user_id=user_id)
    completed = get_tasks(status='completed', user_id=user_id)
    
    response = "📋 *ЗАДАЧИ*\n\n"
    
    if pending:
        response += "⏳ *В процессе:*\n"
        for task_id, partner, desc, status, created_at in pending:
            response += f"  #{task_id} @{partner}: {desc}\n"
    else:
        response += "✅ Нет активных задач!\n"
    
    if completed:
        response += "\n✅ *Выполнено:*\n"
        for task_id, partner, desc, status, created_at in completed[:5]:
            response += f"  #{task_id} @{partner}: {desc}\n"
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def finance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /finance - финансовый отчёт"""
    user_id = update.effective_user.id
    report = get_financial_report(user_id)
    await update.message.reply_text(report, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка"""
    help_text = """📚 *СПРАВКА*

*Основные команды:*
/start - начало
/tasks - список задач
/finance - финансовый отчёт
/help - эта справка

*Примеры команд в чате:*

💰 Добавить доход:
"Получил доход 50000 по проекту Офисный комплекс от клиента Рога"

❌ Добавить расход:
"Потратил 30000 на закупку цемента для проекта Школа"

📋 Создать задачу:
"Отправь задачу Сергею: проверить цены на кирпич в Москве"

📊 Рассчитать наценку:
"Какую наценку сделать на цемент? Оптовая цена 150, продаю в Казани"

*Просто пиши мне что нужно сделать - я всё понимаю!* 🤖
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ===================== MAIN =====================

def main():
    """Главная функция"""
    
    # Инициализируем БД
    init_db()
    
    # Создаём приложение
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("finance", finance_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Добавляем обработчик для обычных сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 Бот запущен! Ожидание сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
