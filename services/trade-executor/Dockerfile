FROM stocker-base:latest
WORKDIR /app
COPY services/trade-executor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/trade-executor/app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
