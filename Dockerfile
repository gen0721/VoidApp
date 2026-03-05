FROM python:3.9-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY main.py .

# Создание папок
RUN mkdir -p data

# Запуск
CMD ["python", "main.py"]
