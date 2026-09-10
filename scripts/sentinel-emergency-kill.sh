#!/usr/bin/env bash
# Minimal risk-reducing automation fence. This path deliberately bypasses the
# normal runtime, backup and Compose preflights. It never contacts a broker.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"

"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

ACTOR="manual"
REASON="manual emergency kill"
SEEN_ACTOR=0
SEEN_REASON=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --actor)
      [ "$SEEN_ACTOR" -eq 0 ] && [ "$#" -ge 2 ] || {
        echo "REFUSED: --actor requires one unique value" >&2; exit 2; }
      ACTOR="$2"; SEEN_ACTOR=1; shift 2 ;;
    --actor=*)
      [ "$SEEN_ACTOR" -eq 0 ] || {
        echo "REFUSED: --actor may be supplied only once" >&2; exit 2; }
      ACTOR="${1#--actor=}"; SEEN_ACTOR=1; shift ;;
    --reason)
      [ "$SEEN_REASON" -eq 0 ] && [ "$#" -ge 2 ] || {
        echo "REFUSED: --reason requires one unique value" >&2; exit 2; }
      REASON="$2"; SEEN_REASON=1; shift 2 ;;
    --reason=*)
      [ "$SEEN_REASON" -eq 0 ] || {
        echo "REFUSED: --reason may be supplied only once" >&2; exit 2; }
      REASON="${1#--reason=}"; SEEN_REASON=1; shift ;;
    *)
      echo "REFUSED: usage: sentinel-emergency-kill.sh [--actor VALUE] [--reason VALUE]" >&2
      exit 2 ;;
  esac
done

"$PYTHON" - "$ACTOR" "$REASON" <<'PY'
import sys
for value, label in ((sys.argv[1], "actor"), (sys.argv[2], "reason")):
    if not value.strip():
        print("REFUSED: emergency kill %s must be non-empty" % label, file=sys.stderr)
        raise SystemExit(2)
    if "\x00" in value:
        print("REFUSED: emergency kill %s contains NUL" % label, file=sys.stderr)
        raise SystemExit(2)
PY

# Emergency fencing must survive broken .env/Compose/runtime state. Pin the
# local engine explicitly and remove ambient daemon selectors before discovery.
unset DOCKER_HOST DOCKER_CONFIG DOCKER_CERT_PATH DOCKER_TLS_VERIFY DOCKER_TLS \
  DOCKER_API_VERSION DOCKER_DEFAULT_PLATFORM BUILDKIT_HOST BUILDX_BUILDER
export DOCKER_CONTEXT=default

mapfile -t POSTGRES_IDS < <(
  docker --context default ps -q \
    --filter label=com.docker.compose.project=sentinel \
    --filter label=com.docker.compose.service=sentinel-postgres
)
[ "${#POSTGRES_IDS[@]}" -eq 1 ] && [ -n "${POSTGRES_IDS[0]}" ] || {
  echo "REFUSED: canonical running Sentinel PostgreSQL container is not unique" >&2
  exit 3
}
POSTGRES_ID="${POSTGRES_IDS[0]}"

# Reproduce the durable automation-store fencing transaction directly in the
# canonical database. It is idempotent: an already-engaged kill remains a PASS,
# while the lease is still invalidated. Missing singleton rows abort atomically.
SQL=$(cat <<'SQL'
BEGIN;
DO $$
BEGIN
  PERFORM 1 FROM sentinel_automation_control WHERE id=1 FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'durable automation control singleton is missing';
  END IF;
  PERFORM 1 FROM sentinel_automation_lease WHERE id=1 FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'durable automation lease singleton is missing';
  END IF;
END $$;
WITH changed AS (
  UPDATE sentinel_automation_control
     SET generation=generation+1,
         kill_switch_engaged=TRUE,
         authority_verdict=NULL,
         authority_detail=NULL,
         authority_checked_at=NULL,
         updated_at=clock_timestamp()
   WHERE id=1 AND NOT kill_switch_engaged
   RETURNING generation
), params AS (
  SELECT :'actor'::text AS actor, :'reason'::text AS reason
)
INSERT INTO sentinel_automation_events
       (generation,action,actor,reason,detail)
SELECT generation,'KILL_ENGAGED',params.actor,params.reason,'{}'::jsonb
  FROM changed CROSS JOIN params;
UPDATE sentinel_automation_lease
   SET holder_id=NULL,
       control_generation=NULL,
       acquired_at=NULL,
       heartbeat_at=NULL,
       expires_at=NULL,
       updated_at=clock_timestamp()
 WHERE id=1;
COMMIT;
SELECT CASE WHEN kill_switch_engaged
            THEN 'automation_kill_engaged:true generation=' || generation::text
            ELSE 'automation_kill_engaged:false'
       END
  FROM sentinel_automation_control WHERE id=1;
SQL
)

printf '%s\n' "$SQL" | docker --context default exec -i "$POSTGRES_ID" \
  psql -X -v ON_ERROR_STOP=1 -v actor="$ACTOR" -v reason="$REASON" \
  -U sentinel -d sentinel -At
