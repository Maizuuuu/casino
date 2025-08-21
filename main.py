import logging
import random
import math
import time
from datetime import datetime, timedelta
import sqlite3
from typing import Dict, Tuple, List
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackContext
)


# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация бота
TOKEN = "7334381322:AAFnQuyzmVEyxhWMt8CMz1Y8wh4dxDVkibs"
ADMIN_IDS = [123456789]  # Ваш Telegram ID
DATABASE_NAME = "casino_bot.db"
INITIAL_BALANCE = 1000

# Инициализация базы данных
def init_db():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        
        # Включаем поддержку внешних ключей
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Создаем таблицы
        tables = [
            '''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance INTEGER DEFAULT 1000,
                registration_date TEXT,
                is_admin INTEGER DEFAULT 0)''',
                
            '''CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                transaction_type TEXT,
                game_type TEXT,
                result TEXT,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id))''',
                
            '''CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                multiplier REAL,
                fixed_win INTEGER,
                discount INTEGER,
                attempts INTEGER,
                expires_at TEXT,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(user_id))''',
                
            '''CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                bonus_amount INTEGER NOT NULL,
                expires_at TEXT,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES users(user_id))''',
                
            '''CREATE TABLE IF NOT EXISTS used_promocodes (
                user_id INTEGER,
                code TEXT,
                PRIMARY KEY (user_id, code),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (code) REFERENCES promocodes(code))'''
        ]
        
        for table in tables:
            cursor.execute(table)
        
        # Добавляем администраторов
        for admin_id in ADMIN_IDS:
            cursor.execute('INSERT OR IGNORE INTO users (user_id, is_admin, registration_date) VALUES (?, ?, ?)',
                          (admin_id, 1, datetime.now().isoformat()))
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()    

init_db()

def add_event(name: str, description: str, event_type: str, value: float, 
             attempts: int, days_active: int, admin_id: int) -> tuple:
    """Добавляет событие с валидацией. Возвращает (success, message)"""
    
    # Валидация данных
    if not name or not description:
        return False, "Название и описание не могут быть пустыми"
    
    if event_type == "multiplier" and value <= 0:
        return False, "Множитель должен быть положительным"
    elif event_type == "fixed_win" and value <= 0:
        return False, "Фиксированный выигрыш должен быть положительным"
    elif event_type == "discount" and (value <= 0 or value > 100):
        return False, "Скидка должна быть от 1% до 100%"
    
    if attempts < -1 or attempts == 0:
        return False, "Попытки должны быть -1 (бесконечно) или положительным числом"
    
    if days_active <= 0:
        return False, "Дней активности должно быть положительным числом"
    
    expires_at = (datetime.now() + timedelta(days=days_active)).isoformat()
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        if event_type == "multiplier":
            cursor.execute('''
                INSERT INTO events (name, description, multiplier, attempts, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, description, value, attempts, expires_at, admin_id))
        elif event_type == "fixed_win":
            cursor.execute('''
                INSERT INTO events (name, description, fixed_win, attempts, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, description, int(value), attempts, expires_at, admin_id))
        elif event_type == "discount":
            cursor.execute('''
                INSERT INTO events (name, description, discount, attempts, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, description, int(value), attempts, expires_at, admin_id))
        
        conn.commit()
        return True, "Событие успешно создано!"
    except sqlite3.IntegrityError:
        return False, "Событие с таким названием уже существует"
    except Exception as e:
        logger.error(f"Error adding event: {e}")
        return False, f"Ошибка при создании события: {str(e)}"
    finally:
        conn.close()

async def admin_add_event_multiplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания события-множителя"""
    context.user_data['event_creation'] = {
        'type': 'multiplier',
        'step': 'name'
    }
    
    await send_or_edit(update,
                      "📈 СОЗДАНИЕ МНОЖИТЕЛЯ\n\n"
                      "Введите название события:",
                      [[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО

async def admin_add_event_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания события с фиксированным выигрышем"""
    context.user_data['event_creation'] = {
        'type': 'fixed_win',
        'step': 'name'
    }
    
    await send_or_edit(update,
                      "💰 СОЗДАНИЕ ФИКСИРОВАННОГО ВЫИГРЫША\n\n"
                      "Введите название события:",
                      [[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО

async def admin_add_event_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания события со скидкой"""
    context.user_data['event_creation'] = {
        'type': 'discount', 
        'step': 'name'
    }
    
    await send_or_edit(update,
                      "🎫 СОЗДАНИЕ СКИДКИ\n\n"
                      "Введите название события:",
                      [[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
    
def get_active_events_count() -> int:
    """Возвращает количество активных событий"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM events WHERE expires_at > datetime("now")')
    count = cursor.fetchone()[0]
    conn.close()
    return count

async def handle_event_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка step-by-step создания события с правильными callback'ами"""
    if 'event_creation' not in context.user_data:
        await update.message.reply_text("❌ Сначала выберите тип события через меню")
        return
        
    creation_data = context.user_data['event_creation']
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    try:
        if creation_data['step'] == 'name':
            if len(text) < 3:
                await update.message.reply_text("❌ Название должно быть не менее 3 символов")
                return
                
            creation_data['name'] = text
            creation_data['step'] = 'description'
            
            await update.message.reply_text(
                "📝 Введите описание события:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
            )
            
        elif creation_data['step'] == 'description':
            if len(text) < 10:
                await update.message.reply_text("❌ Описание должно быть не менее 10 символов")
                return
                
            creation_data['description'] = text
            creation_data['step'] = 'value'
            
            if creation_data['type'] == 'multiplier':
                await update.message.reply_text(
                    "🔢 Введите значение множителя (например: 2.5):",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
                )
            elif creation_data['type'] == 'fixed_win':
                await update.message.reply_text(
                    "💰 Введите размер фиксированного выигрыша:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
                )
            elif creation_data['type'] == 'discount':
                await update.message.reply_text(
                    "🎫 Введите размер скидки в процентах (1-100):",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
                )
                
        elif creation_data['step'] == 'value':
            value = float(text)
            
            if creation_data['type'] == 'multiplier' and value <= 0:
                await update.message.reply_text("❌ Множитель должен быть положительным")
                return
            elif creation_data['type'] == 'fixed_win' and value <= 0:
                await update.message.reply_text("❌ Выигрыш должен быть положительным")
                return
            elif creation_data['type'] == 'discount' and (value <= 0 or value > 100):
                await update.message.reply_text("❌ Скидка должна быть от 1% до 100%")
                return
                
            creation_data['value'] = value
            creation_data['step'] = 'attempts'
            
            await update.message.reply_text(
                "🔄 Введите количество попыток (-1 для бесконечных):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
            )
            
        elif creation_data['step'] == 'attempts':
            attempts = int(text)
            if attempts < -1 or attempts == 0:
                await update.message.reply_text("❌ Попытки должны быть -1 (бесконечно) или положительным числом")
                return
                
            creation_data['attempts'] = attempts
            creation_data['step'] = 'days'
            
            await update.message.reply_text(
                "📅 Введите количество дней активности события:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_cancel_event')]])  # ИЗМЕНЕНО
            )
            
        elif creation_data['step'] == 'days':
            days = int(text)
            if days <= 0:
                await update.message.reply_text("❌ Дней активности должно быть положительным числом")
                return
                
            creation_data['days'] = days
            
            # Финальный шаг - создаем событие
            success, message = add_event(
                name=creation_data['name'],
                description=creation_data['description'],
                event_type=creation_data['type'],
                value=creation_data['value'],
                attempts=creation_data['attempts'],
                days_active=creation_data['days'],
                admin_id=user_id
            )
            
            if success:
                # Формируем красивый summary
                event_type_name = {
                    'multiplier': 'Множитель',
                    'fixed_win': 'Фиксированный выигрыш', 
                    'discount': 'Скидка'
                }[creation_data['type']]
                
                summary = (
                    f"✅ {message}\n\n"
                    f"📋 Сводка события:\n"
                    f"🏷 Тип: {event_type_name}\n"
                    f"📛 Название: {creation_data['name']}\n"
                    f"📝 Описание: {creation_data['description']}\n"
                )
                
                if creation_data['type'] == 'multiplier':
                    summary += f"📈 Множитель: x{creation_data['value']}\n"
                elif creation_data['type'] == 'fixed_win':
                    summary += f"💰 Выигрыш: {int(creation_data['value'])} монет\n"
                elif creation_data['type'] == 'discount':
                    summary += f"🎫 Скидка: {int(creation_data['value'])}%\n"
                    
                summary += (
                    f"🔄 Попыток: {'∞' if creation_data['attempts'] == -1 else creation_data['attempts']}\n"
                    f"📅 Дней активности: {creation_data['days']}\n"
                    f"⏰ Истекает: {(datetime.now() + timedelta(days=creation_data['days'])).strftime('%d.%m.%Y')}"
                )
                
                await update.message.reply_text(
                    summary,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Создать еще", callback_data='admin_add_event')],
                        [InlineKeyboardButton("📋 К событиям", callback_data='admin_view_events')],
                        [InlineKeyboardButton("🔙 В админку", callback_data='admin_panel')]
                    ])
                )
            else:
                await update.message.reply_text(
                    f"❌ {message}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Попробовать снова", callback_data='admin_add_event')]])
                )
            
            # Очищаем данные создания
            context.user_data.pop('event_creation', None)
            
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное число!")



def delete_event(event_id: int) -> bool:
    """Удаляет событие по ID"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM events WHERE event_id = ?', (event_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        return False
    finally:
        conn.close()

async def cancel_event_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена создания события"""
    if 'event_creation' in context.user_data:
        context.user_data.pop('event_creation', None)
        await update.callback_query.answer("❌ Создание события отменено")
    
    # Возвращаемся в меню добавления событий
    keyboard = [
        [InlineKeyboardButton("📈 Множитель выигрыша", callback_data='admin_add_event_multiplier')],
        [InlineKeyboardButton("💰 Фиксированный бонус", callback_data='admin_add_event_fixed')],
        [InlineKeyboardButton("🎫 Скидка на ставки", callback_data='admin_add_event_discount')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_events')]
    ]
    
    text = (
        "🎁 ВЫБЕРИТЕ ТИП СОБЫТИЯ\n\n"
        "📈 <b>Множитель выигрыша</b> - увеличивает выигрыш в X раз\n"
        "💰 <b>Фиксированный бонус</b> - добавляет N монет к выигрышу\n"  
        "🎫 <b>Скидка на ставки</b> - уменьшает стоимость ставок на N%\n\n"
        "Выберите тип:"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
def get_event_by_id(event_id: int) -> Dict:
    """Получает полную информацию о событии по ID"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT event_id, name, description, multiplier, fixed_win, discount, 
               attempts, expires_at, created_by 
        FROM events WHERE event_id = ?
    ''', (event_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'multiplier': row[3],
            'fixed_win': row[4],
            'discount': row[5],
            'attempts': row[6],
            'expires_at': row[7],
            'created_by': row[8]
        }
    return None

def apply_event_bonuses(user_id: int, game_type: str, bet_amount: int) -> tuple:
    """Применяет активные бонусы событий к игре"""
    events = get_active_events_for_game(game_type)
    bonuses = {
        'multiplier': 1.0,
        'fixed_bonus': 0,
        'discount': 0
    }
    
    applied_events = []
    
    for event in events:
        event_id = event[0]
        
        # Уменьшаем количество попыток
        if event[6] > 0:  # Если не бесконечные попытки
            decrease_event_attempts(event_id)
        
        if event[3]:  # Multiplier
            bonuses['multiplier'] *= event[3]
            applied_events.append(f"x{event[3]}")
        elif event[4]:  # Fixed win
            bonuses['fixed_bonus'] += event[4]
            applied_events.append(f"+{event[4]} монет")
        elif event[5]:  # Discount
            discount_percent = event[5]
            actual_discount = bet_amount * discount_percent / 100
            bonuses['discount'] += actual_discount
            applied_events.append(f"-{discount_percent}%")
    
    # Применяем скидку к ставке
    final_bet = max(0, bet_amount - bonuses['discount'])
    
    return final_bet, bonuses, applied_events

# Функции работы с базой данных
def get_user(user_id: int) -> Dict:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {
            'user_id': user[0],
            'username': user[1],
            'first_name': user[2],
            'last_name': user[3],
            'balance': user[4],
            'registration_date': user[5],
            'is_admin': bool(user[6])
        }
    return None

def get_admin_name(admin_id: int) -> str:
    """Получаем имя администратора по ID"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT first_name, last_name FROM users WHERE user_id = ?', (admin_id,))
    admin = cursor.fetchone()
    conn.close()
    
    if admin:
        return f"{admin[0]} {admin[1] or ''}".strip()
    return "Неизвестный"

def get_active_events_for_game(game_type: str) -> list:
    """Получаем активные события для конкретного типа игры"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    # Для слотов применяем скидки, для других игр - множители/фиксированные бонусы
    if game_type == "slots":
        cursor.execute('''
            SELECT * FROM events 
            WHERE expires_at > datetime('now') 
            AND (discount > 0 OR multiplier > 1)
            ORDER BY expires_at ASC
        ''')
    else:
        cursor.execute('''
            SELECT * FROM events 
            WHERE expires_at > datetime('now') 
            AND (multiplier > 1 OR fixed_win > 0)
            ORDER BY expires_at ASC
        ''')
    
    events = cursor.fetchall()
    conn.close()
    return events

def create_user(user_id: int, username: str, first_name: str, last_name: str) -> None:
    is_admin = 1 if user_id in ADMIN_IDS else 0
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO users (user_id, username, first_name, last_name, registration_date, is_admin) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, username, first_name, last_name, datetime.now().isoformat(), is_admin)
    )
    conn.commit()
    conn.close()

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str = None) -> None:
    if username:
        # Поиск по username
        if username.startswith('@'):
            username = username[1:]
        
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            await update.message.reply_text(f"❌ Пользователь @{username} не найден")
            return
            
        balance = result[0]
        await update.message.reply_text(f"💰 Баланс @{username}: {balance} монет")
    else:
        # Проверка своего баланса
        user_data = get_user(update.effective_user.id)
        await update.message.reply_text(f"💰 Ваш баланс: {user_data['balance']} монет")

def update_balance(user_id: int, amount: int) -> None:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def add_transaction(user_id: int, amount: int, transaction_type: str, game_type: str = None, result: str = None) -> None:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO transactions (user_id, amount, transaction_type, game_type, result, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, abs(amount), transaction_type, game_type, result, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_all_users() -> List[Dict]:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, first_name, last_name, balance FROM users')
    users = cursor.fetchall()
    conn.close()
    
    return [{
        'user_id': user[0],
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3],
        'balance': user[4]
    } for user in users]

def reset_statistics() -> None:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM transactions')
    cursor.execute('UPDATE users SET balance = ?', (INITIAL_BALANCE,))
    conn.commit()
    conn.close()

def modify_user_balance(user_id: int, amount: int) -> Dict:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return None
    
    current_balance = user[4]
    new_balance = max(0, current_balance + amount)
    
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
    
    transaction_type = "admin_add" if amount > 0 else "admin_remove"
    cursor.execute(
        'INSERT INTO transactions (user_id, amount, transaction_type, timestamp) VALUES (?, ?, ?, ?)',
        (user_id, abs(amount), transaction_type, datetime.now().isoformat())
    )
    
    conn.commit()
    conn.close()
    
    return {
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3],
        'old_balance': current_balance,
        'new_balance': new_balance
    }

# Игровая логика
def calculate_complex_coefficient(user_id: int, bet_amount: int, game_type: str) -> float:
    timestamp = int(time.time())
    user_data = get_user(user_id)
    balance = user_data['balance'] if user_data else INITIAL_BALANCE
    
    seed = (
        (user_id % 1000) + 
        (timestamp % 100000) + 
        (bet_amount % 50) + 
        (balance % 200) +
        random.randint(1, 1000)
    )
    random.seed(seed)
    
    if game_type == "dice":
        base = random.uniform(0.8, 1.2)
        mod1 = math.sin(timestamp / 1000) * 0.3
        mod2 = (bet_amount / (balance + 1)) * 0.5
        mod3 = (user_id % 10) * 0.05
        coefficient = base + mod1 - mod2 + mod3
        return max(1.0, min(6.0, coefficient * 3.5))
    
    elif game_type == "slots":
        base = random.uniform(0.5, 1.5)
        mod1 = math.cos(timestamp / 500) * 0.4
        mod2 = (bet_amount / (balance + 1)) * 0.8
        mod3 = ((user_id + timestamp) % 20) * 0.1
        coefficient = base + mod1 - mod2 + mod3
        return max(1.0, min(100.0, coefficient * 50))
    
    return 1.0

async def play_dice(user_id: int, bet_amount: int, guess: int) -> Tuple[bool, float, int, list, int]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0.0, 0, [], 0
    
    # ✅ ВЫЗЫВАЕМ ФУНКЦИЮ БОНУСОВ (РАНЬШЕ ЭТОГО НЕ БЫЛО!)
    final_bet, bonuses, applied_events = apply_event_bonuses(user_id, "dice", bet_amount)
    
    # Проверяем, хватает ли баланса после применения скидок
    if user['balance'] < final_bet:
        return False, 0.0, 0, [], 0
    
    coefficient = calculate_complex_coefficient(user_id, final_bet, "dice")
    roll = random.randint(1, 6)
    total_win_amount = 0
    
    if guess == roll:
        # ✅ ПРИМЕНЯЕМ БОНУСЫ ПРАВИЛЬНО
        base_win = int(final_bet * coefficient)          # Базовый выигрыш
        total_win = base_win + bonuses['fixed_bonus']    # + фиксированный бонус
        total_win_amount = int(total_win * bonuses['multiplier'])  # × множитель
        
        update_balance(user_id, total_win_amount)
        add_transaction(user_id, total_win_amount, "win", "dice", 
                       f"guess:{guess},roll:{roll},coef:{coefficient:.2f},events:{applied_events},final_bet:{final_bet}")
        return True, coefficient, roll, applied_events, total_win_amount
    
    # ✅ ПРИ ПРОИГРЫШЕ: списываем только final_bet (уже со скидкой)
    update_balance(user_id, -final_bet)
    add_transaction(user_id, -final_bet, "loss", "dice", 
                   f"guess:{guess},roll:{roll},coef:{coefficient:.2f},events:{applied_events},final_bet:{final_bet}")
    return False, coefficient, roll, applied_events, 0

async def play_slots(user_id: int, bet_amount: int) -> Tuple[bool, float, list, list, int]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0.0, [], [], 0
    
    # ✅ ВЫЗЫВАЕМ ФУНКЦИЮ БОНУСОВ
    final_bet, bonuses, applied_events = apply_event_bonuses(user_id, "slots", bet_amount)
    
    if user['balance'] < final_bet:
        return False, 0.0, [], [], 0
    
    coefficient = calculate_complex_coefficient(user_id, final_bet, "slots")
    symbols = ['🍒', '🍋', '🍊', '🍇', '🍉', '7']
    reels = [random.choice(symbols) for _ in range(3)]
    
    total_win_amount = 0
    win_coefficient = 0
    
    if reels[0] == reels[1] == reels[2]:
        win_coefficient = 10 if reels[0] == '7' else 3
        # ✅ ПРИМЕНЯЕМ БОНУСЫ ПРАВИЛЬНО
        base_win = int(final_bet * win_coefficient)       # Базовый выигрыш
        total_win = base_win + bonuses['fixed_bonus']     # + фиксированный бонус
        total_win_amount = int(total_win * bonuses['multiplier'])  # × множитель
        
        update_balance(user_id, total_win_amount)
        add_transaction(user_id, total_win_amount, "win", "slots", 
                       f"reels:{''.join(reels)},coef:{coefficient:.2f}x{win_coefficient},events:{applied_events},final_bet:{final_bet}")
        return True, coefficient * win_coefficient, reels, applied_events, total_win_amount
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        win_coefficient = 0.5
        # ✅ ПРИМЕНЯЕМ БОНУСЫ ПРАВИЛЬНО
        base_win = int(final_bet * win_coefficient)       # Базовый выигрыш
        total_win = base_win + bonuses['fixed_bonus']     # + фиксированный бонус
        total_win_amount = int(total_win * bonuses['multiplier'])  # × множитель
        
        update_balance(user_id, total_win_amount)
        add_transaction(user_id, total_win_amount, "win", "slots", 
                       f"reels:{''.join(reels)},coef:0.5,events:{applied_events},final_bet:{final_bet}")
        return True, 0.5, reels, applied_events, total_win_amount
    
    # ✅ ПРИ ПРОИГРЫШЕ: списываем только final_bet
    update_balance(user_id, -final_bet)
    add_transaction(user_id, -final_bet, "loss", "slots", 
                   f"reels:{''.join(reels)},coef:{coefficient:.2f},events:{applied_events},final_bet:{final_bet}")
    return False, coefficient, reels, applied_events, 0


# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not get_user(user.id):
        create_user(user.id, user.username, user.first_name, user.last_name)
        await update.message.reply_text(
            f"🎰 Добро пожаловать в Lucky Azart, {user.first_name}!\n"
            f"💰 Ваш стартовый баланс: {INITIAL_BALANCE} монет."
        )
    else:
        user_data = get_user(user.id)
        await update.message.reply_text(
            f"🎰 С возвращением, {user.first_name}!\n"
            f"💰 Ваш баланс: {user_data['balance']} монет."
        )
    await show_disclaimer(update, context, "start")
    await menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Сохраняем данные пользователя
    context.user_data['chat_id'] = update.effective_chat.id
    context.user_data['user_id'] = update.effective_user.id
    
    # Проверяем количество активных событий
    events_count = get_active_events_count()
    events_text = "🎉 События" + (f" ({events_count})" if events_count > 0 else "")
    
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data='games_menu')],
        [InlineKeyboardButton(events_text, callback_data='events_menu')],  # С подсчетом
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("👤 Пользователи", callback_data='users_menu')],
    ]

    # Добавляем кнопку админки если пользователь админ
    user_data = get_user(update.effective_user.id)

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем текст с информацией о событиях
    menu_text = '🎰 <b>Главное меню</b>'
    if events_count > 0:
        menu_text += f'\n\n🎁 <b>Доступно {events_count} активных событий!</b>'
    
    # Очищаем таймер, если он был
    if 'job' in context.user_data:
        context.user_data['job'].schedule_removal()
        del context.user_data['job']
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            menu_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            menu_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

# В menu.py
async def events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню активных событий для всех пользователей"""
    events = get_active_events()
    
    if not events:
        await send_or_edit(update, 
                         "🎉 На данный момент нет активных событий\n\n"
                         "Здесь будут появляться специальные акции и бонусы!",
                         [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]])
        return
    
    text = "🎁 <b>АКТИВНЫЕ СОБЫТИЯ</b>\n\n"
    text += "Выберите событие для просмотра деталей:\n\n"
    
    keyboard = []
    for event in events:
        # Создаем краткое описание для кнопки
        event_icon = "📈" if event['multiplier'] else "💰" if event['fixed_win'] else "🎫"
        event_value = f"x{event['multiplier']}" if event['multiplier'] else f"+{event['fixed_win']}" if event['fixed_win'] else f"-{event['discount']}%"
        
        days_left = (datetime.fromisoformat(event['expires_at']) - datetime.now()).days
        days_text = f" ({days_left}д.)" if days_left > 0 else " (сегодня!)"
        
        button_text = f"{event_icon} {event['name']} {event_value}{days_text}"
        
        # Обрезаем если слишком длинное
        if len(button_text) > 35:
            button_text = button_text[:32] + "..."
            
        keyboard.append([InlineKeyboardButton(
            button_text, 
            callback_data=f"view_event_{event['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_to_menu')])
    
    await send_or_edit(update, text, keyboard)

def get_event_by_id(event_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events WHERE event_id = ?', (event_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'multiplier': row[3],
            'fixed_win': row[4],
            'discount': row[5],
            'attempts': row[6],
            'expires_at': row[7],
            'created_by': row[8]
        }
    return None

async def send_or_edit(update, text, keyboard):
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

def setup_handlers(application):
    # Основные меню
    application.add_handler(CallbackQueryHandler(events_menu, pattern='^events_menu$'))
    application.add_handler(CallbackQueryHandler(view_event, pattern='^view_event_'))
    
    # Админ-панель
    application.add_handler(CallbackQueryHandler(admin_events_menu, pattern='^admin_events$'))
    application.add_handler(CallbackQueryHandler(admin_add_event, pattern='^admin_add_event$'))
    application.add_handler(CallbackQueryHandler(admin_promocodes_menu, pattern='^admin_promocodes$'))
    
    # Обработчики создания событий
    application.add_handler(CallbackQueryHandler(add_event_multiplier_handler, pattern='^add_event_multiplier$'))
    # Добавьте другие обработчики по аналогии
    
    # Обработчик текстовых команд для создания событий
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'.+\|.+\|.+\|.+\|.+'),
        process_event_creation
    ))

async def view_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный просмотр события для пользователей"""
    event_id = int(update.callback_query.data.split('_')[-1])
    event = get_event_by_id(event_id)
    
    if not event or datetime.fromisoformat(event['expires_at']) < datetime.now():
        await update.callback_query.answer("Событие не найдено или истекло")
        await events_menu(update, context)
        return
    
    # Форматируем информацию о событии
    event_type = ""
    event_value = ""
    
    if event['multiplier']:
        event_type = "📈 МНОЖИТЕЛЬ ВЫИГРЫША"
        event_value = f"Увеличивает ваш выигрыш в <b>x{event['multiplier']}</b> раз!"
    elif event['fixed_win']:
        event_type = "💰 ФИКСИРОВАННЫЙ БОНУС"
        event_value = f"Добавляет <b>{event['fixed_win']} монет</b> к каждому выигрышу!"
    elif event['discount']:
        event_type = "🎫 СКИДКА НА СТАВКИ"
        event_value = f"Уменьшает стоимость ставок на <b>{event['discount']}%</b>!"
    
    # Рассчитываем оставшееся время
    expires_at = datetime.fromisoformat(event['expires_at'])
    time_left = expires_at - datetime.now()
    days_left = time_left.days
    hours_left = time_left.seconds // 3600
    
    time_left_text = ""
    if days_left > 0:
        time_left_text = f"⏰ Осталось: <b>{days_left} дней</b>"
    elif hours_left > 0:
        time_left_text = f"⏰ Осталось: <b>{hours_left} часов</b>"
    else:
        time_left_text = "⏰ Заканчивается <b>сегодня</b>!"
    
    attempts_text = "🔄 Попыток: <b>∞</b>" if event['attempts'] == -1 else f"🔄 Осталось попыток: <b>{event['attempts']}</b>"
    
    text = (
        f"{event_type}\n\n"
        f"🎯 <b>{event['name']}</b>\n\n"
        f"{event['description']}\n\n"
        f"{event_value}\n\n"
        f"{time_left_text}\n"
        f"{attempts_text}\n\n"
        f"👤 Создано: {get_admin_name(event['created_by'])}"
    )
    
    keyboard = []
    
    # Добавляем кнопку "Использовать" если есть попытки
    if event['attempts'] != 0:
        # Определяем для каких игр применимо событие
        applicable_games = []
        if event['multiplier'] or event['fixed_win']:
            applicable_games.extend(['dice', 'slots', 'roulette'])
        if event['discount']:
            applicable_games.extend(['slots'])  # Скидки только для слотов по текущей логике
        
        if applicable_games:
            keyboard.append([InlineKeyboardButton("🎮 Использовать в играх", callback_data='games_menu')])
    
    keyboard.append([InlineKeyboardButton("📋 Все события", callback_data='events_menu')])
    keyboard.append([InlineKeyboardButton("🔙 Главное меню", callback_data='back_to_menu')])
    
    # Добавляем кнопки редактирования для админов
    user_data = get_user(update.effective_user.id)
    if user_data and user_data['is_admin']:
        keyboard.append([
            InlineKeyboardButton("✏️ Изменить", callback_data=f"admin_edit_event_{event_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_confirm_delete_{event_id}")
        ])
    
    await send_or_edit(update, text, keyboard)

async def admin_promocodes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promocodes = get_all_promocodes()
    
    keyboard = []
    for promo in promocodes:
        keyboard.append([InlineKeyboardButton(
            f"{promo['code']} (+{promo['amount']})", 
            callback_data=f"view_promo_{promo['code']}"
        )])
    
    keyboard.extend([
        [InlineKeyboardButton("➕ Добавить промокод", callback_data='add_promocode')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
    ])
    
    await send_or_edit(update, "🎫 Управление промокодами:", keyboard)

def get_active_events():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT event_id, name, description, multiplier, fixed_win, discount, 
               attempts, expires_at, created_by 
        FROM events 
        WHERE expires_at > datetime('now')
        ORDER BY expires_at ASC
    ''')
    
    events = []
    for row in cursor.fetchall():
        events.append({
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'multiplier': row[3],
            'fixed_win': row[4],
            'discount': row[5],
            'attempts': row[6],
            'expires_at': row[7],
            'created_by': row[8]
        })
    conn.close()
    return events

def format_event_info(event: tuple) -> str:
    info = f"<b>{event[1]}</b>\n{event[2]}\n\n"
    if event[3]:
        info += f"📈 Коэффициент: x{event[3]}\n"
    elif event[4]:
        info += f"💰 Фиксированный выигрыш: +{event[4]} монет\n"
    elif event[5]:
        info += f"🎫 Скидка: {event[5]}% на крутки\n"
    
    info += f"🔄 Попыток: {'∞' if event[6] == -1 else event[6]}\n"
    info += f"⏳ До: {event[7][:10]}\n"
    info += f"👤 Создал: {get_admin_name(event[8])}"
    return info

# В admin.py
async def admin_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню управления событиями"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить событие", callback_data='admin_add_event')],
        [InlineKeyboardButton("📋 Активные события", callback_data='admin_view_events')],
        [InlineKeyboardButton("🗑 Удалить событие", callback_data='admin_delete_event')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
    ]
    
    await send_or_edit(update, "🛠 Управление событиями:", keyboard)

async def admin_view_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр всех активных событий"""
    events = get_active_events()
    
    if not events:
        await send_or_edit(update, 
                         "📭 Нет активных событий",
                         [[InlineKeyboardButton("🔙 Назад", callback_data='admin_events')]])
        return
    
    keyboard = []
    for event in events:
        event_info = f"{event['name']} (ID: {event['id']})"
        keyboard.append([InlineKeyboardButton(event_info, callback_data=f"admin_event_info_{event['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_events')])
    
    await send_or_edit(update, "📋 Активные события:", keyboard)

async def admin_event_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о конкретном событии"""
    event_id = int(update.callback_query.data.split('_')[-1])
    event = get_event_by_id(event_id)
    
    if not event:
        await update.callback_query.answer("Событие не найдено")
        return
    
    text = (
        f"🎁 <b>{event['name']}</b>\n\n"
        f"{event['description']}\n\n"
        f"📅 Действует до: {event['expires_at'][:10]}\n"
        f"🔄 Осталось попыток: {'∞' if event['attempts'] == -1 else event['attempts']}\n"
    )
    
    if event['multiplier']:
        text += f"📈 Множитель: x{event['multiplier']}\n"
    elif event['fixed_win']:
        text += f"💰 Фиксированный выигрыш: {event['fixed_win']} монет\n"
    elif event['discount']:
        text += f"🎫 Скидка: {event['discount']}% на крутки\n"
    
    text += f"\n👤 Создал: {get_admin_name(event['created_by'])}"
    
    keyboard = [
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_confirm_delete_{event_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_view_events')]
    ]
    
    await send_or_edit(update, text, keyboard)

async def admin_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления события"""
    event_id = int(update.callback_query.data.split('_')[-1])
    event = get_event_by_id(event_id)
    
    if not event:
        await update.callback_query.answer("Событие не найдено")
        return
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"admin_delete_confirm_{event_id}")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data=f"admin_event_info_{event_id}")]
    ]
    
    await send_or_edit(update, 
                      f"❓ Вы уверены, что хотите удалить событие \"{event['name']}\"?",
                      keyboard)
    
async def admin_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное удаление события"""
    event_id = int(update.callback_query.data.split('_')[-1])
    
    if delete_event(event_id):
        await send_or_edit(update, 
                          "✅ Событие успешно удалено!",
                          [[InlineKeyboardButton("🔙 К списку событий", callback_data='admin_view_events')]])
    else:
        await send_or_edit(update, 
                          "❌ Ошибка при удалении события",
                          [[InlineKeyboardButton("🔙 Назад", callback_data='admin_view_events')]])



# promocodes.py
def add_promocode(code: str, amount: int, days: int, admin_id: int) -> bool:
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO promocodes (code, bonus_amount, expires_at, created_by)
            VALUES (?, ?, ?, ?)
        ''', (code.upper(), amount, expires_at, admin_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

async def use_promocode(user_id: int, code: str) -> tuple:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        # Проверяем существует ли промокод
        cursor.execute('''
            SELECT bonus_amount FROM promocodes 
            WHERE code = ? AND expires_at > datetime('now')
        ''', (code.upper(),))
        promocode = cursor.fetchone()
        
        if not promocode:
            return (False, "Промокод не найден или истёк")
        
        # Проверяем не использовал ли уже пользователь
        cursor.execute('''
            SELECT 1 FROM used_promocodes 
            WHERE user_id = ? AND code = ?
        ''', (user_id, code.upper()))
        
        if cursor.fetchone():
            return (False, "Вы уже использовали этот промокод")
        
        # Зачисляем бонус
        update_balance(user_id, promocode[0])
        
        # Фиксируем использование
        cursor.execute('''
            INSERT INTO used_promocodes (user_id, code)
            VALUES (?, ?)
        ''', (user_id, code.upper()))
        
        conn.commit()
        return (True, f"Получено {promocode[0]} монет!")
    finally:
        conn.close()

async def admin_events_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить событие", callback_data='admin_add_event')], 
        [InlineKeyboardButton("❌ Удалить событие", callback_data='admin_delete_event')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
    ]
    await update.callback_query.edit_message_text(
        "🛠 Управление событиями и промокодами:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_edit_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = get_all_events()  # Нужно реализовать эту функцию
    if not events:
        await update.callback_query.edit_message_text(
            "Нет активных событий для редактирования",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_events')]
            ])
        )
        return
    
    keyboard = []
    for event in events:
        keyboard.append([InlineKeyboardButton(
            f"{event['name']} (ID: {event['id']})", 
            callback_data=f"edit_event_{event['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_events')])
    
    await update.callback_query.edit_message_text(
        "Выберите событие для редактирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
def get_all_events():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM events')
    events = []
    for row in cursor.fetchall():
        events.append({
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'multiplier': row[3],
            'fixed_win': row[4],
            'discount': row[5],
            'attempts': row[6],
            'expires_at': row[7],
            'created_by': row[8]
        })
    conn.close()
    return events


def decrease_event_attempts(event_id: int):
    """Уменьшаем количество оставшихся попыток"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE events 
        SET attempts = attempts - 1 
        WHERE event_id = ? AND attempts > 0
    ''', (event_id,))
    conn.commit()
    conn.close()


async def rating_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🏆 Топ по балансу", callback_data='rating_balance')],
        [InlineKeyboardButton("💎 Топ по выигрышам", callback_data='rating_profit')],
        [InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "📊 Рейтинги игроков:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "📊 Рейтинги игроков:",
            reply_markup=reply_markup
        )

async def show_rating(update: Update, context: ContextTypes.DEFAULT_TYPE, rating_type: str) -> None:
    if rating_type == 'balance':
        top_users = get_top_balance()
        title = "🏆 Топ-15 по балансу:\n\n"
        for i, user in enumerate(top_users, 1):
            title += f"{i}. {user['first_name']} {user['last_name'] or ''} (@{user['username'] or 'нет'}) - {user['balance']} монет\n"
    else:
        top_users = get_top_profit()
        title = "💎 Топ-15 по чистому выигрышу:\n\n"
        for i, user in enumerate(top_users, 1):
            title += f"{i}. {user['first_name']} {user['last_name'] or ''} (@{user['username'] or 'нет'}) - {user['profit']} монет\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Топ по балансу", callback_data='rating_balance'),
         InlineKeyboardButton("🔄 Топ по выигрышам", callback_data='rating_profit')],
        [InlineKeyboardButton("🔙 Назад", callback_data='rating_menu')]
    ]
    
    await update.callback_query.edit_message_text(
        title,
        reply_markup=InlineKeyboardMarkup(keyboard))

async def show_disclaimer(update: Update, context: ContextTypes.DEFAULT_TYPE, from_handler: str = "start"):
    # Удаляем предыдущий дисклеймер если есть
    if 'disclaimer_msg_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['disclaimer_msg_id']
            )
        except Exception as e:
            logger.error(f"Ошибка удаления предыдущего дисклеймера: {e}")

    disclaimer_text = """
⚠️ <b>ВАЖНАЯ ИНФОРМАЦИЯ</b> ⚠️

Этот Telegram-бот <b>"Lucky Azart"</b> является исключительно <b>развлекательным приложением</b> и <b>не имеет отношения к реальным азартным играм</b>.

<b>▫️ Основные положения:</b>
• Все "ставки" совершаются с использованием виртуальной игровой валюты
• Никакие реальные деньги не принимаются и не выплачиваются
• Бот не является азартной игрой в юридическом смысле

<b>▫️ Юридический статус:</b>
• Не требует лицензии на азартные игры
• Не проводит денежные транзакции
• Не принимает депозиты и не выплачивает выигрыши

<b>▫️ Для пользователей из разных стран:</b>
• <b>РФ:</b> Соответствует ФЗ-244 "О государственном регулировании азартных игр"
• <b>ЕС:</b> Не подпадает под Директиву 2014/62/EU об азартных играх
• <b>США:</b> Не нарушает UIGEA (Unlawful Internet Gambling Enforcement Act)

<b>▫️ Ограничения:</b>
• Запрещено использование лицами младше 18 лет
• Запрещено использование в коммерческих целях
• Администрация не несёт ответственности за возможную игровую зависимость

Используя этого бота, вы подтверждаете, что:
1. Понимаете виртуальную природу "ставок"
2. Не ожидаете реальных денежных выплат
3. Осознаёте, что это развлекательный сервис

Полный текст пользовательского соглашения доступен по команде /terms
"""
    buttons = [[InlineKeyboardButton("✅ Я понимаю", callback_data=f'disclaim_ok_{from_handler}')]]
    
    msg = await update.effective_message.reply_text(
        text=disclaimer_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='HTML'
    )
    
    # Сохраняем только ID сообщения
    context.user_data['disclaimer_msg_id'] = msg.message_id
    context.user_data['disclaimer_time'] = time.time()
    
    # Устанавливаем таймер только если есть job_queue
    if context.job_queue:
        context.job_queue.run_once(
            callback=auto_delete_disclaimer,
            when=10,
            chat_id=update.effective_chat.id,
            name=f"disclaim_{msg.message_id}"
        )

async def auto_delete_disclaimer(context: CallbackContext):
    
    if 'disclaimer_msg_id' not in context.user_data:
        return
        
    try:
        await context.bot.delete_message(...)
    except Exception:
        pass
        
    # Важно: очищаем данные даже если не удалилось сообщение
    context.user_data.pop('disclaimer_msg_id', None)
    context.user_data.pop('disclaimer_time', None)

# async def delete_disclaimer_callback(context: CallbackContext):
#     job = context.job
#     chat_id = job.chat_id
#     try:
#         # Проверяем, не было ли сообщение уже удалено
#         if 'disclaimer_message_id' in context.user_data:
#             message_id = context.user_data['disclaimer_message_id']
#             # Проверяем, что сообщение не было удалено ранее по кнопке
#             if time.time() - context.user_data.get('disclaimer_time', 0) >= 9.5:  # 0.5 сек погрешность
#                 await context.bot.delete_message(
#                     chat_id=chat_id,
#                     message_id=message_id
#                 )
#                 # Чистим данные
#                 context.user_data.pop('disclaimer_message_id', None)
#                 context.user_data.pop('disclaimer_time', None)
#     except Exception as e:
#         logger.error(f"Ошибка при удалении дисклеймера: {e}")
        
async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Проверяем есть ли активные события
    events_count = get_active_events_count()
    events_info = f"\n\n🎁 Доступно {events_count} активных бонусов!" if events_count > 0 else ""
    
    keyboard = [
        [InlineKeyboardButton("🎲 Кости", callback_data='game_dice'),
         InlineKeyboardButton("🎰 Слоты", callback_data='game_slots'),
         InlineKeyboardButton("🎡 Рулетка", callback_data='game_roulette')],
        [InlineKeyboardButton("📖 Правила игр", callback_data='game_rules')],
        [InlineKeyboardButton("🎉 Активные события", callback_data='events_menu')],  # ДОБАВЛЕНО
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f'🎮 <b>Выберите игру</b>{events_info}'
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def game_roulette_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    keyboard = [
        [InlineKeyboardButton("🔴 Красное", callback_data='roulette_red'),
         InlineKeyboardButton("⚫ Черное", callback_data='roulette_black')],
        [InlineKeyboardButton("🔢 Четное", callback_data='roulette_even'),
         InlineKeyboardButton("🔣 Нечетное", callback_data='roulette_odd')],
        [InlineKeyboardButton("1-18", callback_data='roulette_1to18'),
         InlineKeyboardButton("19-36", callback_data='roulette_19to36')],
        [InlineKeyboardButton("🔢 Поставить на число", callback_data='roulette_number')],
        [InlineKeyboardButton("🔙 Назад", callback_data='games_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🎡 Рулетка\n\nВыберите тип ставки:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🎡 Рулетка\n\nВыберите тип ставки:",
            reply_markup=reply_markup
        )

async def handle_roulette_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("❌ Вы не зарегистрированы. Используйте /start")
        return

    text = update.message.text.strip()
    
    try:
        # Если это выбор числа для ставки
        if context.user_data.get('roulette_bet_type') == 'number' and 'roulette_number' not in context.user_data:
            number = int(text)
            if number < 0 or number > 36:
                await update.message.reply_text("❌ Число должно быть от 0 до 36!")
                return
                
            context.user_data['roulette_number'] = number
            await update.message.reply_text(
                f"🎡 Выбрано число: {number}\n"
                "Теперь введите сумму ставки:"
            )
            return
            
        # Обработка суммы ставки
        bet_amount = int(text)
        if bet_amount <= 0:
            await update.message.reply_text("❌ Сумма ставки должна быть положительной!")
            return
            
        if user_data['balance'] < bet_amount:
            await update.message.reply_text(f"❌ Недостаточно средств! Ваш баланс: {user_data['balance']}")
            return
            
        # Получаем тип ставки
        bet_type = context.user_data['roulette_bet_type']
        
        # Для ставки на число используем сохраненное число
        if bet_type == 'number':
            if 'roulette_number' not in context.user_data:
                await update.message.reply_text("❌ Сначала выберите число!")
                return
            bet_type = str(context.user_data['roulette_number'])
        
        # Играем с учетом бонусов событий
        win, payout, result, applied_events, final_bet = await play_roulette(user_id, bet_type, bet_amount)
        
        # Формируем ответ
        if win:
            response = f"🎉 Вы выиграли {payout} монет!\n"
        else:
            response = f"❌ Вы проиграли {final_bet} монет.\n"
            
        response += f"🎡 {result}\n"
        
        # Добавляем информацию о примененных бонусах
        if applied_events:
            response += f"🎁 Примененные бонусы: {', '.join(applied_events)}\n"
            
        response += f"💰 Ваш баланс: {get_user(user_id)['balance']}"

        # Кнопка для повторной игры
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎡 Играть снова", callback_data='game_roulette')]])
        await update.message.reply_text(response, reply_markup=keyboard)
        
        # Очищаем контекст
        context.user_data.pop('roulette_bet_type', None)
        context.user_data.pop('roulette_number', None)
        
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите число!")

async def users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("💸 Перевести деньги", callback_data='transfer_money')],
        [InlineKeyboardButton("📊 Рейтинги", callback_data='rating_menu')],  # Добавлено
    ]
    
    if get_user(update.effective_user.id)['is_admin']:
        keyboard.append([InlineKeyboardButton("👑 Админка", callback_data='admin_panel')])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            '👤 Меню пользователей:',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            '👤 Меню пользователей:',
            reply_markup=reply_markup
        )

async def admin_delete_event_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора события для удаления"""
    events = get_all_events()
    
    if not events:
        await send_or_edit(update, 
                         "📭 Нет событий для удаления",
                         [[InlineKeyboardButton("🔙 Назад", callback_data='admin_events')]])
        return
    
    keyboard = []
    for event in events:
        event_info = f"{event['name']} (ID: {event['id']})"
        keyboard.append([InlineKeyboardButton(event_info, callback_data=f"admin_confirm_delete_{event['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_events')])
    
    await send_or_edit(update, "🗑 Выберите событие для удаления:", keyboard)

# Новая функция для отображения правил
async def game_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_text = """
📖 Правила игр:

🎲 Кости:
1. Выберите число от 1 до 6
2. Сделайте ставку
3. Если выпадет ваше число - выигрыш с коэффициентом 1:1 до 6:1
4. Коэффициент зависит от сложности выбранного числа

🎰 Слоты:
1. Сделайте ставку
2. Крутятся 3 барабана с символами
3. Два одинаковых символа - выигрыш 0.5x ставки
4. Три одинаковых символа - выигрыш 3x ставки
5. Три символа '7' - джекпот 10x ставки

🎡 Рулетка:
1. Выберите тип ставки:
   - 🔴 Красное (1:1)
   - ⚫ Черное (1:1)
   - 🔢 Четное (1:1)
   - 🔣 Нечетное (1:1)
   - 1-18 (1:1)
   - 19-36 (1:1)
   - Конкретное число (1-36, 35:1)
2. Сделайте ставку
3. Если выиграли - получите выплату по коэффициенту
4. 0 (зеро) - всегда проигрыш (кроме ставки на 0)
"""
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='games_menu')]]
    await update.callback_query.edit_message_text(
        rules_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def play_roulette(user_id: int, bet_type: str, bet_amount: int) -> Tuple[bool, int, str, list, int]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0, "Недостаточно средств", [], 0
    
    # ПРИМЕНЯЕМ БОНУСЫ СОБЫТИЙ
    final_bet, bonuses, applied_events = apply_event_bonuses(user_id, "roulette", bet_amount)
    
    # Проверяем, хватает ли баланса после применения скидок
    if user['balance'] < final_bet:
        return False, 0, "Недостаточно средств после применения скидок", [], 0

    # Генерация случайного числа (0-36)
    winning_number = random.randint(0, 36)
    
    # Определяем цвет числа (0 - зелёный)
    if winning_number == 0:
        color = "green"
    elif winning_number % 2 == 1:
        color = "red"  # Нечетные = красные (в европейской рулетке)
    else:
        color = "black"

    # Проверяем выигрыш
    win = False
    base_payout = 0
    payout_multiplier = 1
    
    if bet_type.isdigit():  # Ставка на конкретное число (1-36)
        if int(bet_type) == winning_number:
            win = True
            base_payout = final_bet * 35
            payout_multiplier = 35
    else:
        bet_type = bet_type.lower()
        if bet_type == "red" and color == "red":
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1
        elif bet_type == "black" and color == "black":
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1
        elif bet_type == "even" and winning_number % 2 == 0 and winning_number != 0:
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1
        elif bet_type == "odd" and winning_number % 2 == 1:
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1
        elif bet_type == "1to18" and 1 <= winning_number <= 18:
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1
        elif bet_type == "19to36" and 19 <= winning_number <= 36:
            win = True
            base_payout = final_bet * 1
            payout_multiplier = 1

    total_win_amount = 0
    
    if win:
        # ✅ ПРИМЕНЯЕМ БОНУСЫ ПРАВИЛЬНО
        total_win = base_payout + bonuses['fixed_bonus']     # + фиксированный бонус
        total_win_amount = int(total_win * bonuses['multiplier'])  # × множитель
        
        update_balance(user_id, total_win_amount)
        add_transaction(user_id, total_win_amount, "win", "roulette", 
                       f"bet:{bet_type},win:{winning_number},payout_x:{payout_multiplier},events:{applied_events},final_bet:{final_bet}")
    else:
        # ✅ ПРИ ПРОИГРЫШЕ: списываем только final_bet
        update_balance(user_id, -final_bet)
        add_transaction(user_id, -final_bet, "loss", "roulette", 
                       f"bet:{bet_type},win:{winning_number},events:{applied_events},final_bet:{final_bet}")

    return win, total_win_amount, f"Выпало: {winning_number} ({color})", applied_events, final_bet

async def transfer_money_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.edit_message_text(
        "💸 Перевод средств\n\n"
        "Введите ID/username и сумму через пробел:\n"
        "Например:\n"
        "123456 100\n"
        "или\n"
        "@username 200",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
    )
    context.user_data['transfer_step'] = 'wait_input'
async def handle_transfer_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        recipient_input = update.message.text.strip()
        
        # Проверяем, ввели ли ID (число) или username (начинается с @)
        if recipient_input.startswith('@'):
            # Поиск по username
            username = recipient_input[1:]
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                await update.message.reply_text(
                    f"❌ Пользователь @{username} не найден",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
                )
                return
                
            recipient_id = result[0]
        else:
            # Поиск по ID
            try:
                recipient_id = int(recipient_input)
            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат. Введите ID (число) или @username",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
                )
                return
                
            if not get_user(recipient_id):
                await update.message.reply_text(
                    f"❌ Пользователь с ID {recipient_id} не найден",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
                )
                return
        
        # Сохраняем ID получателя и переходим к вводу суммы
        context.user_data['transfer_recipient_id'] = recipient_id
        context.user_data['transfer_step'] = 'wait_amount'
        
        recipient = get_user(recipient_id)
        recipient_name = f"{recipient['first_name']} {recipient['last_name'] or ''}"
        
        await update.message.reply_text(
            f"👤 Получатель: {recipient_name}\n"
            f"🆔 ID: {recipient_id}\n\n"
            "Введите сумму для перевода:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='users_menu')]])
        )
        
    except Exception as e:
        logger.error(f"Transfer recipient error: {e}")
        await update.message.reply_text(
            "❌ Ошибка при обработке запроса",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
        )
async def handle_transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        sender_data = get_user(user_id)
        amount = int(update.message.text)
        
        if amount <= 0:
            await update.message.reply_text(
                "❌ Сумма должна быть положительной!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
            )
            return
            
        if sender_data['balance'] < amount:
            await update.message.reply_text(
                f"❌ Недостаточно средств. Ваш баланс: {sender_data['balance']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
            )
            return
            
        recipient_id = context.user_data['transfer_recipient_id']
        recipient_data = get_user(recipient_id)
        
        # Выполняем перевод
        update_balance(user_id, -amount)
        update_balance(recipient_id, amount)
        
        # Записываем транзакции
        add_transaction(user_id, -amount, "transfer_out", None, f"to:{recipient_id}")
        add_transaction(recipient_id, amount, "transfer_in", None, f"from:{user_id}")
        
        # Формируем имена для сообщения
        sender_name = f"{sender_data['first_name']} {sender_data['last_name'] or ''}"
        recipient_name = f"{recipient_data['first_name']} {recipient_data['last_name'] or ''}"
        
        await update.message.reply_text(
            f"✅ Перевод выполнен!\n\n"
            f"👤 Отправитель: {sender_name}\n"
            f"👤 Получатель: {recipient_name}\n"
            f"💵 Сумма: {amount} монет\n\n"
            f"💰 Ваш новый баланс: {sender_data['balance'] - amount}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]])
        )
        
        # Очищаем данные перевода
        context.user_data.pop('transfer_step', None)
        context.user_data.pop('transfer_recipient_id', None)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат суммы. Введите целое число:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
        )

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'transfer_step' not in context.user_data:
        return
    
    try:
        text = update.message.text.strip().split()
        if len(text) < 2:
            raise ValueError("Недостаточно данных")
            
        # Определяем получателя (первый элемент - ID или username)
        recipient_input = text[0]
        amount = int(text[1])
        
        # Проверяем сумму
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной!")
            return
            
        # Ищем получателя
        if recipient_input.startswith('@'):
            # Поиск по username
            username = recipient_input[1:]
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                await update.message.reply_text(f"❌ Пользователь @{username} не найден")
                return
                
            recipient_id = result[0]
        else:
            # Поиск по ID
            try:
                recipient_id = int(recipient_input)
            except ValueError:
                await update.message.reply_text("❌ Неверный формат ID. Введите число или @username")
                return
                
            if not get_user(recipient_id):
                await update.message.reply_text(f"❌ Пользователь с ID {recipient_id} не найден")
                return
        
        # Проверяем отправителя
        sender_id = update.effective_user.id
        sender_data = get_user(sender_id)
        
        if not sender_data:
            await update.message.reply_text("❌ Ошибка: ваш аккаунт не найден")
            return
            
        if sender_data['balance'] < amount:
            await update.message.reply_text(f"❌ Недостаточно средств. Ваш баланс: {sender_data['balance']}")
            return
            
        # Получаем данные получателя
        recipient_data = get_user(recipient_id)
        if not recipient_data:
            await update.message.reply_text("❌ Ошибка: получатель не найден")
            return
            
        # Выполняем перевод
        update_balance(sender_id, -amount)
        update_balance(recipient_id, amount)
        
        # Записываем транзакции
        add_transaction(sender_id, -amount, "transfer_out", None, f"to:{recipient_id}")
        add_transaction(recipient_id, amount, "transfer_in", None, f"from:{sender_id}")
        
        # Формируем сообщение
        sender_name = f"{sender_data['first_name']} {sender_data['last_name'] or ''}"
        recipient_name = f"{recipient_data['first_name']} {recipient_data['last_name'] or ''}"
        
        await update.message.reply_text(
            f"✅ Перевод выполнен!\n\n"
            f"👤 Отправитель: {sender_name}\n"
            f"👤 Получатель: {recipient_name}\n"
            f"💵 Сумма: {amount} монет\n\n"
            f"💰 Ваш новый баланс: {sender_data['balance'] - amount}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]])
        )
        
        # Очищаем данные перевода
        context.user_data.pop('transfer_step', None)
        
    except ValueError as e:
        await update.message.reply_text(
            f"❌ Ошибка ввода: {str(e)}\n"
            "Формат: ID/username сумма\n"
            "Примеры:\n123456 100\n@username 200",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
        )
    except Exception as e:
        logger.error(f"Transfer error: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при переводе",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='users_menu')]])
        )

async def timeout_callback(context: CallbackContext):
    job = context.job
    await context.bot.send_message(
        job.chat_id,
        "⏳ Время ожидания истекло. Возвращаю в главное меню.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎰 Главное меню", callback_data='back_to_menu')]])
    )

def set_timeout(context: CallbackContext):
    if 'job' in context.user_data:
        context.user_data['job'].schedule_removal()
    
    job = context.job_queue.run_once(
        timeout_callback, 
        60, 
        chat_id=context.user_data.get('chat_id'),
        name=str(context.user_data.get('user_id'))
    )
    context.user_data['job'] = job


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = get_user(update.effective_user.id)
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"💰 Баланс: {user_data['balance']} монет",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"💰 Баланс: {user_data['balance']} монет",
            reply_markup=reply_markup
        )

    if context.args:
        await check_balance(update, context, context.args[0])
    else:
        await check_balance(update, context)
    

async def game_dice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    keyboard = [
        [InlineKeyboardButton("1", callback_data='dice_1'),
         InlineKeyboardButton("2", callback_data='dice_2'),
         InlineKeyboardButton("3", callback_data='dice_3')],
        [InlineKeyboardButton("4", callback_data='dice_4'),
         InlineKeyboardButton("5", callback_data='dice_5'),
         InlineKeyboardButton("6", callback_data='dice_6')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🎲 Выберите число (1-6):\nОтправьте сумму ставки в чат.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🎲 Выберите число (1-6):\nОтправьте сумму ставки в чат.",
            reply_markup=reply_markup
        )

async def game_slots_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🎰 Игровые автоматы:\nОтправьте сумму ставки в чат.",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "🎰 Игровые автоматы:\nОтправьте сумму ставки в чат.",
            reply_markup=reply_markup
        )

async def handle_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not context.user_data.get('disclaimer_shown', False):
        await show_disclaimer(update, context, "game")
        return
    try:
        bet_amount = int(update.message.text)
        if bet_amount <= 0:
            await update.message.reply_text("❌ Сумма ставки должна быть положительной!")
            return
            
        if user_data['balance'] < bet_amount:
            await update.message.reply_text(f"❌ Недостаточно средств! Баланс: {user_data['balance']}")
            return
            
        game_type = context.user_data['current_game']
        
        if game_type == 'dice':
            if 'dice_guess' not in context.user_data:
                await update.message.reply_text("❌ Сначала выберите число!")
                return
                
            guess = context.user_data['dice_guess']
            won, coefficient, roll, applied_events, win_amount = await play_dice(user_id, bet_amount, guess)
            
            response = (
                f"🎉 Поздравляем! Выигрыш: {win_amount} монет!\n"
                f"🎲 Выпало: {roll} (ставка: {guess})\n"
                f"📈 Коэф: {coefficient:.2f}x\n"
                if won else
                f"❌ Проигрыш: {bet_amount} монет\n"
                f"🎲 Выпало: {roll} (ставка: {guess})\n"
                f"📈 Коэф был: {coefficient:.2f}x\n"
            )
            
        elif game_type == 'slots':
            won, coefficient, reels, applied_events, win_amount = await play_slots(user_id, bet_amount)
            
            if won:
                if reels[0] == reels[1] == reels[2]:
                    win_text = "🎉 ДЖЕКПОТ! Три 7!" if reels[0] == '7' else "🎉 Три одинаковых!"
                else:
                    win_text = "🎉 Два одинаковых!"
                
                response = (
                    f"{win_text}\n🎰 {' '.join(reels)}\n"
                    f"💰 Выигрыш: {win_amount} монет!\n"
                    f"📈 Коэф: {coefficient:.2f}x\n"
                )
            else:
                response = (
                    f"❌ Проигрыш: {bet_amount} монет\n"
                    f"🎰 {' '.join(reels)}\n"
                    f"📈 Коэф был: {coefficient:.2f}x\n"
                )
        
        # Добавляем информацию о примененных бонусах
        if applied_events:
            response += f"🎁 Примененные бонусы: {', '.join(applied_events)}\n"
        if applied_events:
            bonus_text = "🎁 АКТИВНЫЕ БОНУСЫ:\n"
            for bonus in applied_events:
                bonus_text += f"   • {bonus}\n"
            response = bonus_text + response
        # Общий вывод для всех игр
        response += f"💰 Баланс: {get_user(user_id)['balance']}"
        keyboard = [
            [InlineKeyboardButton("🔄 Играть снова", callback_data=f'game_{game_type}')],
            [InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]
        ]
        await update.message.reply_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Очищаем контекст
        context.user_data.pop('current_game', None)
        context.user_data.pop('dice_guess', None)
        
    except ValueError:
        await update.message.reply_text("❌ Введите целое число!")

# Админ-панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or user['is_admin'] != 1:  
        await update.callback_query.answer("❌ У вас нет прав доступа", show_alert=True)
        return
    
    if context.job_queue:
        context.job_queue.run_once(
            timeout_callback, 
            300,
            chat_id=update.effective_chat.id,
            name=str(update.effective_user.id))
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_full_stats'),
         InlineKeyboardButton("🛠 События", callback_data='admin_events')],
        [InlineKeyboardButton("👤 Пользователи", callback_data='admin_users'),
         InlineKeyboardButton("🎫 Промокоды", callback_data='admin_promocodes')],
        [InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]
    ]
    await send_or_edit(update, "👑 Админ-панель:", keyboard)

async def admin_add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора типа события для создания"""
    keyboard = [
        [InlineKeyboardButton("📈 Множитель выигрыша", callback_data='admin_add_event_multiplier')],
        [InlineKeyboardButton("💰 Фиксированный бонус", callback_data='admin_add_event_fixed')],
        [InlineKeyboardButton("🎫 Скидка на ставки", callback_data='admin_add_event_discount')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_events')]
    ]
    
    text = (
        "🎁 ВЫБЕРИТЕ ТИП СОБЫТИЯ\n\n"
        "📈 <b>Множитель выигрыша</b> - увеличивает выигрыш в X раз\n"
        "💰 <b>Фиксированный бонус</b> - добавляет N монет к выигрышу\n"  
        "🎫 <b>Скидка на ставки</b> - уменьшает стоимость ставок на N%\n\n"
        "Выберите тип:"
    )
    
    await send_or_edit(update, text, keyboard)

async def add_event_multiplier_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['event_type'] = 'multiplier'
    await send_or_edit(update, 
                      "Введите данные для события в формате:\n"
                      "Название|Описание|Множитель|Попытки (-1 для бесконечных)|Дней активности",
                      [[InlineKeyboardButton("🔙 Отмена", callback_data='admin_add_event')]])

async def process_event_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'event_type' not in context.user_data:
        await update.message.reply_text("❌ Сначала выберите тип события через меню")
        return

    try:
        data = update.message.text.split('|')
        if len(data) != 5:
            raise ValueError("Неверный формат данных")

        name = data[0].strip()
        description = data[1].strip()
        value = float(data[2].strip())
        attempts = int(data[3].strip())
        days_active = int(data[4].strip())

        event_type = context.user_data['event_type']
        admin_id = update.effective_user.id

        if event_type == 'multiplier':
            success = add_event(
                name=name,
                description=description,
                event_type="multiplier",
                value=value,
                attempts=attempts,
                days_active=days_active,
                admin_id=admin_id
            )
        elif event_type == 'fixed':
            success = add_event(
                name=name,
                description=description,
                event_type="fixed_win",
                value=value,
                attempts=attempts,
                days_active=days_active,
                admin_id=admin_id
            )
        elif event_type == 'discount':
            success = add_event(
                name=name,
                description=description,
                event_type="discount",
                value=value,
                attempts=attempts,
                days_active=days_active,
                admin_id=admin_id
            )

        if success:
            await update.message.reply_text("✅ Событие успешно создано!")
        else:
            await update.message.reply_text("❌ Ошибка при создании события")

    except ValueError as e:
        await update.message.reply_text(f"❌ Ошибка в формате данных: {str(e)}\n"
                                      "Правильный формат: Название|Описание|Значение|Попытки|Дней активности")
    finally:
        context.user_data.pop('event_type', None)

def get_all_promocodes():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT code, bonus_amount, expires_at, created_by 
        FROM promocodes 
        WHERE expires_at > datetime('now')
        ORDER BY expires_at ASC
    ''')
    
    promocodes = []
    for row in cursor.fetchall():
        promocodes.append({
            'code': row[0],
            'amount': row[1],
            'expires_at': row[2],
            'created_by': row[3]
        })
    conn.close()
    return promocodes

async def admin_full_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.job_queue:
        context.job_queue.run_once(
            timeout_callback, 
            300,  # 5 минут для админ-панели
            chat_id=update.effective_chat.id,
            name=str(update.effective_user.id))
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or not user['is_admin']:
        await query.answer("❌ У вас нет прав доступа")
        return
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(balance) FROM users')
        total_balance = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(amount) FROM transactions WHERE transaction_type = "win"')
        total_wins = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(amount) FROM transactions WHERE transaction_type = "loss"')
        total_losses = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(amount) FROM transactions WHERE transaction_type = "admin_add"')
        total_added = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(amount) FROM transactions WHERE transaction_type = "admin_remove"')
        total_removed = cursor.fetchone()[0] or 0
        
        profit = total_losses - total_wins + total_removed - total_added
        
        stats_text = (
            "📊 Полная статистика казино:\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"💰 Общий баланс всех пользователей: {total_balance} монет\n\n"
            f"🎉 Выиграно пользователями: {total_wins} монет\n"
            f"💸 Проиграно пользователями: {total_losses} монет\n\n"
            f"➕ Добавлено администраторами: {total_added} монет\n"
            f"➖ Снято администраторами: {total_removed} монет\n\n"
            f"🏦 Общая прибыль казино: {profit} монет"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Сбросить статистику", callback_data='admin_reset_stats')],
            [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
        ]
        
        await query.edit_message_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        await query.edit_message_text(
            "❌ Ошибка при получении статистики",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
    finally:
        conn.close()

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or not user['is_admin']:
        await query.answer("❌ У вас нет прав доступа")
        return
    
    keyboard = [
        [InlineKeyboardButton("📋 Список всех пользователей", callback_data='admin_users_list')],
        [InlineKeyboardButton("➕ Пополнить баланс", callback_data='admin_add_money')],
        [InlineKeyboardButton("➖ Снять средства", callback_data='admin_remove_money')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')],
    ]
    
    await query.edit_message_text(
        '👤 Управление пользователями:',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_add_money_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    context.user_data['admin_action'] = 'add'
    context.user_data['admin_step'] = 'wait_user_id'
    
    await query.edit_message_text(
        "💵 ПОПОЛНЕНИЕ БАЛАНСА\n\n"
        "Введите ID пользователя или @username:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
    )

async def admin_remove_money_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    context.user_data['admin_action'] = 'remove'
    context.user_data['admin_step'] = 'wait_user_id'
    
    await query.edit_message_text(
        "💸 СНЯТИЕ СРЕДСТВ\n\n"
        "Введите ID пользователя или @username:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
    )

async def admin_process_user_id(update: Update, context: CallbackContext):
    try:
        user_input = update.message.text.strip()
        
        # Поиск по username
        if user_input.startswith('@'):
            username = user_input[1:]
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, first_name, last_name, balance FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                await update.message.reply_text(
                    f"❌ Пользователь @{username} не найден",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]])
                )
                return
                
            user_id, first_name, last_name, balance = result
            user_data = {
                'user_id': user_id,
                'first_name': first_name,
                'last_name': last_name,
                'balance': balance
            }
        else:
            # Поиск по ID
            try:
                user_id = int(user_input)
            except ValueError:
                await update.message.reply_text(
                    "❌ Неверный формат. Введите ID (число) или @username",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]])
                )
                return
                
            user_data = get_user(user_id)
            if not user_data:
                await update.message.reply_text(
                    f"❌ Пользователь с ID {user_id} не найден",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]])
                )
                return
        
        context.user_data['admin_user_id'] = user_id
        context.user_data['admin_step'] = 'wait_amount'
        
        action = context.user_data['admin_action']
        
        await update.message.reply_text(
            f"👤 Пользователь: {user_data['first_name']} {user_data['last_name'] or ''}\n"
            f"🆔 ID: {user_id}\n"
            f"💰 Текущий баланс: {user_data['balance']} монет\n\n"
            f"Введите сумму для {'пополнения' if action == 'add' else 'снятия'}:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
        )
        
    except Exception as e:
        logger.error(f"Admin user search error: {e}")
        await update.message.reply_text(
            "❌ Ошибка при обработке запроса",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]])
        )

async def admin_process_amount(update: Update, context: CallbackContext):
    try:
        amount = int(update.message.text)
        if amount <= 0:
            await update.message.reply_text(
                "❌ Сумма должна быть положительной!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
            )
            return
        
        user_id = context.user_data['admin_user_id']
        action = context.user_data['admin_action']
        user_data = get_user(user_id)
        
        # Убрана проверка баланса при снятии
        new_balance = user_data['balance'] + (amount if action == 'add' else -amount)
        
        # Запрещаем отрицательный баланс
        if new_balance < 0:
            await update.message.reply_text(
                "❌ Нельзя установить отрицательный баланс!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
            )
            return
        
        update_balance(user_id, amount if action == 'add' else -amount)
        
        transaction_type = "admin_add" if action == 'add' else "admin_remove"
        add_transaction(user_id, amount, transaction_type)
        
        await update.message.reply_text(
            f"✅ Баланс успешно {'пополнен' if action == 'add' else 'уменьшен'}!\n\n"
            f"👤 Пользователь: {user_data['first_name']} {user_data['last_name'] or ''}\n"
            f"🆔 ID: {user_id}\n"
            f"💰 Было: {user_data['balance']} монет\n"
            f"💵 Сумма: {amount} монет\n"
            f"💰 Стало: {new_balance} монет",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админку", callback_data='admin_panel')]])
        )
        
        context.user_data.pop('admin_action', None)
        context.user_data.pop('admin_step', None)
        context.user_data.pop('admin_user_id', None)
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат суммы. Введите число:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
        )

async def admin_wait_for_user_id(update: Update, context: CallbackContext) -> None:
    query = update.callback_query   
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or not user['is_admin']:
        await query.answer("❌ У вас нет прав доступа")
        return
    
    # Определяем действие на основе callback_data
    if query.data == 'admin_add_money':
        context.user_data['admin_action'] = 'add'
    elif query.data == 'admin_remove_money':
        context.user_data['admin_action'] = 'remove'
    
    context.user_data['admin_step'] = 'wait_user_id'
    
    await query.edit_message_text(
        "Введите ID пользователя:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_users')]])
    )

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or not user['is_admin']:
        await query.answer("❌ У вас нет прав доступа")
        return
    
    users = get_all_users()
    users_text = "📋 Список пользователей:\n\n"
    
    for user in users:
        username = user['username'] or "Нет username"
        users_text += (
            f"👤 {user['first_name']} {user['last_name'] or ''} (@{username})\n"
            f"🆔 ID: {user['user_id']}\n"
            f"💰 Баланс: {user['balance']} монет\n\n"
        )
    
    if len(users_text) > 4000:
        users_text = users_text[:4000] + "\n\n... (список обрезан из-за ограничения длины сообщения)"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_users')]]
    
    await query.edit_message_text(
        users_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    user = get_user(update.effective_user.id)
    if not user or not user['is_admin']:
        await query.answer("❌ У вас нет прав доступа")
        return
    
    reset_statistics()
    
    await query.edit_message_text(
        "✅ Вся статистика и балансы пользователей сброшены к начальным значениям",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_full_stats')]])
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not get_user(user_id):
        await update.message.reply_text("❌ Вы не зарегистрированы. Используйте /start")
        return

    # 1. Проверяем создание события (ПЕРВЫМ, чтобы перехватывать все сообщения)
    if 'event_creation' in context.user_data:
        await handle_event_creation(update, context)
        return
    
    # 2. Проверяем рулетку
    if 'roulette_bet_type' in context.user_data:
        await handle_roulette_bet(update, context)
        return
    
    # 3. Проверяем другие игры
    if 'current_game' in context.user_data:
        await handle_bet(update, context)
        return
    
    # 4. Проверяем перевод денег
    if 'transfer_step' in context.user_data:
        await handle_transfer(update, context)
        return
    
    # 5. Проверяем админ-действия
    if 'admin_step' in context.user_data:
        step = context.user_data['admin_step']
        if step == 'wait_user_id':
            await admin_process_user_id(update, context)
        elif step == 'wait_amount':
            await admin_process_amount(update, context)
        return
    
    if update.message.text.startswith('/balance'):
        parts = update.message.text.split()
        if len(parts) > 1:
            await check_balance(update, context, parts[1])
        else:
            await check_balance(update, context)
        return

    
    # 5. Общие команды
    await menu(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    logger.info(f"Received callback_data: {query.data}")  # Логируем
    data = query.data
    
    if data.startswith('disclaim_ok_'):
        try:
            # Удаляем сообщение с дисклеймером  
            await query.message.delete()
            
            # Очищаем данные дисклеймера
            context.user_data.pop('disclaimer_msg_id', None)
            context.user_data.pop('disclaimer_time', None)
            context.user_data['disclaimer_shown'] = True  # Добавляем флаг
            
            # Определяем куда переходить
            target = data.split('_')[-1]
            
            if target == "start":
                await menu(update, context)
            elif target == "game":
                game_type = context.user_data.get('current_game')
                if game_type == 'dice':
                    await game_dice_menu(update, context)
                elif game_type == 'slots':
                    await game_slots_menu(update, context)
                elif game_type == 'roulette':
                    await game_roulette_menu(update, context)
        except Exception as e:
            logger.error(f"Ошибка при обработке дисклеймера: {e}")
            return
    
    # 2. Главное меню
    elif data == 'back_to_menu':
        await menu(update, context)
    
    # 3. Меню игр
    elif data == 'games_menu':
        await games_menu(update, context)
    
    # 4. Игра в кости
    elif data.startswith('dice_'):
        guess = int(data.split('_')[1])
        context.user_data['dice_guess'] = guess
        await query.edit_message_text(
            f"🎲 Выбрано число: {guess}\nОтправьте сумму ставки в чат.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data='game_dice')]
            ])
        )
    
    # 5. Меню пользователей
    elif data == 'events_menu':
        await events_menu(update, context)
    elif data.startswith('view_event_'):
        await view_event(update, context)
    elif data == 'admin_add_event':
        await admin_add_event(update, context)
    elif data == 'admin_add_event_multiplier':
        await admin_add_event_multiplier(update, context)
    elif data == 'admin_add_event_fixed':
        await admin_add_event_fixed(update, context)  
    elif data == 'admin_add_event_discount':
        await admin_add_event_discount(update, context)
    elif data == 'admin_cancel_event':  # НОВЫЙ ОБРАБОТЧИК ДЛЯ ОТМЕНЫ
        await cancel_event_creation(update, context)
    elif data == 'admin_events':
        await admin_events_menu(update, context)
    elif data == 'admin_add_event':
        await admin_add_event(update, context)
    elif data == 'admin_view_events':
        await admin_view_events(update, context)
    elif data == 'admin_delete_event':
        await admin_delete_event_menu(update, context)
    elif data.startswith('admin_event_info_'):
        await admin_event_info(update, context)
    elif data.startswith('admin_confirm_delete_'):
        await admin_confirm_delete(update, context)
    elif data.startswith('admin_delete_confirm_'):
        await admin_delete_confirm(update, context)
    elif data == 'users_menu':
        await users_menu(update, context)
    elif data == 'game_dice':
        context.user_data['current_game'] = 'dice'
        await game_dice_menu(update, context)
    elif data == 'game_slots':
        context.user_data['current_game'] = 'slots'
        await game_slots_menu(update, context)
    elif data == 'game_roulette':
        context.user_data['current_game'] = 'roulette'
        await game_roulette_menu(update, context)
    # 6. Админ-панель
    elif data == 'admin_panel':
        user = get_user(update.effective_user.id)
        if user and user['is_admin']:
            await admin_panel(update, context)
        else:
            await query.answer("❌ У вас нет прав доступа", show_alert=True)
    
    elif data == 'users_menu':
        await users_menu(update, context)
    elif data == 'balance':
        await balance(update, context)
    elif data == 'admin_panel':
        await admin_panel(update, context)
    elif data == 'admin_full_stats':
        await admin_full_stats(update, context)
    elif data == 'admin_users':
        await admin_users(update, context)
    elif data == 'admin_users_list':
        await admin_users_list(update, context)
    elif data == 'admin_add_money':
        await admin_add_money_handler(update, context)
    elif data == 'admin_remove_money':
        await admin_remove_money_handler(update, context)
    elif data == 'admin_reset_stats':
        await admin_reset_stats(update, context)
    elif data == 'game_rules':
        await game_rules(update, context)
    elif data == 'transfer_money':
        await transfer_money_menu(update, context)
    elif data == 'rating_menu':
        await rating_menu(update, context)
    elif data == 'rating_balance':
        await show_rating(update, context, 'balance')
    elif data == 'rating_profit':
        await show_rating(update, context, 'profit')
    elif data.startswith('dice_'):
        guess = int(data.split('_')[1])
        context.user_data['dice_guess'] = guess
        await query.edit_message_text(
            f"🎲 Выбрано число: {guess}\n"
            "Отправьте сумму ставки в чат."
        )
        if context.job_queue:
            job = context.job_queue.run_once(
                timeout_callback, 
                60, 
                chat_id=update.effective_chat.id,
                name=str(update.effective_user.id)
            )
            context.user_data['job'] = job
    elif data.startswith('roulette_'):
        bet_type = data.split('_')[1]
        context.user_data['roulette_bet_type'] = bet_type
        
        if bet_type == 'number':
            await query.edit_message_text(
                "🎡 Ставка на число\n\n"
                "Введите число от 0 до 36:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='game_roulette')]])
            )
        else:
            await query.edit_message_text(
                f"🎡 Выбрана ставка: {get_bet_type_name(bet_type)}\n\n"
                "Введите сумму ставки:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='game_roulette')]])
            )

def get_top_balance(limit=15) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, first_name, last_name, balance 
        FROM users 
        ORDER BY balance DESC 
        LIMIT ?
    ''', (limit,))
    users = cursor.fetchall()
    conn.close()
    
    return [{
        'user_id': user[0],
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3],
        'balance': user[4]
    } for user in users]

def get_top_profit(limit=15) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.last_name,
               COALESCE(SUM(CASE WHEN t.transaction_type = 'win' THEN t.amount ELSE 0 END), 0) -
               COALESCE(SUM(CASE WHEN t.transaction_type = 'loss' THEN t.amount ELSE 0 END), 0) as profit
        FROM users u
        LEFT JOIN transactions t ON u.user_id = t.user_id
        GROUP BY u.user_id
        ORDER BY profit DESC
        LIMIT ?
    ''', (limit,))
    users = cursor.fetchall()
    conn.close()
    
    return [{
        'user_id': user[0],
        'username': user[1],
        'first_name': user[2],
        'last_name': user[3],
        'profit': user[4]
    } for user in users]

def get_bet_type_name(bet_type: str) -> str:
    names = {
        'red': '🔴 Красное',
        'black': '⚫ Черное',
        'even': '🔢 Четное',
        'odd': '🔣 Нечетное',
        '1to18': '1-18',
        '19to36': '19-36',
        'number': '🔢 Конкретное число'
    }
    return names.get(bet_type, bet_type)

# def save_user_data(update: Update, context: CallbackContext):
#         context.user_data['chat_id'] = update.effective_chat.id
#         context.user_data['user_id'] = update.effective_user.id
#         return True

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CallbackQueryHandler(button_handler))   
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(admin_events_menu, pattern='^admin_events$'))
    application.add_handler(CallbackQueryHandler(admin_edit_events, pattern='^admin_edit_events$'))
    application.add_handler(CallbackQueryHandler(events_menu, pattern='^events_menu$'))

    application.run_polling()

if __name__ == '__main__':
    main()