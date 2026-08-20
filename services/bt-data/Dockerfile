# Self-contained image — the backtest stack runs on a SEPARATE machine that does
# not have the live stocker-base image. No live-stack dependency.
FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
ARG SOURCE_GIT_SHA=unknown
LABEL org.opencontainers.image.revision=${SOURCE_GIT_SHA}
WORKDIR /app
COPY services/bt-data/requirements.txt services/bt-data/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: \
    -r requirements.lock
COPY services/bt-data/app/ ./app/
COPY services/bt-data/sql/ ./sql/
# Keep the historical init file stable while making the post-#185 semantic epoch
# part of the exact runtime schema bootstrap. Every database starts unproven;
# only the explicit volume-domain migration may establish certification authority.
RUN cat ./sql/volume_domain_guard.sql >> ./sql/init_bt.sql
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
