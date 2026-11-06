#!/usr/bin/env bash
set -Eeuo pipefail

# Start PostgreSQL first so TDE can provision keys and migrate existing tables.
# WAL encryption is restart-only, so prepare the cluster before any migration
# or application service can connect.
compose_args=("$@")
dc() { docker compose "${compose_args[@]}" "$@"; }

dc config --quiet
dc up --detach postgres-data-init
dc up --detach db

db_container="$(dc ps --all --quiet db | head -n 1)"
[[ -n "$db_container" ]] || { echo "PostgreSQL container was not created" >&2; exit 1; }
for attempt in $(seq 1 90); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "$db_container" 2>/dev/null || true)"
  [[ "$health" == healthy ]] && break
  [[ "$health" != unhealthy && "$attempt" -lt 90 ]] || { dc ps --all; dc logs --no-color db; echo "PostgreSQL did not become healthy" >&2; exit 1; }
  sleep 2
done

dc run --build --rm --no-deps tde-setup --prepare

wal_setting="$(dc exec --no-TTY db psql --no-psqlrc --tuples-only --no-align -U "${POSTGRES_USER:-sps_app}" -d "${POSTGRES_DB:-sps_dashboard}" --command 'SHOW pg_tde.wal_encrypt' | tr '[:upper:]' '[:lower:]')"
if [[ "$wal_setting" != on && "$wal_setting" != true && "$wal_setting" != 1 ]]; then
  dc restart db
  for attempt in $(seq 1 90); do
    health="$(docker inspect --format '{{.State.Health.Status}}' "$db_container" 2>/dev/null || true)"
    [[ "$health" == healthy ]] && break
    [[ "$health" != unhealthy && "$attempt" -lt 90 ]] || { dc ps --all; dc logs --no-color db; echo "PostgreSQL did not become healthy after enabling WAL encryption" >&2; exit 1; }
    sleep 2
  done
fi

wal_setting="$(dc exec --no-TTY db psql --no-psqlrc --tuples-only --no-align -U "${POSTGRES_USER:-sps_app}" -d "${POSTGRES_DB:-sps_dashboard}" --command 'SHOW pg_tde.wal_encrypt' | tr '[:upper:]' '[:lower:]')"
[[ "$wal_setting" == on || "$wal_setting" == true || "$wal_setting" == 1 ]] || { echo "PostgreSQL WAL encryption is not enabled" >&2; exit 1; }

dc up --detach --build --remove-orphans
