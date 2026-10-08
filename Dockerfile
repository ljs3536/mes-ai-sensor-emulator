FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul \
    DATABASE_PATH=/data/emulator.db

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY emulator ./emulator

RUN useradd --uid 10001 --no-create-home app && mkdir -p /data && chown app:app /data
USER app

EXPOSE 8002
CMD ["uvicorn", "emulator.main:app", "--host", "0.0.0.0", "--port", "8002", "--proxy-headers"]
