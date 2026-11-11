# SPS Student Dashboard

This repository contains the production system under construction and the approved HTML prototype in [`prototype/`](prototype/).

## Run the foundation locally

Copy `.env.example` to `.env` and replace the sample secrets. Set `DATABASE_RUNTIME_PASSWORD` to a generated URL-safe secret (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and use the same value in the password component of `DATABASE_URL`. `DATABASE_ADMIN_URL` and `POSTGRES_PASSWORD` must use the same migration-account password. Then run:

```powershell
docker compose up --build
```

Compose waits for PostgreSQL, applies the versioned schema migration, and provisions a SCRAM-authenticated `sps_runtime` role before starting the API. The API role has data read/write and sequence use privileges only; schema changes run through the separate migration account. The migration account is not passed to the API container. To apply migrations manually during development, run `docker compose run --rm migrate`. The initial migration intentionally refuses downgrade because dropping its tables could destroy operational data; recover through a verified backup or a forward migration.

Open `http://localhost:8080/` for the actual sign-in, account administration and committed-data dashboard. See [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md) for the delivered workflow and limitations. The synthetic prototype remains at `http://localhost:8080/prototype/index.html`, and API documentation is at `http://localhost:8080/docs`.

The initial bootstrap identity is controlled by `BOOTSTRAP_USERNAME` and `BOOTSTRAP_PASSWORD`. The Superuser must change that credential and create a named IT Administrator through the setup wizard before normal application APIs unlock. Setup completion is audited and persisted; the bootstrap account retains full Superuser access. PostgreSQL is on a private Compose network and has no published host port. See [FIRST_RUN_SETUP.md](FIRST_RUN_SETUP.md).

Lost Superuser access can be recovered only by authorised Docker-host personnel using the audited, interactive command in [SUPERUSER_RECOVERY.md](SUPERUSER_RECOVERY.md). Recovery is refused when another active Superuser is available; there is no public recovery endpoint.
Set `APP_ENV=production` for a production deployment. In this mode the application rejects SQLite or non-psycopg database URLs, default or short JWT/bootstrap secrets, invalid Fernet encryption keys, duplicate active/previous encryption keys, and the checked-in development encryption key. `.env.example` contains placeholders for local setup only; production secrets must be generated and supplied through the approved deployment secret store.

## Current implemented slice

- Operator attendance browser: session creation/search, captured-roster lookup, mark/correction, missing review, audited count adjustment and explicit incomplete closure. Sessions/records use version checks and session locking; duplicate sessions are rejected. The monthly attendance export uses captured identities and labels partial legacy rosters. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md) for the API contract and historical-roster limits.

- Operator student profile browser: filtered/paged search, create/edit, status history, duplicate detection and version-checked saves. `PATCH /students/{id}` now requires `expected_version`; see [STUDENT_PROFILES.md](STUDENT_PROFILES.md).

- Operator intake workbook import: encrypted staging, sanitized preview, row validation, create-only or explicit update-existing mode and atomic version-checked commit. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

- Production browser sign-in, forced password rotation, Superuser account administration and committed-data dashboard with real Chromium CI acceptance tests. Browser assets run locally without CDNs; tokens remain only in memory. The remaining production screens and security/deployment gates are documented in [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md).

- Docker Compose services for NGINX, FastAPI and PostgreSQL.
- Separate PostgreSQL credentials for the migration service and API runtime; the API role cannot create schemas/objects or administer roles/databases. CI verifies its PostgreSQL privileges and SCRAM password storage.
- One-shot encrypted PostgreSQL backup, empty-database restore and bounded retention commands in the Compose `maintenance` profile. See [DATABASE_BACKUPS.md](DATABASE_BACKUPS.md).
- Live/readiness health endpoints.
- Bootstrap Superuser login with short-lived signed JWT access tokens.
- Mandatory first-login password change; Superuser-only account creation and role assignment with account-activity checks on each authenticated request.
- PBKDF2 password hashing.
- Stable-ID scheduling rules with effective dates, edit versions, class/cluster overlap prevention and exactly-one-rule bulk resolution. See [SCHEDULING_RULES.md](SCHEDULING_RULES.md) for the API and legacy binding process.
- Teacher, subject, instructional-class and cluster resource APIs, with inherited period definitions and a non-schedulable third lunch column.
- Lesson requirements linked to resource IDs, with duplicate prevention, availability/block checks, versioned edits, archive/restore and audit events. Operators and IT Administrators can maintain requirements.
- Weekly timetable planning with deterministic generation, persistent revisioned drafts, validated manual edits, class-oriented Amend 4-up for 4/8/12/16 classes, and IT approval. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md), [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) and [TIMETABLE_INTEGRATION.md](TIMETABLE_INTEGRATION.md) for current delivery and remaining gaps.
- The timetable workspace provides redesigned By class/By teacher boards, IT resource setup, Superuser operational access and browser print layouts. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md) for current delivery limits.
- Audited Excel timetable reports for By Instructional Class and By Teacher, generated from saved version snapshots with Executive downloads limited to approved versions. See [TIMETABLE_REPORT_EXPORTS.md](TIMETABLE_REPORT_EXPORTS.md).
- IT-managed publication of one approved timetable version per academic week, with an authenticated published-version lookup for downstream consumers. See [TIMETABLE_PUBLICATION.md](TIMETABLE_PUBLICATION.md).
- Protected student intake API with duplicate `Pris No.` rejection and application-encrypted name/date-of-birth fields.
- Student profile updates with append-only status history and audit events.
- Attendance session and record API with class eligibility checks, duplicate prevention, correction reasons, record review and session close control.
- Committed-data dashboard API, filtered attendance CSV export and IT-only audit event review.
- Versioned Alembic schema migrations run as an explicit Compose startup dependency and CI gate.
- CI test workflow and container-based pytest suite.

This remains an early foundation, not a production-ready release. Remaining work includes historical roster reconciliation, approved business-report reconciliation and print parity, complete setup/recovery, off-host backup scheduling and restore drills, database storage encryption, broader security hardening and deployment readiness.

## WSL laptop staging

The staging CD workflow deploys only a successfully tested push to `main` to a labeled self-hosted runner on the WSL laptop. Pull request tests remain on GitHub-hosted runners. Follow [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md) to enable Docker Desktop's WSL integration, prepare a local synthetic-data environment, register the `sps-staging` runner and configure the GitHub `staging` environment. The proxy binds to localhost by default. This staging process is not production deployment or a backup/rollback plan.

## Production image releases

The manual, `main`-only [production release workflow](PRODUCTION_RELEASE.md) requires successful CI and staging for the exact commit, scans digest-addressed candidates, and publishes signed images with a release manifest and CycloneDX SBOMs. It does not deploy production.

## Continuous integration

Every pull request runs lint and formatting checks, Python static-security and dependency audits, PostgreSQL-backed API tests with coverage reporting, Alembic migration checks, application and database-maintenance container builds/scans, Compose configuration validation, full-history secret scanning, and a Compose PostgreSQL backup/restore round trip that checks encryption, target safety, no-overwrite behavior and tamper rollback. This includes stacked pull requests whose base is another feature branch. Weekly Dependabot updates are enabled for Python and GitHub Actions dependencies. CI uses disposable test credentials and isolated PostgreSQL data; it does not connect to operational data.

For local Python development, install the test toolset with `python -m pip install -e ".[test]"`, then run `ruff check app tests migrations`, `ruff format --check app tests migrations`, `bandit -q -r app`, and `pytest`. Set `DATABASE_URL` to an isolated PostgreSQL database to exercise the same database engine as CI. Coverage is reported while the initial baseline is being established; no aggregate minimum is enforced yet.

Apply `alembic upgrade head` against the isolated test database before `pytest`. The suite now includes lesson lifecycle/permission checks, simultaneous lesson edits, a period-change/lesson-create race, database constraints, and a SQLite rehearsal proving that upgrading revision `0002` preserves existing profile/student rows. PostgreSQL remains the authoritative CI engine for constraint and concurrency checks.

Lesson requirements are available at `/api/v1/timetable/lessons`. `PUT /{id}` requires the complete requirement, `is_active`, and the last loaded `expected_version`; a stale save returns HTTP 409. `DELETE /{id}?expected_version=N` archives the row, retaining its references and audit history. Restore it using `PUT` with `is_active=true` and its current version. Each academic-year/class/teacher/subject combination is unique, including archived rows. Weekly count is the total number of periods; block length requests consecutive blocks with a shorter remainder when necessary (for example, count 3/length 2 is a double plus a single). Lunch, unavailable slots and gaps in configured times split blocks. These checks prove individual requirement feasibility; the future scheduler must also check combined workloads, rules and clashes. Period or cluster-membership edits that invalidate an existing active requirement are rejected.
Student Intake 2021 and 2023 imports use an explicit worksheet selector and separate IT-managed, versioned class crosswalks under **Timetable / Schedule → Scheduling setup**. Unknown or inactive mappings block the batch; changing a mapping after preview requires a fresh upload. The 2021 `VERIFY` detail is encrypted and `ELECTIVE` is retained as an academic profile field. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md) for import and privacy behavior.
