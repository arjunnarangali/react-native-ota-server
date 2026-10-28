FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && groupadd --system --gid 10001 ota \
    && useradd --system --uid 10001 --gid ota --home-dir /app ota \
    && mkdir -p /app/storage/releases \
    && chown -R ota:ota /app

COPY --chown=ota:ota app/ /app/app/
COPY --chown=ota:ota migrations/ /app/migrations/
COPY --chown=ota:ota alembic.ini /app/alembic.ini

WORKDIR /app
USER ota

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
