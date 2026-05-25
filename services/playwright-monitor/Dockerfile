FROM python:3.12-slim

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    libasound2 libxss1 libgtk-3-0 libx11-xcb1 libdrm2 libxkbcommon0 \
    fonts-liberation libappindicator3-1 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium \
    && playwright install-deps chromium

COPY monitor.py .

ENV ARTIFACTS_DIR=/artifacts
ENV DASHBOARD_URL=http://dashboard:8000
ENV MONITOR_TIMEOUT_MINS=90
ENV POLL_SECS=2.0

ENTRYPOINT ["python", "monitor.py"]
