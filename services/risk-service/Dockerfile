FROM python:3.12-slim
WORKDIR /app
COPY shared/ /shared/
RUN pip install --no-cache-dir /shared/
COPY services/risk-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/risk-service/app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
