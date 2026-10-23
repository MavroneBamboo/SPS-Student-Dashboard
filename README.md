# SPS Student Dashboard

This repository contains the production system under construction and the approved HTML prototype in [`prototype/`](prototype/).

## Run the foundation locally

Copy `.env.example` to `.env` and replace the sample secrets. Then run:

```powershell
docker compose up --build
```

Compose waits for PostgreSQL and applies the versioned schema migration before starting the API. To apply migrations manually during development, run `docker compose run --rm migrate`. The initial migration intentionally refuses downgrade because dropping its tables could destroy operational data; recover through a verified backup or a forward migration.

Open `http://localhost:8080/prototype/index.html` for the prototype or `http://localhost:8080/docs` for the API documentation.

The initial bootstrap identity is controlled by `BOOTSTRAP_USERNAME` and `BOOTSTRAP_PASSWORD`. It is seeded as a Superuser in setup state and must be changed/rotated before operational use. PostgreSQL is on a private Compose network and has no published host port.

## Current implemented slice

- Docker Compose services for NGINX, FastAPI and PostgreSQL.
- Live/readiness health endpoints.
- Bootstrap Superuser login with short-lived signed JWT access tokens.
- Mandatory first-login password change; Superuser-only account creation and role assignment with account-activity checks on each authenticated request.
- PBKDF2 password hashing.
- Stable-ID scheduling rules with effective dates, edit versions, class/cluster overlap prevention and exactly-one-rule bulk resolution. See [SCHEDULING_RULES.md](SCHEDULING_RULES.md) for the API and legacy binding process.
- Teacher, subject, instructional-class and cluster resource APIs, with inherited period definitions and a non-schedulable third lunch column.
- Lesson requirements linked to resource IDs, with duplicate prevention, availability/block checks, versioned edits, archive/restore and audit events. Operators and IT Administrators can maintain requirements.
- Protected student intake API with duplicate `Pris No.` rejection and application-encrypted name/date-of-birth fields.
- Student profile updates with append-only status history and audit events.
- Attendance session and record API with class eligibility checks, duplicate prevention, correction reasons, record review and session close control.
- Committed-data dashboard API, filtered attendance CSV export and IT-only audit event review.
- Versioned Alembic schema migrations run as an explicit Compose startup dependency and CI gate.
- CI test workflow and container-based pytest suite.

This remains an early foundation, not a production-ready release. The APIs currently cover basic student intake/profile history, attendance entry, preliminary dashboard/export endpoints and scheduling-rule storage. Remaining work includes managed user/role administration, Excel imports, complete timetable planning and Amend 4-up lesson placement, approved business-report reconciliation, backup/restore, broader security hardening and a production frontend.

## Continuous integration

Pull requests targeting `main` run lint and formatting checks, Python static-security and dependency audits, PostgreSQL-backed API tests with coverage reporting, Alembic migration checks, a production-container build and vulnerability scan, Compose configuration validation, and a full-history secret scan. Weekly Dependabot updates are enabled for Python and GitHub Actions dependencies. CI uses disposable test credentials and an isolated PostgreSQL service; it does not connect to operational data.

For local Python development, install the test toolset with `python -m pip install -e ".[test]"`, then run `ruff check app tests migrations`, `ruff format --check app tests migrations`, `bandit -q -r app`, and `pytest`. Set `DATABASE_URL` to an isolated PostgreSQL database to exercise the same database engine as CI. Coverage is reported while the initial baseline is being established; no aggregate minimum is enforced yet.

Apply `alembic upgrade head` against the isolated test database before `pytest`. The suite now includes lesson lifecycle/permission checks, simultaneous lesson edits, a period-change/lesson-create race, database constraints, and a SQLite rehearsal proving that upgrading revision `0002` preserves existing profile/student rows. PostgreSQL remains the authoritative CI engine for constraint and concurrency checks.

Lesson requirements are available at `/api/v1/timetable/lessons`. `PUT /{id}` requires the complete requirement, `is_active`, and the last loaded `expected_version`; a stale save returns HTTP 409. `DELETE /{id}?expected_version=N` archives the row, retaining its references and audit history. Restore it using `PUT` with `is_active=true` and its current version. Each academic-year/class/teacher/subject combination is unique, including archived rows. Weekly count is the total number of periods; block length requests consecutive blocks with a shorter remainder when necessary (for example, count 3/length 2 is a double plus a single). Lunch, unavailable slots and gaps in configured times split blocks. These checks prove individual requirement feasibility; the future scheduler must also check combined workloads, rules and clashes. Period or cluster-membership edits that invalidate an existing active requirement are rejected.
