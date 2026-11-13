# Encrypted PostgreSQL backup and restore

The `maintenance` Compose profile provides a one-shot `pg_dump` backup encrypted with age and a restore command that only targets a fresh, empty database. PostgreSQL is accessed on the private Compose network; the database port remains unpublished. The API/runtime account reads the backup, while restore uses the PostgreSQL administrator account. PostgreSQL relation/WAL encryption and its recovery requirements are documented in [POSTGRES_TDE.md](POSTGRES_TDE.md).

## Configure the encryption key and destination

Build the maintenance image and generate an age identity in a protected host directory. The private identity is needed to restore; the public recipient is safe to place in the local `.env` file.

```bash
install -d -m 700 "$HOME/.config/sps-student-dashboard"
docker compose --profile maintenance build database-backup
docker compose --profile maintenance run --no-deps --rm \
  --volume "$HOME/.config/sps-student-dashboard:/keys" \
  --entrypoint age-keygen database-backup \
  -o /keys/backup.agekey 2>/dev/null
docker compose --profile maintenance run --no-deps --rm \
  --volume "$HOME/.config/sps-student-dashboard:/keys" \
  --entrypoint age-keygen database-backup \
  -y /keys/backup.agekey
```

Set the reported `age1...` public key and local paths in `.env`:

```dotenv
BACKUP_DATABASE_USER=sps_runtime
BACKUP_DATABASE_PASSWORD=<same value as DATABASE_RUNTIME_PASSWORD>
BACKUP_AGE_RECIPIENT=age1...
BACKUP_HOST_PATH=/path/to/separate/protected/backup/storage
BACKUP_AGE_IDENTITY_HOST_PATH=/home/<user>/.config/sps-student-dashboard/backup.agekey
BACKUP_RETENTION_DAYS=90
```

Create the configured backup directory before running the container and ensure it belongs to the UID/GID configured by `BACKUP_CONTAINER_UID` and `BACKUP_CONTAINER_GID`:

```bash
install -d -m 700 /path/to/separate/protected/backup/storage
```

Keep the private age identity outside the backup directory and protect an additional recovery copy. Losing it makes the backups unreadable. Use a backup path on storage separate from the database host for production. The default `./backups` path is only suitable for development.

## Create and prune backups

Run from the repository directory. The command prints the encrypted backup filename; by default it is timestamped in UTC. Existing files are never overwritten, and incomplete output is removed if `pg_dump` or encryption fails.

```bash
docker compose --profile maintenance run --rm --build database-backup
docker compose --profile maintenance run --rm database-backup-prune
```

The prune command removes only generated `sps-dashboard-*.dump.age` files older than `BACKUP_RETENTION_DAYS` from the configured backup directory. It does not traverse subdirectories or remove custom-named files.

For daily backups, schedule the backup command with the host's scheduler and capture its exit status and logs. For example, a cron entry can use:

```cron
0 2 * * * cd /home/<user>/src/SPS-Student-Dashboard && flock -n /tmp/sps-dashboard-backup.lock docker compose --project-name sps-student-dashboard --env-file /home/<user>/.config/sps-student-dashboard/production.env --profile maintenance run --rm database-backup >> /var/log/sps-student-dashboard-backup.log 2>&1
```

Configure the scheduler and log location for the production host, and monitor missed backups. The repository does not install a host scheduler automatically.

## Restore drill

Restore never drops or cleans existing objects. Create a new empty database on the target PostgreSQL cluster, then set `BACKUP_FILE`, `RESTORE_TARGET_DATABASE`, `RESTORE_TARGET_ACK` and `BACKUP_AGE_IDENTITY_HOST_PATH` in the local environment. The acknowledgement must exactly match `db/<database-name>` for the Compose target.

```bash
docker compose exec -T db createdb -U sps_app -O sps_app sps_restore_drill
```

Then configure:

```dotenv
BACKUP_FILE=sps-dashboard-<timestamp>.dump.age
RESTORE_TARGET_DATABASE=sps_restore_drill
RESTORE_TARGET_ACK=db/sps_restore_drill
```

Run the restore and verify the recovered records and application behavior before promoting the restored database. The restore service first prepares the empty target with the configured TDE provider and database default access method; the provider keys must be available to the database server:

```bash
docker compose --profile maintenance run --rm --build database-restore
```

Restore decrypts the archive directly into `pg_restore` using one database transaction. A failed decryption or restore rolls back the transaction. Restore access is checked against the exact target host/database acknowledgement and the target must have no user relations. The CI integration test exercises backup, restore, refusal to overwrite, and tampered-ciphertext rejection with PostgreSQL 17 and age. The TDE integration test separately verifies encrypted relation creation and key persistence; production recovery also requires access to the external TDE provider.

This provides encrypted logical backups and a restore mechanism. Production approval still requires an isolated backup destination, a scheduled job with monitored success/failure, a tested off-host restore, key recovery custody, retention approval, and agreed recovery-time/recovery-point objectives.
