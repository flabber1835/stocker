FROM python:3.12-slim

WORKDIR /app

ENV PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org"
RUN sed -i 's/MinProtocol = TLSv1.2/MinProtocol = TLSv1.2\nMaxProtocol = TLSv1.2/' /etc/ssl/openssl.cnf

# Pin versions so a new release can't silently break a NAS rebuild.
RUN pip install --no-cache-dir "alembic==1.13.3" "psycopg2-binary==2.9.10"

COPY db/migrations /app/db/migrations
COPY alembic.ini /app/alembic.ini
COPY services/db-migrator/migrate.sh /app/migrate.sh
RUN chmod +x /app/migrate.sh

CMD ["/app/migrate.sh"]
