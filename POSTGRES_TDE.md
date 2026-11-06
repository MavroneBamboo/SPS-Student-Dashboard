# PostgreSQL storage encryption

The Compose database uses Percona Distribution for PostgreSQL 17.11.1-4 on UBI 9 with `pg_tde`. The application remains PostgreSQL-compatible and connects through the private Compose network. Application field encryption, TDE, and age-encrypted logical backups protect different data copies and are all retained.

## What is encrypted

`pg_tde` encrypts user data stored in `tde_heap` tables, associated TOAST data, indexes on encrypted tables, and WAL records. The setup command migrates existing ordinary tables and materialized views, configures partitioned tables for future encrypted partitions, applies `tde_heap` as the database default, and enables `pg_tde.enforce_encryption`. The startup helper provisions keys and completes the required PostgreSQL restart before migrations and the API can start.

`pg_tde` does not encrypt PostgreSQL system catalogs/statistics or temporary spill files created when queries exceed `work_mem`. Table metadata such as column names is also visible. Production must use host or storage-level encryption for the complete database volume, WAL, temporary files, and other files. The Compose TDE feature alone must not be represented as full-volume encryption.

## Key providers

- Local development and CI use a file provider stored in the separate `tde-keyring` named volume. The key file is unencrypted and is not suitable for production.
- Production sets `APP_ENV=production` and uses the Vault KV v2 provider. The database container reads a narrowly scoped Vault token from the configured read-only secret file. Provision a Vault endpoint with TLS verification, a KV v2 mount, and read/write access only to this application's key path. Keep the Vault token and its recovery access outside the database host.
- Preserve the provider name, principal key names, Vault mount, and Vault key versions. Losing or replacing key material can make the database and its backups unreadable. Do not delete keys or change providers as routine maintenance.

The database image has `pg_tde` in `shared_preload_libraries`. `scripts/compose-up.sh` starts only the database prerequisites, runs `app.tde_setup --prepare`, restarts PostgreSQL if WAL encryption is not active, verifies the setting, then starts the migration and application services. `tde-setup --verify` is a migration dependency and fails closed if encryption is missing. The staging workflow uses the same helper. Production Vault settings are in `docker-compose.tde-production.yml`; compose that file with the approved production Compose files and protected environment file.

## Existing database migration

The setup is idempotent, but changing a populated PostgreSQL volume to Percona PostgreSQL and rewriting existing relations is an operational migration. The helper converts its configured database volume in place and is intended for local development and synthetic staging. Do not point it at the only copy of production data. For production use a side-by-side cluster and logical restore:

1. Take an age-encrypted logical backup and prove it restores into an isolated, empty target.
2. Provision a new Compose project and PostgreSQL volume using the Percona image, Vault key provider and host/storage encryption. Keep it isolated from user traffic.
3. Stop or quiesce application writes, take the final backup, and restore it into the new target. Restore setup creates encrypted tables and reapplies the restricted API role grants before `pg_restore`.
4. Confirm TDE verification, application health, sensitive record reads/writes, reports, counts/reconciliation and a second restore drill on the new cluster.
5. Cut over application/proxy configuration only after acceptance. Keep the original PostgreSQL cluster read-only and unchanged for rollback until the new cluster is accepted.
6. Retain the age identity and Vault access. Never use `docker compose down --volumes` on an operational project.

The integration test in `scripts/test-postgres-tde.sh` starts a unique, disposable Compose project. It initializes a shared database volume using the repository's current vanilla `postgres:17.2-alpine` image, then opens that same PostgreSQL 17 volume with Percona and checks preservation/conversion of pre-existing data, encrypted new tables, rejection of an explicit heap table, plaintext sentinels in relation/WAL files, and key persistence after restart. It refuses to clean up if resources with its chosen project name already exist.

## Backup and restore

The existing age-encrypted `pg_dump` backup format remains the portable recovery artifact. Create an empty restore database first. `database-restore` depends on `tde-restore-setup`, which enables the extension, configures the key, enforces encrypted tables and reapplies least-privilege runtime grants for that target before `pg_restore` opens its connection. Verify data, encrypted relation status, application behavior, counts and audit state before promoting the restored database. Retain both the age identity and TDE provider access; they protect separate layers.

WAL encryption is enabled for database storage. The current backup path uses logical `pg_dump` and does not archive physical WAL. Do not add physical/WAL backup tooling without validating the tool against the exact Percona `pg_tde` version and its documented WAL encryption requirements.

## Release gates and limitations

The CI integration test is required before merging this change. Production use remains gated on a witnessed full-size migration, Vault key recovery drill, host/storage encryption evidence, backup restore rehearsal, operational downtime approval, and performance measurement. Docker Compose and the setup code cannot independently verify that the host disk is encrypted.

References: [Percona encrypted data scope](https://docs.percona.com/pg-tde/index/tde-encrypts.html), [Percona limitations](https://docs.percona.com/pg-tde/index/tde-limitations.html), [Percona key functions](https://docs.percona.com/pg-tde/functions.html), and [PostgreSQL 17 materialized-view access methods](https://www.postgresql.org/docs/17/sql-altermaterializedview.html).
