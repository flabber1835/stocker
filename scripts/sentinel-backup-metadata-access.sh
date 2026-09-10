#!/bin/sh
# Container-root provisioning of the PostgreSQL metadata reader's exact grant.
set -eu
refuse() { echo "REFUSED: backup metadata access: $*" >&2; exit 4; }
[ "$(id -u)" = 0 ] || refuse "container root is required"
[ "$#" -ge 1 ] && [ "$#" -le 2 ] || refuse "expected BASE_ROOT [STAGING_NAME]"
root="$1"
case "$root" in /*) ;; *) refuse "base root must be absolute";; esac
[ "$root" != / ] || refuse "base root cannot be /"
private_directory() {
  [ -d "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u "$1")" = 0 ] ||
    refuse "expected root-owned regular directory: $1"
}
[ -d "$root" ] && [ ! -L "$root" ] || refuse "expected regular base root"
gid="$(id -g postgres)"
case "$gid" in ''|*[!0-9]*) refuse "postgres group is unavailable";; esac
fields='backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity'
if [ "$#" = 2 ]; then
  printf '%s\n' "$2" | grep -Eq '^\.base-[0-9]{8}T[0-9]{6}Z\.part-[0-9]+$' ||
    refuse "invalid staging name"
  set -- "$root/$2"
  exact=1
else
  set -- "$root"/base-*
  exact=0
fi
# Validate all selected paths before applying a grant. Existing incomplete
# generations also need traversal so missing_ok reads can skip them safely.
for base do
  if [ "$exact" = 0 ]; then
    printf '%s\n' "${base##*/}" | grep -Eq '^base-[0-9]{8}T[0-9]{6}Z$' || continue
  fi
  private_directory "$base"
  for name in $fields; do
    path="$base/$name"
    if [ "$exact" = 0 ] && [ ! -e "$path" ] && [ ! -L "$path" ]; then continue; fi
    [ -f "$path" ] && [ ! -L "$path" ] &&
      [ "$(stat -c %u "$path")" = 0 ] && [ "$(stat -c %h "$path")" = 1 ] ||
      refuse "expected single-link root-owned metadata: $path"
  done
done
for base do
  if [ "$exact" = 0 ]; then
    printf '%s\n' "${base##*/}" | grep -Eq '^base-[0-9]{8}T[0-9]{6}Z$' || continue
  fi
  for name in $fields; do
    path="$base/$name"
    [ -f "$path" ] || continue
    chown "0:$gid" "$path"
    chmod 0640 "$path"
    sync "$path"
  done
  chown "0:$gid" "$base"
  chmod 0710 "$base"
  sync "$base"
done
chown "0:$gid" "$root"
chmod 0750 "$root"
sync "$root"
