#!/usr/bin/env bash
# Private, literal ingestion bridge. Call after selecting the host interpreter.
sentinel_load_environment() {
  local record
  local -a records=()
  while IFS= read -r -d '' record; do
    records+=("$record")
  done < <("$PYTHON" scripts/sentinel_env.py --records "$@")
  if [ "${#records[@]}" -eq 0 ] || \
     [ "${records[${#records[@]}-1]}" != SENTINEL_ENV_COMPLETE_V1 ]; then
    echo "REFUSED: environment preflight did not complete" >&2
    return 2
  fi
  unset 'records[${#records[@]}-1]'
  for record in "${records[@]}"; do
    export "$record" || return 2
  done

  # Bind every supported launcher to one local Docker/Compose authority before
  # any Docker operation. The checker sees the original process controls first;
  # only a clean observation is normalized to the canonical local context.
  "$PYTHON" scripts/sentinel_execution_envelope.py environment || return $?
  unset DOCKER_HOST DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY DOCKER_TLS \
    DOCKER_API_VERSION DOCKER_DEFAULT_PLATFORM BUILDKIT_HOST BUILDX_BUILDER
  unset COMPOSE_FILE COMPOSE_PATH_SEPARATOR COMPOSE_PROJECT_NAME COMPOSE_PROFILES
  export DOCKER_CONTEXT=default
  export COMPOSE_DISABLE_ENV_FILE=1
  export COMPOSE_ENV_FILES=/dev/null
}
