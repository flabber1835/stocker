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
}
