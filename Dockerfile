FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV GARY_FINANCE_FILE=/data/finance_data/profile.json
ENV GARY_CONTENT_FILE=/data/finance_data/content.json
ENV GARY_PREVIEW_CACHE=/data/gary_previews

RUN mkdir -p /data/finance_data /data/gary_previews

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["bash", "scripts/start-prod.sh"]
