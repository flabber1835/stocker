# Self-contained image — the backtest stack runs on a SEPARATE machine that does
# not have the live stocker-base image. No live-stack dependency.
FROM python:3.12-slim
WORKDIR /app
COPY services/bt-data/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/bt-data/app/ ./app/
COPY services/bt-data/sql/ ./sql/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
