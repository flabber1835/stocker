FROM python:3.12-slim
WORKDIR /app
ENV PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org"
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY services/dashboard/app ./app
COPY services/dashboard/static ./static
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
