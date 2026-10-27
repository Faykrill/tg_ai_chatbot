FROM python:3.13-slim

# Не буферизуем вывод Python — чтобы логи в докере были видны сразу
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала копируем зависимости — чтобы Docker кэшировал этот слой
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Потом копируем код
COPY src/ ./src/

# Команда запуска
CMD ["python", "src/main.py"]