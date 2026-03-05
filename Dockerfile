FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Отключаем PEP 668
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Копируем requirements
COPY requirements.txt .

# Установка Python пакетов с игнорированием ошибок
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --ignore-installed -r requirements.txt || \
    pip install --no-cache-dir pyTelegramBotAPI requests telethon && \
    pip install --no-cache-dir --force-reinstall --no-deps pyTelegramBotAPI

# Копируем код
COPY . .

# Создаем папку для базы данных
RUN mkdir -p /app/data

# Запуск
CMD ["python", "main.py"]
