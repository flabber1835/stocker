#!/usr/bin/env bash
# Read-only restore-horizon proof executed as the PostgreSQL OS identity.
set -euo pipefail

refuse() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 4
}

[ "$#" -eq 5 ] || refuse "expected BASE_NAME WAL_NAMESPACE SYSTEM_ID LAST_WAL WAL_BYTES"
name="$1"
namespace="$2"
system_id="$3"
last_wal="$4"
wal_bytes="$5"
base="/sentinel-backup/base/$name"
wal_root="/sentinel-backup/wal/$namespace"

[[ "$name" =~ ^base-[0-9]{8}T[0-9]{6}Z$ ]] || refuse "base backup name is malformed"
[[ "$namespace" == "cluster-$system_id" ]] || refuse "WAL namespace does not match system identifier"
[[ "$system_id" =~ ^[0-9]+$ ]] || refuse "PostgreSQL system identifier is malformed"
[[ "$last_wal" =~ ^[0-9A-F]{24}$ ]] || refuse "last archived WAL name is malformed"
[[ "$wal_bytes" =~ ^[0-9]+$ ]] && [ "$wal_bytes" -gt 0 ] || refuse "WAL segment size is malformed"
[ $((4294967296 % wal_bytes)) -eq 0 ] || refuse "WAL segment size does not divide one PostgreSQL log id"
segments_per_log=$((4294967296 / wal_bytes))

[ -d "$base" ] && [ ! -L "$base" ] || refuse "base backup directory is missing or aliased"
[ -d "$wal_root" ] && [ ! -L "$wal_root" ] || refuse "WAL namespace is missing or aliased"
for metadata in backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity; do
  path="$base/$metadata"
  [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ] || \
    refuse "base backup metadata is missing, unreadable, or aliased: $metadata"
done

identity_id="$(sed -n 's/^system_identifier=//p' "$base/sentinel-pitr-base-identity")"
[ "$identity_id" = "$system_id" ] || refuse "base backup identity belongs to another PostgreSQL cluster"
marker="$base/sentinel-recovery-marker"
[ "$(wc -l < "$marker")" -eq 4 ] || refuse "recovery marker field count is invalid"
[ "$(grep -Ec '^marker=sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+$' "$marker")" -eq 1 ] || \
  refuse "recovery marker identity is malformed"
[ "$(grep -Ec '^lsn=[0-9A-F]{1,8}/[0-9A-F]{1,8}$' "$marker")" -eq 1 ] || \
  refuse "recovery marker LSN is malformed"
[ "$(grep -Ec '^wal=[0-9A-F]{24}$' "$marker")" -eq 1 ] || \
  refuse "recovery marker WAL is malformed"
[ "$(grep -Ec '^system_identifier=[0-9]+$' "$marker")" -eq 1 ] || \
  refuse "recovery marker system identifier is malformed"
marker_id="$(sed -n 's/^system_identifier=//p' "$marker")"
[ "$marker_id" = "$system_id" ] || refuse "recovery marker belongs to another PostgreSQL cluster"
marker_wal="$(sed -n 's/^wal=//p' "$marker")"

# Let PostgreSQL parse its own JSON manifest. This is a read-only server-side
# file read under the same OS authority the runtime checker uses.
manifest_sql="SELECT (j->'WAL-Ranges'->-1->>'Timeline') || '|' || (j->'WAL-Ranges'->-1->>'End-LSN') FROM (SELECT pg_read_file('$base/backup_manifest')::jsonb AS j) AS m"
manifest_range="$(psql -U sentinel -d sentinel -Atq -v ON_ERROR_STOP=1 -c "$manifest_sql")" || \
  refuse "base backup manifest cannot establish its final WAL range"
IFS='|' read -r start_timeline start_lsn <<EOF
$manifest_range
EOF
[[ "$start_timeline" =~ ^[0-9]+$ ]] || refuse "base backup manifest timeline is malformed"
[ "$start_timeline" -ge 1 ] && [ "$start_timeline" -le 4294967295 ] || \
  refuse "base backup manifest timeline is outside WAL bounds"
[[ "$start_lsn" =~ ^[0-9A-Fa-f]{1,8}/[0-9A-Fa-f]{1,8}$ ]] || \
  refuse "base backup manifest End-LSN is malformed"
start_high="${start_lsn%/*}"
start_low="${start_lsn#*/}"
start_log=$((16#$start_high))
start_offset=$((16#$start_low))
start_segment=$((start_offset / wal_bytes))

last_timeline_hex="${last_wal:0:8}"
last_log_hex="${last_wal:8:8}"
last_segment_hex="${last_wal:16:8}"
last_timeline=$((16#$last_timeline_hex))
last_log=$((16#$last_log_hex))
last_segment=$((16#$last_segment_hex))
[ "$last_segment" -lt "$segments_per_log" ] || refuse "last WAL segment is outside configured geometry"
[ "$start_timeline" -eq "$last_timeline" ] || \
  refuse "base backup and current archive are on different timelines"
first_index=$((start_log * segments_per_log + start_segment))
last_index=$((last_log * segments_per_log + last_segment))
[ "$last_index" -ge "$first_index" ] || refuse "archived WAL frontier precedes base recovery horizon"
[ $((last_index - first_index)) -le 1000000 ] || refuse "backup WAL chain exceeds reviewed bound"

marker_seen=0
count=0
index="$first_index"
while [ "$index" -le "$last_index" ]; do
  log=$((index / segments_per_log))
  segment=$((index % segments_per_log))
  printf -v wal '%08X%08X%08X' "$start_timeline" "$log" "$segment"
  path="$wal_root/$wal"
  sidecar="$path.sha256"
  [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ] || \
    refuse "archived WAL is missing, unreadable, or aliased: $wal"
  [ "$(stat -c %s "$path")" -eq "$wal_bytes" ] || refuse "archived WAL is truncated: $wal"
  [ -f "$sidecar" ] && [ ! -L "$sidecar" ] && [ -r "$sidecar" ] || \
    refuse "archived WAL SHA-256 sidecar is missing, unreadable, or aliased: $wal"
  [ "$(wc -l < "$sidecar")" -eq 1 ] || refuse "archived WAL SHA-256 sidecar has invalid field count: $wal"
  checksum="$(sed -n 's/^sha256=//p' "$sidecar")"
  [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || refuse "archived WAL SHA-256 sidecar is malformed: $wal"
  observed="$(sha256sum -- "$path")" || refuse "archived WAL could not be hashed: $wal"
  observed="${observed%% *}"
  [ "$observed" = "$checksum" ] || refuse "archived WAL failed SHA-256 integrity validation: $wal"
  if [ "$wal" = "$marker_wal" ]; then marker_seen=1; fi
  count=$((count + 1))
  index=$((index + 1))
done
[ "$marker_seen" -eq 1 ] || refuse "recovery marker WAL is outside the retained restore chain"
printf 'wal_chain_ready:true start_index=%s end=%s segments=%s marker=%s\n' \
  "$first_index" "$last_wal" "$count" "$marker_wal"
