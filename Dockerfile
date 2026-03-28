FROM python:3.11-slim

# Evitar .pyc e garantir logs sem buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Instalar dependências Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 2) Copiar o código
COPY . /app

# 3) Iniciar o app usando a porta do Render
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT