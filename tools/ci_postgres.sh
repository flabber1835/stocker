#!/usr/bin/env bash
# CI dependency setup only: verify existing tools before using package mirrors.
set -euo pipefail

postgres_tools_ready() {
  local pg_bin tool
  pg_bin="$(pg_config --bindir 2>/dev/null)" || return 1
  test -n "$pg_bin" || return 1
  for tool in postgres initdb pg_ctl pg_basebackup pg_verifybackup pg_controldata \
              pg_dump pg_restore psql createdb dropdb; do
    test -x "$pg_bin/$tool" || return 1
    "$pg_bin/$tool" --version || return 1
  done
}

if ! postgres_tools_ready; then
  apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=30 \
               -o Acquire::https::Timeout=30 -o APT::Update::Error-Mode=any)
  sudo apt-get "${apt_options[@]}" update
  sudo apt-get "${apt_options[@]}" install -y postgresql
  postgres_tools_ready || {
    echo 'REFUSED: CI PostgreSQL toolchain remains incomplete after installation' >&2
    exit 1
  }
fi

echo 'CI PostgreSQL toolchain verified; no database or deployment service started'
