FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir alembic psycopg2-binary

COPY db/migrations /app/db/migrations
COPY alembic.ini /app/alembic.ini

CMD ["alembic", "upgrade", "head"]
