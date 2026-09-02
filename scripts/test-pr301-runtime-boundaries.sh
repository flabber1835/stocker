#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUNTIME_IMAGE="${1:-sentinel-authorized:ci}"
HELPER_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

work="$(mktemp -d)"
volume="sentinel-pr301-state-${RANDOM}-$$"
project="sentinel-pr301-authority-${RANDOM}-$$"
cleanup() {
  docker compose -p "$project" -f "$work/compose.yml" down -v \
    >/dev/null 2>&1 || true
  docker volume rm -f "$volume" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

# Reproduce a hardened host: both the authority root and deployment attempt are
# created under umask 077. This is the exact case that previously made the
# fixed uid/gid runtime unable to traverse to a signed certificate.
umask 077
authority="$work/authority"
attempt="$authority/deployments/attempt"
mkdir -p "$attempt"
printf '%s\n' '{"schema":"sentinel.test-public-certificate/1"}' \
  > "$attempt/paper-observation-certificate.json"
chmod 0700 "$authority" "$authority/deployments" "$attempt"
chmod 0600 "$attempt/paper-observation-certificate.json"

# Exercise the same narrow helper policy as production Compose. Directory
# listings and non-certificate files remain private; only traversal plus public
# signed-certificate reads are opened to the non-root runtime.
docker run --rm --network none --user 0:0 \
  --cap-drop ALL --cap-add DAC_OVERRIDE --cap-add FOWNER \
  --security-opt no-new-privileges:true \
  --mount "type=bind,src=$authority,dst=/authority" \
  --entrypoint sh "$HELPER_IMAGE" -ceu '
    find /authority -type d -exec chmod 0711 {} +
    find /authority -type f -name "*-certificate.json" -exec chmod 0644 {} +
  '

test "$(stat -c %a "$authority")" = 711
test "$(stat -c %a "$attempt")" = 711
test "$(stat -c %a "$attempt/paper-observation-certificate.json")" = 644

# Prove Compose re-runs a completed permission dependency for every one-shot
# authorized CLI invocation. The second certificate is created only after the
# first reader has completed and is deliberately reset to mode 0600.
cat > "$work/compose.yml" <<EOF
services:
  permissions:
    image: $HELPER_IMAGE
    network_mode: none
    user: "0:0"
    cap_drop: ["ALL"]
    cap_add: ["DAC_OVERRIDE", "FOWNER"]
    security_opt: ["no-new-privileges:true"]
    entrypoint: ["sh", "-ceu"]
    command:
      - |
        find /authority -type d -exec chmod 0711 {} +
        find /authority -type f -name '*-certificate.json' -exec chmod 0644 {} +
    volumes:
      - type: bind
        source: $authority
        target: /authority
  reader:
    image: $RUNTIME_IMAGE
    network_mode: none
    user: "10001:10001"
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    entrypoint: ["sh", "-ceu"]
    command: ["test -r /authority/deployments/attempt/paper-observation-certificate.json"]
    volumes:
      - type: bind
        source: $authority
        target: /authority
        read_only: true
    depends_on:
      permissions:
        condition: service_completed_successfully
EOF

docker compose -p "$project" -f "$work/compose.yml" run --rm reader
printf '%s\n' '{"schema":"sentinel.test-public-certificate/2"}' \
  > "$attempt/next-certificate.json"
chmod 0600 "$attempt/next-certificate.json"
test "$(stat -c %a "$attempt/next-certificate.json")" = 600

docker compose -p "$project" -f "$work/compose.yml" run --rm \
  --entrypoint sh reader -ceu '
    test -r /authority/deployments/attempt/next-certificate.json
    grep -q sentinel.test-public-certificate/2 \
      /authority/deployments/attempt/next-certificate.json
  '
test "$(stat -c %a "$attempt/next-certificate.json")" = 644

docker volume create "$volume" >/dev/null
docker run --rm --network none --user 0:0 \
  --mount "type=volume,src=$volume,dst=/state" \
  --entrypoint sh "$HELPER_IMAGE" -ceu '
    chown -R 10001:10001 /state
    test "$(stat -c %u /state)" = 10001
    test "$(stat -c %g /state)" = 10001
  '

# Exercise the actual deployable image under the production kernel boundary.
# It must read the signed authority artifact and write its state volume as the
# fixed uid/gid with zero Linux capabilities and no-new-privileges.
docker run --rm --network none --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --mount "type=bind,src=$authority,dst=/var/lib/sentinel-authority,readonly" \
  --mount "type=volume,src=$volume,dst=/var/lib/sentinel" \
  --entrypoint sh "$RUNTIME_IMAGE" -ceu '
    test "$(id -u)" = 10001
    test "$(id -g)" = 10001
    test -r /var/lib/sentinel-authority/deployments/attempt/paper-observation-certificate.json
    grep -q sentinel.test-public-certificate \
      /var/lib/sentinel-authority/deployments/attempt/paper-observation-certificate.json
    printf runtime-smoke > /var/lib/sentinel/runtime-smoke
    test -s /var/lib/sentinel/runtime-smoke
  '

# Exercise the strict recovered-order ownership rule through the same fresh
# process/environment activation path used by the authorized Compose services.
# This proves the package import actually replaces the historical adopter and
# that a bare sntl- prefix cannot create durable production ownership authority.
docker run --rm --network none --user 10001:10001 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  -e SENTINEL_RECOVERED_ORDER_AUTHORITY=STRICT_V1 \
  --entrypoint python "$RUNTIME_IMAGE" -c '
from types import SimpleNamespace
from sentinel.execution import journal
from sentinel.execution import recovered_order_policy as policy
assert journal.adopt_recovered_order is policy.refuse_unauthenticated_recovered_order
order = SimpleNamespace(
    client_key="sntl-prefix-only",
    instrument=SimpleNamespace(security_id="SEC:AMBIGUOUS"),
)
try:
    journal.adopt_recovered_order(None, order, deployment=None)
except journal.RecoveredOrderConflict as exc:
    assert "prefix" in str(exc)
else:
    raise SystemExit("strict recovered-order policy did not fail closed")
print("PR301_STRICT_RECOVERED_ORDER_PASS")
  '

# Exercise the actual ordinary production image and Compose database contract
# from a cold/stopped PostgreSQL state. This covers the preflight seam that the
# unit suite cannot reproduce: UID 10001, Compose DNS, authentication, health,
# import failure, and the typed child marker protocol all run in real containers.
python3 scripts/test_go_probe_runtime_integration.py sentinel:latest

printf '%s\n' 'PR301_RUNTIME_BOUNDARY_PASS'
