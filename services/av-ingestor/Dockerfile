FROM stocker-base:latest
WORKDIR /app
COPY services/av-ingestor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/av-ingestor/app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
