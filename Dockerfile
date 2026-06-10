FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# wait for postgres, run migrations, then start the API
CMD ["sh", "-c", "until pg_isready -h ${PGHOST:-postgres} -U amc; do echo 'waiting for postgres...'; sleep 1; done && alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
