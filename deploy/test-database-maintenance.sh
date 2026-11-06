#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="sps-db-maintenance-ci-${GITHUB_RUN_ID:-$$}"
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" || -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]]; then
  echo "Refusing to reuse an existing Compose test project: $project" >&2
  exit 2
fi

test_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/sps-database-maintenance.XXXXXX")"
test_root="$(realpath -e "$test_root")"
case "$test_root" in
  "${RUNNER_TEMP:-/tmp}"/sps-database-maintenance.*) ;;
  *) echo "Refusing to use unexpected test directory: $test_root" >&2; exit 2 ;;
esac
mkdir -m 0700 "$test_root/backups"

export POSTGRES_USER=sps_app
export POSTGRES_DB=sps_dashboard
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?CI PostgreSQL password is required}"
export DATABASE_ADMIN_URL="postgresql+psycopg://sps_app:${POSTGRES_PASSWORD}@db:5432/sps_dashboard"
export BACKUP_DATABASE_USER=sps_runtime
export BACKUP_DATABASE_PASSWORD=ci-only-runtime-password
export DATABASE_RUNTIME_PASSWORD="$BACKUP_DATABASE_PASSWORD"
export DATABASE_URL="postgresql+psycopg://${BACKUP_DATABASE_USER}:${DATABASE_RUNTIME_PASSWORD}@db:5432/sps_dashboard"
export BACKUP_HOST_PATH="$test_root/backups"
export BACKUP_AGE_IDENTITY_HOST_PATH="$test_root/backup.agekey"
export BACKUP_CONTAINER_UID="$(id -u)"
export BACKUP_CONTAINER_GID="$(id -g)"
export BACKUP_FILE=verified.dump.age
export RESTORE_TARGET_DATABASE=sps_restore_target
export RESTORE_TARGET_ACK=db/sps_restore_target
export DATABASE_MAINTENANCE_IMAGE_TAG=ci
export BACKUP_AGE_RECIPIENT=

compose=(docker compose --project-name "$project" --env-file "$repository_root/.env.example" --profile maintenance)
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ "$test_root" == "${RUNNER_TEMP:-/tmp}"/sps-database-maintenance.* ]]; then
    rm -rf -- "$test_root"
  fi
}
trap cleanup EXIT

maintenance_image="sps-database-maintenance:ci"
docker run --rm --user "$(id -u):$(id -g)" --volume "$test_root:/keys" \
  --entrypoint age-keygen "$maintenance_image" -o /keys/backup.agekey >/dev/null 2>&1
export BACKUP_AGE_RECIPIENT="$(docker run --rm --volume "$test_root:/keys:ro" \
  --entrypoint age-keygen "$maintenance_image" -y /keys/backup.agekey)"

SPS_COMPOSE_UP_DB_ONLY=1 bash "$repository_root/scripts/compose-up.sh" \
  --project-name "$project" \
  --project-directory "$repository_root" \
  --env-file "$repository_root/.env.example"
ready=false
for attempt in $(seq 1 30); do
  if "${compose[@]}" exec --no-TTY db pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo "PostgreSQL test service did not become ready" >&2; exit 1; }

"${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c 'CREATE TABLE backup_probe (value text PRIMARY KEY)' >/dev/null
"${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "INSERT INTO backup_probe VALUES ('synthetic-backup-roundtrip')" >/dev/null
"${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE ROLE sps_runtime LOGIN PASSWORD '$BACKUP_DATABASE_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" >/dev/null
"${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c 'GRANT CONNECT ON DATABASE sps_dashboard TO sps_runtime' \
  -c 'GRANT USAGE ON SCHEMA public TO sps_runtime' \
  -c 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO sps_runtime' \
  -c 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO sps_runtime' >/dev/null
runtime_privileges="$("${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT rolsuper || ',' || rolcreatedb || ',' || rolcreaterole || ',' || has_database_privilege('sps_runtime', current_database(), 'CONNECT') || ',' || has_schema_privilege('sps_runtime', 'public', 'CREATE') FROM pg_roles WHERE rolname = 'sps_runtime'")"
[[ "$runtime_privileges" == false,false,false,true,false ]]
"${compose[@]}" exec --no-TTY db createdb -U "$POSTGRES_USER" sps_restore_target
"${compose[@]}" exec --no-TTY db createdb -U "$POSTGRES_USER" sps_restore_corrupt
"${compose[@]}" exec --no-TTY db createdb -U "$POSTGRES_USER" sps_restore_nonempty
"${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d sps_restore_nonempty -v ON_ERROR_STOP=1 \
  -c 'CREATE TABLE existing_probe (value text PRIMARY KEY)' \
  -c "INSERT INTO existing_probe VALUES ('preserve-existing-data')" >/dev/null

"${compose[@]}" run --rm database-backup >/dev/null
backup_path="$test_root/backups/$BACKUP_FILE"
[[ -s "$backup_path" ]]
if grep --binary-files=text --fixed-strings --quiet synthetic-backup-roundtrip "$backup_path"; then
  echo "Plaintext marker was found in encrypted backup" >&2
  exit 1
fi

if "${compose[@]}" run --rm database-backup >"$test_root/no-overwrite.log" 2>&1; then
  echo "Backup unexpectedly overwrote an existing file" >&2
  exit 1
fi
grep --fixed-strings --quiet 'refusing to overwrite existing backup' "$test_root/no-overwrite.log"

export RESTORE_TARGET_ACK=db/wrong-target
if "${compose[@]}" run --rm database-restore >"$test_root/wrong-target.log" 2>&1; then
  echo "Restore unexpectedly accepted an incorrect target acknowledgement" >&2
  exit 1
fi
grep --fixed-strings --quiet 'after confirming the restore target' "$test_root/wrong-target.log" || {
  cat "$test_root/wrong-target.log" >&2
  exit 1
}
export RESTORE_TARGET_ACK=db/sps_restore_target

"${compose[@]}" run --rm database-restore
restored_value="$("${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d sps_restore_target -Atc \
  'SELECT value FROM backup_probe')"
[[ "$restored_value" == synthetic-backup-roundtrip ]] || {
  printf 'Restore returned an unexpected probe value: %q\n' "$restored_value" >&2
  exit 1
}

export RESTORE_TARGET_DATABASE=sps_restore_nonempty
export RESTORE_TARGET_ACK=db/sps_restore_nonempty
if "${compose[@]}" run --rm database-restore >"$test_root/nonempty-target.log" 2>&1; then
  echo "Restore unexpectedly accepted a non-empty database" >&2
  exit 1
fi
grep --fixed-strings --quiet 'fresh, empty database' "$test_root/nonempty-target.log" || {
  cat "$test_root/nonempty-target.log" >&2
  exit 1
}
preserved_value="$("${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d sps_restore_nonempty -Atc \
  'SELECT value FROM existing_probe')"
[[ "$preserved_value" == preserve-existing-data ]] || {
  printf 'Non-empty target data changed unexpectedly: %q\n' "$preserved_value" >&2
  exit 1
}

cp -- "$backup_path" "$test_root/backups/tampered.dump.age"
python3 - "$test_root/backups/tampered.dump.age" <<'PY'
import pathlib
import sys

backup = pathlib.Path(sys.argv[1])
ciphertext = bytearray(backup.read_bytes())
ciphertext[-1] ^= 1
backup.write_bytes(ciphertext)
PY
export BACKUP_FILE=tampered.dump.age
export RESTORE_TARGET_DATABASE=sps_restore_corrupt
export RESTORE_TARGET_ACK=db/sps_restore_corrupt
if "${compose[@]}" run --rm database-restore >"$test_root/tampered-restore.log" 2>&1; then
  echo "Restore unexpectedly accepted tampered ciphertext" >&2
  exit 1
fi
corrupt_target_empty="$("${compose[@]}" exec --no-TTY db psql -U "$POSTGRES_USER" -d sps_restore_corrupt -Atc \
  "SELECT to_regclass('public.backup_probe') IS NULL")"
[[ "$corrupt_target_empty" == t ]]

export BACKUP_RETENTION_DAYS=30
touch "$test_root/backups/sps-dashboard-old.dump.age" \
  "$test_root/backups/sps-dashboard-recent.dump.age" \
  "$test_root/backups/custom-old.dump.age"
touch -d '40 days ago' "$test_root/backups/sps-dashboard-old.dump.age" "$test_root/backups/custom-old.dump.age"
"${compose[@]}" run --rm database-backup-prune >/dev/null
[[ ! -e "$test_root/backups/sps-dashboard-old.dump.age" ]]
[[ -e "$test_root/backups/sps-dashboard-recent.dump.age" ]]
[[ -e "$test_root/backups/custom-old.dump.age" ]]

echo "Encrypted backup, restore, target validation, no-overwrite, tamper rollback and retention passed."
