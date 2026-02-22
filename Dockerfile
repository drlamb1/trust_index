FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, cryptography (passlib bcrypt), and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8050

# Default: run web server. Railway injects $PORT; fall back to 8050 for local Docker.
CMD uvicorn api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8050}
