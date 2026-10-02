ARG TEST_IMAGE=sentinel-test:acquisition-data-local
FROM ${TEST_IMAGE}
COPY sentinel /qualification/sentinel
COPY shared /qualification/shared
COPY scripts /qualification/scripts
COPY tools /qualification/tools
COPY tests /qualification/tests
COPY docs /qualification/docs
COPY data/sharadar /qualification/data/sharadar
COPY config /qualification/config
WORKDIR /qualification
ENV PYTHONPATH=/qualification:/qualification/shared:/qualification/scripts
ENV SENTINEL_REPO_ROOT=/qualification
ENTRYPOINT ["python"]
