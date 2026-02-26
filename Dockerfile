FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg, cryptography (passlib bcrypt), and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

ENV PYTHONPATH=/app

EXPOSE 8050

# Dispatch via PROCESS_TYPE env var: "web" (default) or "worker"
CMD ["./entrypoint.sh"]
