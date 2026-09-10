#!/usr/bin/env bash
# Resolve the Stage-4 automation overlay only with immutable deployment facts.
# This script does not activate automation and grants no broker authority.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance --automation-args "$@"

# Keep the Compose graph that was classified and validated above authoritative.
# Explicit alternate env/files can replace interpolation or service definitions
# after preflight; additional profiles can start services outside automation.
sentinel_require_validated_compose_graph() {
  local -a forwarded=("$@")
  local index=0
  local argument profile

  [ -z "${COMPOSE_PROFILES:-}" ] || {
    echo "REFUSED: automation Compose profiles must come from the validated wrapper" >&2
    return 2
  }

  while [ "$index" -lt "${#forwarded[@]}" ]; do
    argument="${forwarded[$index]}"
    case "$argument" in
      --)
        break
        ;;
      --env-file|--file|-f)
        echo "REFUSED: automation Compose file/env overrides are not allowed" >&2
        return 2
        ;;
      --env-file=*|--file=*|-f?*)
        echo "REFUSED: automation Compose file/env overrides are not allowed" >&2
        return 2
        ;;
      --profile)
        index=$((index + 1))
        if [ "$index" -ge "${#forwarded[@]}" ]; then
          echo "REFUSED: automation Compose profile requires the fixed automation value" >&2
          return 2
        fi
        profile="${forwarded[$index]}"
        [ "$profile" = "automation" ] || {
          echo "REFUSED: automation Compose profile requires the fixed automation value" >&2
          return 2
        }
        ;;
      --profile=*)
        profile="${argument#--profile=}"
        [ "$profile" = "automation" ] || {
          echo "REFUSED: automation Compose profile requires the fixed automation value" >&2
          return 2
        }
        ;;
      --ansi|--parallel|--progress|--project-directory|-p|--project-name)
        # These documented global options consume one following value. They do
        # not replace the env/file graph or activate an additional profile.
        index=$((index + 1))
        ;;
      --ansi=*|--parallel=*|--progress=*|--project-directory=*|--project-name=*|-p?*)
        ;;
      --all-resources|--compatibility|--dry-run|--dry-run=*|--help|--help=*|-h|--version|--version=*)
        ;;
      -*)
        # Unknown options remain fail-closed at Compose itself. Stop interpreting
        # their arity here so a value cannot be mistaken for the command.
        break
        ;;
      *)
        break
        ;;
    esac
    index=$((index + 1))
  done
}
sentinel_require_validated_compose_graph "$@"

: "${SENTINEL_RUNTIME_IMAGE_DIGEST:?set sha256 runtime image digest}"
: "${SENTINEL_TEST_IMAGE_DIGEST:?set sha256 test image digest}"
: "${SENTINEL_GIT_COMMIT:?set exact built Git commit}"

[[ "${SENTINEL_RUNTIME_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "REFUSED: SENTINEL_RUNTIME_IMAGE_DIGEST is not an immutable sha256 digest" >&2
  exit 2
}
[[ "${SENTINEL_TEST_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "REFUSED: SENTINEL_TEST_IMAGE_DIGEST is not an immutable sha256 digest" >&2
  exit 2
}
[[ "${SENTINEL_GIT_COMMIT}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || {
  echo "REFUSED: SENTINEL_GIT_COMMIT is not an exact Git object id" >&2
  exit 2
}

exec docker compose \
  -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml \
  -f docker-compose.sentinel-automation.yml \
  --profile automation "$@"
