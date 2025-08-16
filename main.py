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
TOKEN = "7802784921:AAHjeDU2Cp_THJGEnDpsvE5sM67L3qxQioQ"
ADMIN_IDS = [123456789]  # Ваш Telegram ID
DATABASE_NAME = "casino_bot.db"
INITIAL_BALANCE = 1000

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        balance INTEGER DEFAULT 1000,
        registration_date TEXT,
        is_admin INTEGER DEFAULT 0
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        transaction_type TEXT,
        game_type TEXT,
        result TEXT,
        timestamp TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    for admin_id in ADMIN_IDS:
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (admin_id,))
        if not cursor.fetchone():
            cursor.execute(
                'INSERT INTO users (user_id, is_admin, registration_date) VALUES (?, ?, ?)',
                (admin_id, 1, datetime.now().isoformat())
            )
        else:
            cursor.execute(
                'UPDATE users SET is_admin = ? WHERE user_id = ?',
                (1, admin_id)
            )
    
    conn.commit()
    conn.close()

init_db()

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

async def play_dice(user_id: int, bet_amount: int, guess: int) -> Tuple[bool, float, int]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0.0, 0
    
    coefficient = calculate_complex_coefficient(user_id, bet_amount, "dice")
    roll = random.randint(1, 6)
    
    if guess == roll:
        win_amount = int(bet_amount * coefficient)
        update_balance(user_id, win_amount)
        add_transaction(user_id, win_amount, "win", "dice", f"guess:{guess},roll:{roll},coef:{coefficient:.2f}")
        return True, coefficient, roll
    
    update_balance(user_id, -bet_amount)
    add_transaction(user_id, -bet_amount, "loss", "dice", f"guess:{guess},roll:{roll},coef:{coefficient:.2f}")
    return False, coefficient, roll

async def play_slots(user_id: int, bet_amount: int) -> Tuple[bool, float, list]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0.0, []
    
    coefficient = calculate_complex_coefficient(user_id, bet_amount, "slots")
    symbols = ['🍒', '🍋', '🍊', '🍇', '🍉', '7']
    reels = [random.choice(symbols) for _ in range(3)]
    
    if reels[0] == reels[1] == reels[2]:
        win_coefficient = 3 if reels[0] == '7' else 1
        win_amount = int(bet_amount * coefficient * win_coefficient)
        update_balance(user_id, win_amount)
        add_transaction(user_id, win_amount, "win", "slots", f"reels:{''.join(reels)},coef:{coefficient:.2f}x{win_coefficient}")
        return True, coefficient * win_coefficient, reels
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        win_amount = int(bet_amount * 0.5)
        update_balance(user_id, win_amount)
        add_transaction(user_id, win_amount, "win", "slots", f"reels:{''.join(reels)},coef:0.5")
        return True, 0.5, reels
    
    update_balance(user_id, -bet_amount)
    add_transaction(user_id, -bet_amount, "loss", "slots", f"reels:{''.join(reels)},coef:{coefficient:.2f}")
    return False, coefficient, reels


# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not get_user(user.id):
        create_user(user.id, user.username, user.first_name, user.last_name)
        await update.message.reply_text(
            f"🎰 Добро пожаловать в Lucky Casino, {user.first_name}!\n"
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
    
    keyboard = [
        [InlineKeyboardButton("🎮 Игры", callback_data='games_menu')],
        [InlineKeyboardButton("💰 Баланс", callback_data='balance')],
        [InlineKeyboardButton("👤 Пользователи", callback_data='users_menu')],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Очищаем таймер, если он был
    if 'job' in context.user_data:
        context.user_data['job'].schedule_removal()
        del context.user_data['job']
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            '🎰 Главное меню:',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            '🎰 Главное меню:',
            reply_markup=reply_markup
        )

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
⚠️ <b>ВНИМАЛЬНО: ВИРТУАЛЬНОЕ КАЗИНО</b> ⚠️

Это развлекательный бот без реальных ставок.
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
    job = context.job
    chat_id = job.chat_id
    user_data = context.user_data
    
    try:
        if 'disclaimer_msg_id' not in user_data:
            return
            
        msg_id = user_data['disclaimer_msg_id']
        post_time = user_data.get('disclaimer_time', 0)
        
        # Удаляем только если прошло ≥9 секунд
        if time.time() - post_time >= 9:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=msg_id
            )
            # Чистим данные
            user_data.pop('disclaimer_msg_id', None)
            user_data.pop('disclaimer_time', None)
    except Exception as e:
        logger.error(f"Ошибка автоудаления: {e}")

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
    keyboard = [
        [InlineKeyboardButton("🎲 Кости", callback_data='game_dice'),
         InlineKeyboardButton("🎰 Слоты", callback_data='game_slots'),
         InlineKeyboardButton("🎡 Рулетка", callback_data='game_roulette')],
        [InlineKeyboardButton("📖 Правила игр", callback_data='game_rules')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(
        '🎮 Выберите игру:',
        reply_markup=reply_markup
    )

async def game_roulette_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    context.user_data['current_game'] = 'roulette'
    await show_disclaimer(update, context, "game")

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
        # Если это выбор числа для ставки (проверяем только когда ожидается число)
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
            
        # Обработка суммы ставки (здесь НЕ проверяем 0-36)
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
        
        # Играем
        win, payout, result = await play_roulette(user_id, bet_type, bet_amount)
        
        # Формируем ответ
        if win:
            response = f"🎉 Вы выиграли {payout} монет!\n"
        else:
            response = f"❌ Вы проиграли {bet_amount} монет.\n"
            
        response += f"🎡 {result}\n"
        response += f"💰 Ваш баланс: {user_data['balance'] + (payout - bet_amount) if win else user_data['balance'] - bet_amount}"

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

async def play_roulette(user_id: int, bet_type: str, bet_amount: int) -> Tuple[bool, int, str]:
    user = get_user(user_id)
    if not user or user['balance'] < bet_amount:
        return False, 0, "Недостаточно средств"

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
    payout = 0
    
    if bet_type.isdigit():  # Ставка на конкретное число (1-36)
        if int(bet_type) == winning_number:
            win = True
            payout = bet_amount * 35
    else:
        bet_type = bet_type.lower()
        if bet_type == "red" and color == "red":
            win = True
            payout = bet_amount * 1
        elif bet_type == "black" and color == "black":
            win = True
            payout = bet_amount * 1
        elif bet_type == "even" and winning_number % 2 == 0 and winning_number != 0:
            win = True
            payout = bet_amount * 1
        elif bet_type == "odd" and winning_number % 2 == 1:
            win = True
            payout = bet_amount * 1
        elif bet_type == "1to18" and 1 <= winning_number <= 18:
            win = True
            payout = bet_amount * 1
        elif bet_type == "19to36" and 19 <= winning_number <= 36:
            win = True
            payout = bet_amount * 1
        elif bet_type in ["col1", "col2", "col3"]:  # Колонки (1-12, 13-24, 25-36)
            col_num = int(bet_type[-1])
            if (col_num == 1 and 1 <= winning_number <= 12) or \
               (col_num == 2 and 13 <= winning_number <= 24) or \
               (col_num == 3 and 25 <= winning_number <= 36):
                win = True
                payout = bet_amount * 2
        elif bet_type in ["doz1", "doz2", "doz3"]:  # Дюжины (1-12, 13-24, 25-36)
            doz_num = int(bet_type[-1])
            if (doz_num == 1 and 1 <= winning_number <= 12) or \
               (doz_num == 2 and 13 <= winning_number <= 24) or \
               (doz_num == 3 and 25 <= winning_number <= 36):
                win = True
                payout = bet_amount * 2

    # Обновляем баланс
    if win:
        update_balance(user_id, payout)
        add_transaction(user_id, payout, "win", "roulette", f"bet:{bet_type},win:{winning_number}")
    else:
        update_balance(user_id, -bet_amount)
        add_transaction(user_id, -bet_amount, "loss", "roulette", f"bet:{bet_type},win:{winning_number}")

    return win, payout, f"Выпало: {winning_number} ({color})"

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
    context.user_data['game_type'] = 'dice'
    await show_disclaimer(update, context, "game")
    # Устанавливаем флаг, что дисклеймер показан
    context.user_data['disclaimer_shown'] = True    

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

    context.user_data['current_game'] = 'slots'
    await show_disclaimer(update, context, "game")

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
            won, coefficient, roll = await play_dice(user_id, bet_amount, guess)
            
            response = (
    f"🎉 Поздравляем! Выигрыш: {bet_amount * coefficient:.0f} монет!\n"
    f"🎲 Выпало: {roll} (ставка: {guess})\n"
    f"📈 Коэф: {coefficient:.2f}x\n"
    if won else
    f"❌ Проигрыш: {bet_amount} монет\n"
    f"🎲 Выпало: {roll} (ставка: {guess})\n"
    f"📈 Коэф был: {coefficient:.2f}x\n"
)
            
        elif game_type == 'slots':
            won, coefficient, reels = await play_slots(user_id, bet_amount)
            
            if won:
                if reels[0] == reels[1] == reels[2]:
                    win_text = "🎉 ДЖЕКПОТ! Три 7!" if reels[0] == '7' else "🎉 Три одинаковых!"
                else:
                    win_text = "🎉 Два одинаковых!"
                
                response = (
                    f"{win_text}\n🎰 {' '.join(reels)}\n"
                    f"💰 Выигрыш: {bet_amount * coefficient:.0f} монет!\n"
                    f"📈 Коэф был: {coefficient:.2f}x\n"
                )
            else:
                response = (
                    f"❌ Проигрыш: {bet_amount} монет\n"
                    f"🎰 {' '.join(reels)}\n"
                    f"📈 Коэф был: {coefficient:.2f}x\n"
                )
        
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
        [InlineKeyboardButton("📊 Полная статистика", callback_data='admin_full_stats')],
        [InlineKeyboardButton("👤 Управление пользователями", callback_data='admin_users')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='back_to_menu')],
    ]
    
    await query.edit_message_text(
        '👑 Административная панель:',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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

    # 1. Сначала проверяем рулетку
    if 'roulette_bet_type' in context.user_data:
        await handle_roulette_bet(update, context)
        return
    
    if update.message.text.startswith('/balance'):
        parts = update.message.text.split()
        if len(parts) > 1:
            await check_balance(update, context, parts[1])
        else:
            await check_balance(update, context)
        return
    
    # 2. Проверяем другие игры
    if 'current_game' in context.user_data:
        await handle_bet(update, context)
        return
    
    # 3. Проверяем перевод денег
    if 'transfer_step' in context.user_data:
        await handle_transfer(update, context)
        return
    
    # 4. Проверяем админ-действия
    if 'admin_step' in context.user_data:
        step = context.user_data['admin_step']
        if step == 'wait_user_id':
            await admin_process_user_id(update, context)
        elif step == 'wait_amount':
            await admin_process_amount(update, context)
        return
    
    # 5. Общие команды
    await menu(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('disclaim_ok_'):
        try:
            # Удаляем сообщение с дисклеймером
            await query.message.delete()
            context.user_data.pop('disclaimer_msg_id', None)
            
            # Определяем куда переходить после принятия
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
            logger.error(f"Ошибка обработки дисклеймера: {e}")
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
    elif data == 'users_menu':
        await users_menu(update, context)
    
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
    
    application.run_polling()

if __name__ == '__main__':
    main()