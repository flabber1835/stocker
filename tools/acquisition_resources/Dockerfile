# Test dependencies are supplied by the caller's already built local test image.
# This image is a qualification tool and cannot grant production image identity.
ARG TEST_IMAGE=sentinel-test:ci
FROM ${TEST_IMAGE}
COPY sentinel /qualification/sentinel
COPY shared /qualification/shared
COPY scripts /qualification/scripts
COPY tools/acquisition_resources /qualification/tools/acquisition_resources
WORKDIR /qualification
ENV PYTHONPATH=/qualification:/qualification/shared:/qualification/scripts
ENV SENTINEL_REPO_ROOT=/qualification
ENTRYPOINT ["python"]
