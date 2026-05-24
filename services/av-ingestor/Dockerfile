FROM python:3.12-slim
WORKDIR /app
ENV PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org"
RUN sed -i 's/MinProtocol = TLSv1.2/MinProtocol = TLSv1.2\nMaxProtocol = TLSv1.2/' /etc/ssl/openssl.cnf
COPY shared/ /shared/
RUN pip install --no-cache-dir /shared/
COPY services/av-ingestor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/av-ingestor/app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
