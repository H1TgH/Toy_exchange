FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini .

RUN mkdir -p /app/src/logs && chmod -R 777 /app/src/logs

ENV PORT=8000

CMD sh -c 'alembic upgrade head && gunicorn -w 4 -k uvicorn.workers.UvicornWorker src.main:app --bind 0.0.0.0:$PORT'