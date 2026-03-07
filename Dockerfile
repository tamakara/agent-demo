FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=80

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

# Runtime data (SQLite + memory files) lives under /app/data.
RUN mkdir -p /app/data && chown -R app:app /app

USER app

EXPOSE 80
VOLUME ["/app/data"]

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
