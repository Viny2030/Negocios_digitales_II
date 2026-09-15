FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema mínimas para compilar numpy/scipy si hiciera falta
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docs ./docs

EXPOSE 8000

# Forma "shell" (no exec/JSON array) a propósito: así se expande la
# variable de entorno. Railway (y la mayoría de los PaaS) inyectan PORT
# dinámicamente; si el contenedor no escucha en ese puerto, el healthcheck
# falla y el deploy nunca queda "healthy". El fallback ${PORT:-8000} deja
# `docker run`/`docker compose` locales funcionando igual que antes.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
