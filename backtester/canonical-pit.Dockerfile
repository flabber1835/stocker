FROM scratch
ARG SOURCE_REPOSITORY
ARG DATASET_HASH
LABEL org.opencontainers.image.source=$SOURCE_REPOSITORY
LABEL org.opencontainers.image.title="Stocker canonical strict-PIT dataset"
LABEL io.stocker.canonical-pit.dataset-hash=$DATASET_HASH
COPY . /canonical-pit
