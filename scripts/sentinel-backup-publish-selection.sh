#!/bin/sh
# Root-owned selection hint, after the caller verifies and promotes its base.
set -eu
refuse() { echo "REFUSED: backup selection: $*" >&2; exit 4; }
[ "$(id -u)" = 0 ] || refuse "container root is required"
[ "$#" = 3 ] || refuse "expected BASE_ROOT SYSTEM_ID BASE_NAME"
root="$1" system_id="$2" name="$3"
case "$root" in /*) ;; *) refuse "base root must be absolute";; esac
[ "$root" != / ] && [ -d "$root" ] && [ ! -L "$root" ] || refuse "invalid base root"
printf '%s\n' "$system_id" | grep -Eq '^[1-9][0-9]{0,19}$' || refuse "invalid cluster identity"
printf '%s\n' "$name" | grep -Eq '^base-[0-9]{8}T[0-9]{6}Z$' || refuse "invalid final name"
[ -d "$root/$name" ] && [ ! -L "$root/$name" ] || refuse "promoted base is absent"
for field in backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity; do
  path="$root/$name/$field"
  [ -f "$path" ] && [ ! -L "$path" ] && [ "$(stat -c %h "$path")" = 1 ] ||
    refuse "promoted metadata is absent or aliased"
done
gid="$(id -g postgres)"
case "$gid" in ''|*[!0-9]*) refuse "postgres group is unavailable";; esac
selection="$root/.sentinel-runtime-base-$system_id-v1"
umask 077
temporary="$(mktemp "$root/.sentinel-runtime-base-$system_id.part-XXXXXXXX")"
trap 'rm -f -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
printf 'schema=sentinel.runtime-base/1\nsystem_identifier=%s\nbase_backup=%s\n' \
  "$system_id" "$name" > "$temporary"
chown "0:$gid" "$temporary"
chmod 0640 "$temporary"
sync "$temporary"
mv -T -- "$temporary" "$selection"
sync -f "$root"
