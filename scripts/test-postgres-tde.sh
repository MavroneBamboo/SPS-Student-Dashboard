#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$script_dir"
suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$(openssl rand -hex 4)"
project="${SPS_TDE_TEST_PROJECT:-sps-postgres-tde-ci-$suffix}"
if [[ ! "$project" =~ ^sps-postgres-tde-ci-[a-z0-9-]+$ ]]; then
  echo "Refusing to clean up unexpected Compose project name: $project" >&2
  exit 2
fi

compose=(docker compose --project-name "$project" --file docker-compose.yml --file docker-compose.tde-test.yml)
seed_compose=(docker compose --project-name "$project" --file docker-compose.yml --file docker-compose.tde-seed.yml)
restore_compose=(docker compose --profile maintenance --project-name "$project" --file docker-compose.yml --file docker-compose.tde-test.yml)
cleanup_compose=(docker compose --project-name "$project" --file docker-compose.yml --file docker-compose.tde-test.yml --file docker-compose.tde-seed.yml)
if [[ -n "$(docker ps --all --quiet --filter "label=com.docker.compose.project=$project")" ]] \
  || docker volume inspect "${project}_postgres-data" >/dev/null 2>&1 \
  || docker volume inspect "${project}_tde-keyring" >/dev/null 2>&1 \
  || docker network inspect "${project}_default" >/dev/null 2>&1; then
  echo "Refusing to run destructive TDE integration cleanup: Compose project resources already exist for $project" >&2
  exit 2
fi
cleanup() {
  "${cleanup_compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT

"${compose[@]}" config --quiet
"${seed_compose[@]}" config --quiet
"${seed_compose[@]}" up --detach postgres-vanilla-seed
seed_container="$("${seed_compose[@]}" ps --all --quiet postgres-vanilla-seed | head -n 1)"
for attempt in $(seq 1 60); do
  seed_health="$(docker inspect --format '{{.State.Health.Status}}' "$seed_container" 2>/dev/null || true)"
  [[ "$seed_health" == healthy ]] && break
  [[ "$seed_health" != unhealthy && "$attempt" -lt 60 ]] || { "${seed_compose[@]}" logs --no-color postgres-vanilla-seed; echo "Vanilla PostgreSQL seed did not become healthy" >&2; exit 1; }
  sleep 2
done
seed_value="$("${seed_compose[@]}" exec --no-TTY postgres-vanilla-seed psql --no-psqlrc --tuples-only --no-align -U sps_app -d sps_dashboard --command 'SELECT secret FROM public.tde_preserved_probe WHERE id = 1')"
[[ "$seed_value" == "SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a" ]]
"${seed_compose[@]}" stop postgres-vanilla-seed >/dev/null
"${seed_compose[@]}" rm --force postgres-vanilla-seed >/dev/null

if ! bash "$script_dir/scripts/compose-up.sh" --project-name "$project" --file docker-compose.yml --file docker-compose.tde-test.yml; then
  "${compose[@]}" ps --all
  "${compose[@]}" logs --no-color db tde-setup migrate
  exit 1
fi

for attempt in $(seq 1 90); do
  container="$("${compose[@]}" ps --all --quiet db | head -n 1)"
  if [[ -n "$container" ]] && docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null | grep -qx healthy; then
    break
  fi
  if [[ "$attempt" -eq 90 ]]; then
    "${compose[@]}" ps --all
    "${compose[@]}" logs --no-color db tde-setup migrate
    echo "TDE database stack did not become healthy" >&2
    exit 1
  fi
  sleep 2
done

for attempt in $(seq 1 90); do
  container="$("${compose[@]}" ps --all --quiet app | head -n 1)"
  if [[ -n "$container" ]] && docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null | grep -qx healthy; then
    break
  fi
  setup_container="$("${compose[@]}" ps --all --quiet tde-setup | head -n 1)"
  if [[ -n "$setup_container" ]] && [[ "$(docker inspect --format '{{.State.Status}}' "$setup_container")" == exited ]] && [[ "$(docker inspect --format '{{.State.ExitCode}}' "$setup_container")" != 0 ]]; then
    "${compose[@]}" logs --no-color tde-setup migrate
    exit 1
  fi
  if [[ "$attempt" -eq 90 ]]; then
    "${compose[@]}" ps --all
    "${compose[@]}" logs --no-color tde-setup migrate app
    echo "TDE application stack did not become healthy" >&2
    exit 1
  fi
  sleep 2
done

"${compose[@]}" run --build --rm --no-deps --entrypoint python tde-setup -m app.tde_setup --verify

psql=("${compose[@]}" exec --no-TTY db psql -v ON_ERROR_STOP=1 -U sps_app -d sps_dashboard)

preserved="$("${psql[@]}" --tuples-only --no-align --command "SELECT secret FROM public.tde_preserved_probe WHERE id = 1")"
[[ "$preserved" == "SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a" ]]

encrypted="$("${psql[@]}" --tuples-only --no-align --command "SELECT pg_tde_is_encrypted('public.tde_preserved_probe')")"
[[ "$encrypted" == "t" ]]

default_method="$("${psql[@]}" --tuples-only --no-align --command "SHOW default_table_access_method")"
[[ "$default_method" == "tde_heap" ]]

wal_encryption="$("${psql[@]}" --tuples-only --no-align --command "SHOW pg_tde.wal_encrypt")"
[[ "${wal_encryption,,}" == "on" || "${wal_encryption,,}" == "true" ]]

"${psql[@]}" --command "CREATE TABLE public.tde_default_probe (id integer PRIMARY KEY, secret text NOT NULL); INSERT INTO public.tde_default_probe VALUES (1, repeat('SPS_TDE_NEW_TABLE_SENTINEL_9b23a410', 20)); CHECKPOINT;" >/dev/null
new_table_encrypted="$("${psql[@]}" --tuples-only --no-align --command "SELECT pg_tde_is_encrypted('public.tde_default_probe')")"
[[ "$new_table_encrypted" == "t" ]]

"${psql[@]}" --command "CREATE TABLE public.tde_wal_probe (id integer PRIMARY KEY, secret text NOT NULL); INSERT INTO public.tde_wal_probe VALUES (1, 'SPS_TDE_WAL_SENTINEL_31a4d08e'); CHECKPOINT;" >/dev/null
if "${compose[@]}" exec --no-TTY db sh -c "grep -aFq 'SPS_TDE_WAL_SENTINEL_31a4d08e' /var/lib/postgresql/data/pg_wal/*"; then
  echo "Plaintext sentinel was found in WAL after WAL encryption was enabled" >&2
  exit 1
fi

if "${psql[@]}" --command "CREATE TABLE public.tde_unsafe_probe (id integer) USING heap" >/dev/null 2>&1; then
  echo "pg_tde.enforce_encryption allowed a new unencrypted table" >&2
  exit 1
fi

relation_file="$("${psql[@]}" --tuples-only --no-align --command "SELECT pg_relation_filepath('public.tde_preserved_probe')")"
if [[ ! "$relation_file" =~ ^base/[0-9]+/[0-9]+$ ]]; then
  echo "Unexpected relation file path: $relation_file" >&2
  exit 1
fi
if "${compose[@]}" exec --no-TTY db sh -c "grep -aFq 'SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a' '/var/lib/postgresql/data/$relation_file'"; then
  echo "Plaintext sentinel was found in the encrypted table file" >&2
  exit 1
fi

"${psql[@]}" --command "CREATE DATABASE sps_restore_target OWNER sps_app" >/dev/null
RESTORE_TARGET_DATABASE=sps_restore_target "${restore_compose[@]}" run --build --rm --no-deps tde-restore-setup
"${compose[@]}" exec --no-TTY db pg_dump --no-owner --format=custom -U sps_app -d sps_dashboard --table=public.tde_preserved_probe \
  | "${compose[@]}" exec --no-TTY db pg_restore --exit-on-error --no-owner -U sps_app --dbname=sps_restore_target
restored_value="$("${compose[@]}" exec --no-TTY db psql --no-psqlrc --tuples-only --no-align -U sps_app -d sps_restore_target --command 'SELECT secret FROM public.tde_preserved_probe WHERE id = 1')"
[[ "$restored_value" == "SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a" ]]
restored_encrypted="$("${compose[@]}" exec --no-TTY db psql --no-psqlrc --tuples-only --no-align -U sps_app -d sps_restore_target --command "SELECT pg_tde_is_encrypted('public.tde_preserved_probe')")"
[[ "$restored_encrypted" == "t" ]]
runtime_access="$("${compose[@]}" exec --no-TTY db psql --no-psqlrc --tuples-only --no-align -U sps_app -d sps_restore_target --command "SELECT has_table_privilege('sps_runtime', 'public.tde_preserved_probe', 'SELECT')")"
[[ "$runtime_access" == "t" ]]

"${compose[@]}" restart db >/dev/null
for attempt in $(seq 1 60); do
  if "${psql[@]}" --tuples-only --no-align --command "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  [[ "$attempt" -lt 60 ]] || { echo "Database failed to restart with the persistent TDE keyring" >&2; exit 1; }
  sleep 2
done

after_restart="$("${psql[@]}" --tuples-only --no-align --command "SELECT secret FROM public.tde_preserved_probe WHERE id = 1")"
[[ "$after_restart" == "SPS_TDE_EXISTING_DATA_SENTINEL_7f4cdb1a" ]]
restart_encrypted="$("${psql[@]}" --tuples-only --no-align --command "SELECT pg_tde_is_encrypted('public.tde_preserved_probe')")"
[[ "$restart_encrypted" == "t" ]]

echo "TDE integration passed: PostgreSQL 17 data survived a vanilla-to-Percona engine switch; existing, new and restored tables are encrypted; WAL encryption and runtime restore grants are enabled; plaintext sentinels are absent from table/WAL files; and the keyring survived restart."
