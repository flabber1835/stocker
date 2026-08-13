FROM stocker-base:latest
ARG SOURCE_GIT_SHA=unknown
LABEL org.opencontainers.image.revision=${SOURCE_GIT_SHA}
WORKDIR /app
COPY services/bt-engine/requirements.txt services/bt-engine/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: \
    -r requirements.lock
COPY services/bt-engine/app/ ./app/
# Reuse the LIVE chain's math by copying the REAL source files next to the loader
# (app/live/__init__.py). Same files as production — zero drift, no vendoring.
# The Sharadar column-to-domain mapping for Wealth Core, from the ONE module
# that owns it. A second reader of the same corpus with its own opinion about
# which column means what is the failure the factor-coverage contract exists
# after — two engines that agree until they quietly do not.
COPY services/backtester/app/wealth_core_replay.py ./app/live/
# The benchmark series. Its own module because the loader above is guarded
# against ever naming the total-return column — see wealth_core_benchmark.py.
COPY services/backtester/app/wealth_core_benchmark.py ./app/live/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
