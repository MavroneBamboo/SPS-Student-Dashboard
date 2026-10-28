#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail() {
  printf '%s\n' "database-maintenance: $*" >&2
  exit 1
}

require_env() {
  local variable_name=$1
  [[ -n "${!variable_name:-}" ]] || fail "$variable_name is required"
}

require_pg_env() {
  require_env PGHOST
  require_env PGDATABASE
  require_env PGUSER
  require_env PGPASSWORD
}

backup() {
  require_pg_env
  require_env BACKUP_AGE_RECIPIENT
  backup_directory=${BACKUP_DIRECTORY:-/backups}
  backup_file=${BACKUP_FILE:-"sps-dashboard-$(date -u +%Y%m%dT%H%M%SZ).dump.age"}
  [[ -n "$backup_file" && "$backup_file" != "." && "$backup_file" != ".." && "$backup_file" != */* ]] \
    || fail "BACKUP_FILE must be a file name without path components"
  mkdir -p "$backup_directory"
  destination="$backup_directory/$backup_file"
  [ ! -e "$destination" ] || fail "refusing to overwrite existing backup $backup_file"
  temporary_file=$(mktemp "$backup_directory/.sps-dashboard-backup.XXXXXX")
  trap 'rm -f -- "$temporary_file"' EXIT
  trap 'exit 1' HUP INT TERM

  pg_dump --format=custom --no-owner --dbname="$PGDATABASE" \
    | age --recipient "$BACKUP_AGE_RECIPIENT" > "$temporary_file"
  [ -s "$temporary_file" ] || fail "encrypted backup is empty"
  chmod 0600 "$temporary_file"
  # A hard link commits the finished file atomically and never replaces an existing backup.
  ln "$temporary_file" "$destination" || fail "could not publish backup file"
  rm -f -- "$temporary_file"
  trap - EXIT HUP INT TERM
  printf 'Encrypted backup written: %s\n' "$backup_file"
}

restore() {
  require_pg_env
  require_env RESTORE_TARGET_ACK
  require_env AGE_IDENTITY_FILE
  backup_directory=${BACKUP_DIRECTORY:-/backups}
  backup_file=${BACKUP_FILE:-}
  [[ -n "$backup_file" && "$backup_file" != "." && "$backup_file" != ".." && "$backup_file" != */* ]] \
    || fail "BACKUP_FILE must identify an existing file name without path components"
  backup_path="$backup_directory/$backup_file"
  [ -f "$backup_path" ] || fail "backup file does not exist"
  [ -r "$backup_path" ] || fail "backup file is not readable"
  [ -f "$AGE_IDENTITY_FILE" ] || fail "AGE_IDENTITY_FILE must identify a readable age identity file"
  [ -r "$AGE_IDENTITY_FILE" ] || fail "age identity file is not readable"

  target="$PGHOST/$PGDATABASE"
  [ "$RESTORE_TARGET_ACK" = "$target" ] || fail "set RESTORE_TARGET_ACK to exactly $target after confirming the restore target"
  existing_relations=$(psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
    --dbname="$PGDATABASE" --command="SELECT count(*) FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')")
  [ "$existing_relations" = "0" ] || fail "restore target contains user relations; restore only into a fresh, empty database"

  age --decrypt --identity "$AGE_IDENTITY_FILE" "$backup_path" \
    | pg_restore --exit-on-error --single-transaction --no-owner --dbname="$PGDATABASE"
  printf 'Restore completed into the empty target database %s.\n' "$target"
}

prune() {
  local backup_directory=${BACKUP_DIRECTORY:-/backups}
  local retention_days=${BACKUP_RETENTION_DAYS:-}
  [[ "$retention_days" =~ ^[1-9][0-9]*$ ]] || fail "BACKUP_RETENTION_DAYS must be a positive whole number"
  [[ -d "$backup_directory" ]] || fail "backup directory does not exist"
  find "$backup_directory" -maxdepth 1 -type f -name 'sps-dashboard-*.dump.age' -mtime "+$retention_days" -print -delete
}

mode=${1:-}
case "$mode" in
  backup) backup ;;
  restore) restore ;;
  prune) prune ;;
  *) fail "usage: database-maintenance backup|restore|prune" ;;
esac
