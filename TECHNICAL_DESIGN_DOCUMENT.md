# SPS Student Dashboard

Sign-in rate-limit increment (27 October 2026): the Nginx reverse proxy applies a per-client-IP limit to `POST /api/v1/auth/login` and responds with HTTP 429 when a burst exceeds the configured threshold. CI validates the Nginx config and starts a local mock upstream to verify actual throttling. This is network-level protection; account-level lockout and distributed abuse controls remain follow-up work.


Monthly attendance export increment (27 October 2026; layout follow-up 10 November): `GET /api/v1/reports/attendance/monthly.xlsx` generates an authenticated, class-and-month scoped `.xlsx` register for Operators and Executives. The sheet follows the legacy month/class, weekday, date and AM/PM header hierarchy while retaining every calendar day, including weekend sessions. The server writes dates and weekdays as literal values rather than workbook formulas. Print setup is A4 landscape, two pages across, with repeated headers and frozen roster columns. The export uses the month’s captured rosters and saved marks, labels partial legacy coverage or the no-session/current-roster fallback, writes `P/A/L/E/M` for present/absent/late/excused/missing, and leaves unrecorded slots blank. The dashboard form initiates the download without exposing the bearer token in the URL and cancels the request when the user signs out. API and Chromium checks cover workbook hierarchy, weekend marks, snapshot identity, merge ranges, print settings and download. Pixel-level comparison with every legacy sheet remains open; the supplied sheet’s defined print area ends before date formulas in its used range.

Operational permission increment (26 October 2026): all student and attendance routes now enforce Operator server-side; dashboard and attendance CSV enforce Operator/Executive, while audit uses Superuser/IT Administrator. API tests exercise every role across reads and writes. See [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md) for the exact matrix and remaining authorization work.

Identity increment (6 November 2026): migration `0008` preserves accounts while adding token versions and case-insensitive username uniqueness. JWT validation requires a version and live active user; PostgreSQL advisory locking serializes account mutations and last-administrator checks. IT Administrators manage named accounts except Superusers. Password/role/status changes revoke all tokens, while append-only `auth_session` audit events support listing and revoking individual sessions and every request checks the presented JWT ID against revocation events. See [IDENTITY_SECURITY.md](IDENTITY_SECURITY.md); full permission separation, setup/recovery and deployment security remain required.

Attendance increment (26 October 2026): migration `0007` preserves attendance while adding session/record versions and class/date/type uniqueness, refusing ambiguous legacy sessions before DDL. PostgreSQL session/student row locks, required expected versions, immutable record identity, correction reasons and audited incomplete closure/count adjustments protect browser operations. Raw attendance APIs deny Executive access; historical roster/reconciliation and complete permission separation remain release work. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

Profile/import increment (28 October–4 November 2026): migrations `0009`–`0011` add extended student fields, encrypted staging and the controlled source-class crosswalk; `20261104_0018` adds configurable encrypted-payload retention; `20261104_0019` adds the 2021 intake source and records batch source year. The Operator explicitly selects the 2021 or 2023 sheet; strict header maps, cached-age formula handling and separate source-year class crosswalks prevent fuzzy data interpretation. The 2021-only `VERIFY` detail is application-encrypted and `ELECTIVE` is retained in the profile. Imports preview and commit in create-only or explicit update-existing mode with stale mapping/profile/reference checks and atomic audit/history writes. Purge preserves committed student records and import outcome metadata. Database backups and WAL need separate retention enforcement. Golden business reconciliation, historical class reconciliation and report parity remain follow-up work. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md), [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md), and [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Student reference catalog increment (4 November 2026): migration `20261104_0016` follows first-run setup migration `20261104_0015` and creates versioned category, institution, and academic-year values, backfilling existing student categories and academic years from student and timetable records. Catalog names have NFKC/whitespace/casefold uniqueness; writes are audited and use expected-version compare-and-swap. IT Administrators and the Superuser write; all operational roles may read. The profile/reference integration below adds `students.institution`, active catalog enforcement for profile writes, version snapshots for intake categories/academic years, and institution reporting. Historical labels outside the catalogs still require explicit reconciliation; see [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Student profile reference integration (4 November 2026): migration `20261104_0017` adds optional `students.institution`. Profile APIs resolve category, academic year, and institution labels to active catalog values under row locks; category and academic-year storage remains compatible with historical text records. The intake preview stores reference ID/type/name/version and commit rechecks active state and version under lock before writing. Referenced catalog values cannot be renamed; archival preserves existing profiles, and changed values must use an active replacement. Institution remains optional because the source intake sheet has no institution field. See [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Browser increment (26 October 2026): same-origin HTML/CSS/JavaScript are served from `/ui/`, packaged in the application image, and reached from the root. Authentication uses the existing bearer API with module-memory-only tokens, current identity from `/auth/me`, forced rotation, expiry and data clearing. Dynamic values use text/DOM properties; assets/API responses use no-store and restrictive CSP/security headers. Nginx routes production and prototype paths explicitly. Chromium CI exercises real API/database workflows. See [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md), including unresolved HTTPS, session, permission and full-feature release gates.

Generation increment (26 October 2026): `POST /api/v1/timetable/versions/{id}/generate` uses the shared validator for deterministic first-fit and bounded iterative repair. Default fill preserves every existing block; explicit replace-unlocked preserves all locks. The complete resulting grid, revision and report commit atomically. Reports are retained in audit events and exposed through a paginated version-scoped API. Incomplete runs remain drafts with per-block reasons and an explicit search-limit flag. Response grids are captured under the transaction lock before commit. See [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) for contracts, verification and remaining scope.

Implementation integrity update (26 October 2026): every timetable mutation must verify that persisted occupied cells exactly match the shared validator's expansion of stored lesson blocks. Compare block ownership, class, teacher, subject, day, teaching period and actual start/end times under the timetable transaction lock. Reject inconsistent drafts with 409 before writes or audit changes; do not approve a block-complete but cell-incomplete timetable. Keep reads available for investigation and require explicit reconciliation or replacement. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).

## Technical Design Document

**Version:** 1.0  
**Status:** Proposed for implementation  
**Related documents:** [PRODUCT_DESCRIPTION.md](PRODUCT_DESCRIPTION.md), [TECHNICAL_FOLLOW_UP.md](TECHNICAL_FOLLOW_UP.md)

## 1. Purpose and design goals

SPS Student Dashboard is an internal network application for student intake, attendance, dashboards and report generation. This document defines the target technical design for a secure, auditable and Docker Compose deployable system.

The design goals are:

- One authoritative database for profiles, attendance, reference data and audit history.
- Browser access through a backend API; the browser never connects directly to the database.
- Role-based access for Superuser, IT Administrator, Operator and Executive users.
- Near-real-time reporting from committed records.
- Safe Excel import/export during migration from the UiPath and workbook processes.
- Repeatable CI/CD, automated testing and security checks.
- Deployment on a restricted or air-gapped internal network.

## 2. Scope and assumptions

The first release covers student profiles, attendance, reference data, imports, dashboards, reports, user administration, audit history, backups and Docker Compose deployment. Existing UiPath workflows may remain as transitional integrations.

The design assumes an internal server, an approved relational database, browser clients on the SPS network and no dependency on public cloud services for core operation. The exact programming language and database product remain implementation decisions, but all choices must satisfy the interfaces and controls defined here.

## 3. System context

```text
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”       HTTPS        â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Browser usersâ”‚ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¶â”‚ Reverse proxy     â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                     â”‚ TLS + headers     â”‚
                                     â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                               â”‚
                                               â–¼
                                     â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                     â”‚ Web/API applicationâ”‚
                                     â”‚ Auth + business    â”‚
                                     â”‚ rules + reports    â”‚
                                     â””â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”˜
                                           â”‚       â”‚
                                           â–¼       â–¼
                                   â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                   â”‚ Database â”‚ â”‚ Worker   â”‚
                                   â”‚ encryptedâ”‚ â”‚ imports/ â”‚
                                   â”‚ storage  â”‚ â”‚ exports  â”‚
                                   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

The frontend is an untrusted client. It receives only data permitted by the backend and never receives database credentials, connection strings or encryption keys.

## 4. Component design

### 4.1 Reverse proxy

The reverse proxy is the only public application entry point on the internal network. It terminates HTTPS, applies security headers, limits request size and routes `/api` to the backend and static frontend content to the frontend service.

Required controls include TLS, HSTS where appropriate for the internal domain, a restrictive Content Security Policy, `X-Content-Type-Options`, clickjacking protection, request limits and access logging without sensitive payloads.

### 4.2 Frontend

The frontend provides login, profile forms, attendance entry, dashboards and report actions. It may hide controls for usability, but it must not be relied on for authorisation. Every protected operation is enforced again by the backend.

The frontend must not contain database credentials or encryption keys. Token handling must use the selected secure browser pattern; if cookies are used, they must be Secure, HttpOnly and SameSite-configured with CSRF protection for state-changing requests.

### 4.3 Backend API

The backend owns authentication, authorisation, validation, transactions, report queries, encryption/decryption and audit events. It exposes versioned endpoints such as `/api/v1/auth`, `/api/v1/students`, `/api/v1/attendance`, `/api/v1/imports`, `/api/v1/reports` and `/api/v1/admin`.

The backend must use parameterised queries or a safe data-access layer, consistent error responses, correlation IDs, request validation and transaction boundaries. It must never return fields that the requesting role is not allowed to view.

### 4.4 Worker

Long-running imports, Excel/PDF generation, scheduled reports and reconciliation jobs run in a worker. Jobs have a status, owner, timestamps, retry count and error detail safe for the user interface. A failed job must not leave a partially committed import.

### 4.5 Database

The database stores normalised business records, immutable audit events and import metadata. It is reachable only on an internal Docker network and is not published to the user workstation network. Database storage and backups are encrypted.

## 5. Identity and access design

### 5.1 Bootstrap superuser

Installation creates a setup-state Superuser with a one-time secret. On first use, the system requires a credential change and creation of a named IT Administrator through the initial setup workspace. A persisted setup gate blocks all normal API operations until the bootstrap Superuser completes both steps; account creation, setup completion and audit events commit atomically. Existing installations are marked complete only when they already have an active Superuser who changed the bootstrap credential and an active IT Administrator. The bootstrap account remains a full-access Superuser after setup. Recovery uses the audited, interactive host-admin command documented in [SUPERUSER_RECOVERY.md](SUPERUSER_RECOVERY.md); there is no public recovery endpoint.

### 5.2 Roles

Roles map to permissions, not UI screens:

| Role | Access summary |
|---|---|
| Superuser | Bootstrap and emergency administration only |
| IT Administrator | Users, roles, settings, reference data, audit and support |
| Operator | Student profiles, imports, attendance and operational reports |
| Executive | Read-only dashboards and approved report exports |

Use deny-by-default checks at the API/service layer. Privileged operations require a named user and are written to the audit log.

### 5.3 JWT design

The backend issues signed, short-lived access JWTs only after successful authentication. Each request validates signature, issuer, audience, expiry, not-before and token type. The frontend cannot grant itself permissions by changing token claims.

Refresh tokens, if used, must be rotated, revocable, stored securely and associated with a session/device record. Signing keys are supplied through deployment secrets, rotated by key ID and never committed to source control. Logout revokes the refresh session; short-lived access tokens expire naturally.

## 6. Data model

Core entities:

- `users`, `roles`, `permissions`, `user_roles`, `sessions`
- `students`, `student_status_history`
- `institutions`, `classes`, `categories`, `academic_years`
- `attendance_sessions`, `attendance_records`, `attendance_roster_entries`, `attendance_class_mappings`
- `import_batches`, `import_rows`, `export_jobs`
- `audit_log`, `system_settings`

Important rules:

- `students.pris_no` is the preferred unique business identifier.
- Name-only matching is not allowed for an automatic update when duplicates exist.
- Attendance uniqueness is enforced by student, session and date according to the agreed attendance policy.
- Status changes are recorded as history; historical records are not silently overwritten.
- Reference data is effective-dated when needed for historical reporting.
- Attendance class mappings explicitly connect normalized student `class_name` values to unique instructional classes. They are separate from source-specific intake-import crosswalks. Sessions created from a published schedule retain nullable `timetable_version_id` and `instructional_class_id` provenance as a pair; existing and manually created sessions retain null provenance.
- Business records use created/updated timestamps and actor IDs.
- Normal users cannot hard-delete students, attendance or audit records.

Student intake attributes include enrolment classifications, academic-year age, academic selections, demographics and next-of-kin details. The source worksheet's S/N is a display sequence and is not a business key. Age is stored with its academic year because a workbook may contain an age snapshot that cannot be reconstructed when DOB is absent. IC, DOB, gender, nationality, citizenship, birthplace, religion, race, marital status, next-of-kin identity/contact/address and student contact fields use authenticated application encryption; API responses decrypt them only for authorized Operators.

### 6.1 Sensitive data

Classify personal identifiers, dates of birth, contact numbers, addresses and next-of-kin data as sensitive. Designated profile, roster and import fields use authenticated Fernet encryption. New ciphertext carries a non-secret key identifier; `APP_ENCRYPTION_KEY` encrypts new values and `APP_ENCRYPTION_PREVIOUS_KEYS` supplies temporary decrypt-only keys during migration. The maintenance command verifies and atomically re-encrypts all protected student profile, attendance roster and staged-import values. Existing untagged Fernet ciphertext remains readable during the migration window. Unknown key IDs and authentication failures fail closed. Encryption keys are held outside the database and source repository. Database encryption at rest, TLS database connections and encrypted backups remain required in addition to field encryption. See [ENCRYPTION_KEY_ROTATION.md](ENCRYPTION_KEY_ROTATION.md) for the runbook and backup key-retention requirements.

## 7. API conventions

Use a versioned JSON API with consistent responses:

```json
{
  "data": {},
  "errors": [],
  "requestId": "..."
}
```

Validation errors return field-level messages without revealing database details. Authorisation failures return safe `401` or `403` responses. All mutation endpoints accept an idempotency key where retries could otherwise duplicate an operation.

Representative operations:

| Area | Operations |
|---|---|
| Auth | Sign in, refresh, logout, change password, recovery |
| Students | Search, view, create, update, status history |
| Attendance | Create session, record, correct, review missing records |
| Imports | Upload, preview, validate, confirm, reject, reconcile |
| Reports | Dashboard query, export, job status, download |
| Admin | Users, roles, reference data, settings, audit search |

## 8. Intake and attendance transactions

Excel imports are staged before commit. The importer supports both `Student Intake 2021` and `Student Intake 2023` through an explicit source selector and strict year-specific header maps. It accepts bounded `.xlsx` bytes, validates the package/worksheet, reads cached formulas only in the selected age column, rejects other formulas and numeric `Pris No.`, detects duplicate identifiers, and validates profile fields. Numeric IC/NRIC/contact cells are converted from their stored number and require explicit acknowledgement of a leading-zero/precision warning. The preview exposes source year, counts and sanitized row/field errors and warnings. The source-year `CLASS` or `INSTN CLASS` resolves through its own IT-managed crosswalk; mappings use Unicode NFKC, whitespace collapse and case folding, and unknown/inactive mappings block commit. The 2021 `VERIFY` detail is encrypted; `ELECTIVE` is stored as a profile field. `CAT` and a populated academic year resolve through active catalogs; staged rows bind each reference and mapping ID/version/target and commit rechecks them under row locks. Source bytes and staged records are application-encrypted in `student_import_batches`; the creating Operator chooses create-only or explicit update-existing. The transaction rechecks profile versions and identifier conflicts, then writes all profile, status history, audit and batch changes atomically. Migration `0010` adds case/space-normalized identifier uniqueness and refuses existing collisions; `0011` adds mappings and `20261104_0019` extends them to the 2021 source without altering existing profiles or ciphertext. Migration `20261104_0018` implements configurable purging of aged encrypted payloads while preserving committed records and results. The workbook does not contain institution; the profile field is optional and controlled. Golden business reconciliation, malware scanning, business-approved retention age, separate backup/WAL expiry and workbook-report parity remain open design/release work. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md) and [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Attendance session creation captures the active class roster transactionally, including Pris No., encrypted name and status. New records must reference that immutable session roster, so later transfer, deactivation or renaming does not change a past session's eligible students or displayed identity. Correction requires a reason and preserves before/after values in the audit log. Migration `0012` backfills existing sessions only from students already present in attendance records and marks those sessions `LEGACY_PARTIAL`; it does not infer identities for unrecorded students. Monthly attendance exports use the union of session snapshots and saved marks, and explicitly label partial legacy coverage. A no-session monthly register may use the current active roster with a visible basis note. Snapshots record roster state at session creation; retrospective sessions and date-effective enrollment history still require business reconciliation.

## 9. Dashboard and reporting design

Reports query committed database records through tested views or service queries. The workbook reports `Active Breakdown`, `Active Breakdown By Categoy`, class sheets and OP/RT summaries become reconciliation specifications during migration.

The dashboard profile query supports class, institution, category, status (`ACTIVE`, `INACTIVE`, `ALL`) and academic-year filters, defaulting status to `ACTIVE`. It returns matching totals and SQL-grouped class/category/institution counts, plus age counts of 21 and under, over 21 and age not recorded. The age value is interpreted only as the snapshot paired with the profile's academic year. Attendance queries use class and date independently from current profile status/category/institution/year filters; session roster snapshots remain authoritative for historical membership.

`GET /api/v1/reports/dashboard.xlsx` accepts the dashboard filter contract and generates an authenticated workbook with Overview, Profile breakdowns and Attendance sessions sheets. The export contains aggregate profile and attendance data, omits student names and identifiers, writes free-text labels as literal strings to prevent spreadsheet formula execution, and is available only to Operator, Executive and Superuser roles. Each successful export commits an audit event containing the actor, applied filters and aggregate counts before returning the workbook. Source-workbook reconciliation and approved print-layout parity remain acceptance gates.

Every dashboard response includes filters, query completion timestamp, latest matching profile and attendance update timestamps, a combined data-through timestamp and requesting username. The current aggregate workbook is generated synchronously and streamed; persisted report jobs and expiry policies remain a follow-up for long-running exports.

## 10. Docker Compose design

The repository must contain Compose definitions for development and production-like internal deployment. Baseline services are `proxy`, `app`, `worker` and `db`, with optional test dependencies. Use separate Compose overrides rather than changing application code per environment.

Containers must use pinned versions, non-root users where supported, health checks, restart policies, resource limits and private networks. Only the proxy publishes a user-facing port. The database port is not published externally. Persistent database volumes, encrypted backup mounts and secrets are externalised. The Compose database uses Percona PostgreSQL 17 with `pg_tde`. `scripts/compose-up.sh` starts PostgreSQL and its volume-permission prerequisite, prepares provider/principal keys, converts existing user relations, enables WAL encryption and restarts the database before migrations/API startup. The `tde-setup` dependency verifies keys, WAL, default access method, enforcement and relation encryption. Production configuration uses an external Vault KV v2 provider; local file-provider keys are for development and CI only. Migrations use the separate `DATABASE_ADMIN_URL` account. After schema migration, the runner provisions `sps_runtime` with SCRAM-SHA-256 credentials and grants only table DML and sequence access; the role has no superuser, role/database administration, schema creation or role-membership privileges. Default grants cover tables and sequences created by later migrations. The API container receives only the runtime connection URL. The initial baseline migration is deliberately non-reversible to prevent accidental table/data deletion; recovery uses verified backups or forward migrations. See [POSTGRES_TDE.md](POSTGRES_TDE.md).

When `APP_ENV=production`, settings validation requires a PostgreSQL `psycopg` URL, a JWT secret and bootstrap password of at least 32 characters, and valid Fernet active/previous keys without duplicates or the development sample key. The API and migration processes use the same validation. `.env.example` values are for local development and must not be deployed as production secrets. The production Compose overlay terminates TLS in Nginx using certificate and private-key files mounted as Compose secrets; it redirects the configured hostname from HTTP, rejects unknown hostnames and sets HSTS. Host secret custody, renewal and firewall policy remain deployment controls. See [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).

## 11. CI/CD and testing design

The current pull-request workflow enforces Ruff lint/format checks, Bandit static analysis, `pip-audit`, API tests on isolated PostgreSQL, Alembic clean/repeat upgrade and model-parity checks, Python compilation, production-image build and Trivy scan, Compose configuration validation, and full-history Gitleaks scanning. Coverage is reported as an artifact while the baseline is established; no aggregate threshold is claimed yet. Dependabot proposes weekly Python and GitHub Actions updates, which must pass these same gates.

The WSL staging delivery job runs only for a `push` to `main`, after those GitHub-hosted jobs succeed. It targets the custom `sps-staging` self-hosted Linux runner and the protected GitHub `staging` environment, stages the checked-out commit in a stable release directory, builds locally with Compose and checks `/health/ready`. The Compose proxy binds to `127.0.0.1` by default. Pull request and fork jobs must never target this runner. This is a staging convenience, not an approved production release pipeline.

The TDE integration gate exercises bootstrap, conversion, enforcement, WAL and key persistence in an isolated Compose cluster. CI also starts the production Compose stack with a disposable TLS certificate and verifies readiness, HTTP redirect, hostname rejection, TLS 1.2 and security headers.

The manual production image release workflow requires successful CI and staging runs for the exact `main` commit. It builds and scans the app, proxy and maintenance images, records digests/checksums/SBOMs, and uses Cosign with GitHub OIDC to sign and verify those exact digests before creating a release. The workflow is restricted to `main` and the `MavroneBamboo` dispatch actor, and references the `production` environment. It publishes artifacts only; it does not deploy production or perform rollback. See [PRODUCTION_RELEASE.md](PRODUCTION_RELEASE.md).

Browser end-to-end workflows, timetable/import/report golden tests, production-size TDE migration, backup/restore drills, production Compose deployment and smoke tests, offline image transfer, operational rollback, and performance/security testing remain release-phase gates. Promote only the exact tested image digest and add each gate with the feature it verifies.

Tests are organised by unit, service/API, integration, end-to-end, security and migration/recovery suites. Every feature includes positive, negative, permission and audit tests where applicable. Critical workflows include bootstrap, all roles, duplicate detection, attendance correction, dashboard reconciliation and backup restore.

## 12. Observability and audit

Use structured logs with request/job correlation IDs. Never log passwords, JWTs, database credentials, encryption keys or plaintext sensitive fields. Capture application health, readiness, job failures, authentication failures, import errors and database connectivity without exposing data.

Audit events include actor, action, entity, entity ID, timestamp, outcome, request ID and safe before/after metadata. Audit history is append-only to normal application users.

## 13. Backup, recovery and deployment

The Compose `maintenance` profile runs PostgreSQL 17 `pg_dump` and `pg_restore` without publishing a database port. Backup streams are encrypted with age to a public recipient, written atomically without overwriting existing files, and can be pruned by age using a narrowly scoped filename pattern. Restore requires the private identity, an explicit host/database acknowledgement, and an empty target; `pg_restore` runs in a single transaction so authentication or restore errors roll back. The API runtime role reads backups; restore uses the administrative database role. See [DATABASE_BACKUPS.md](DATABASE_BACKUPS.md).

Production operations must schedule and monitor backups, store them outside the database host, protect a recoverable copy of the age identity, approve retention and recovery objectives, and regularly restore into an isolated environment. These controls are not provided by the one-shot Compose commands alone. Deployment runs migrations before enabling new application code, with a documented rollback strategy for both application and schema changes.

Production deployment requires a tagged, tested container artifact, approved configuration, verified backup and smoke tests for login, profile read, attendance and dashboard access. Use the TLS production overlay and keep database ports restricted throughout deployment.

## 14. Key risks and decisions

- Confirm the approved application framework and relational database.
- Confirm Active Directory availability and the final JWT/browser session pattern.
- Define the exact attendance granularity and retention rules.
- Agree field-level encryption classification and key custody process.
- Define performance targets, recovery time objective and recovery point objective.
- Resolve legacy workbook naming and formula-range issues during migration.

## 15. Timetable scheduling module

The legacy timetable system is a .NET WinForms application that converts weekly lesson requirements into a placed timetable for instructional class groups and teachers. It currently saves `.pri` project files and produces two PDF outputs: `Timetable By InstClass.pdf` and `Timetable By Teacher.pdf`.

The new application should model the timetable as first-class domain data rather than treating the PDFs as the source of truth. The legacy `.pri` format can be imported through a controlled migration adapter, but it must not be used as the production database format.

### 15.1 Timetable entities

- `timetable_versions` â€” academic period, status, owner, version and approval state.
- `teachers` â€” short code, full name, adjunct flag and availability by day/period.
- `subjects` â€” code, short code and description.
- `instructional_classes` â€” class code, description and reporting order.
- `class_clusters` and `class_cluster_members` â€” reusable groups of instructional classes.
- `period_definitions` â€” default and override period definitions, including scope, target, start/end time and schedulability.
- `scheduling_rules` and `scheduling_rule_targets` â€” versioned planning rules and their class/cluster scope.
- `lesson_requirements` â€” subject, teacher, class, weekly count and block length.
- `timetable_slots` â€” version, class, teacher, subject, weekday, period, note and lock state.
- `timetable_conflicts` â€” detected conflict type, severity, status and resolution.
- `timetable_audit_events` â€” every amendment, move, swap, removal, rename and approval.

Use stable IDs and foreign keys. Do not reproduce the legacy name-only links or list-index IDs as the production identity model. Composite teachers such as `A / B` and `ALL` require explicit membership/rule data so that conflict handling is deliberate and testable.

### 15.2 Scheduling behavior

The first generated schedule may use a deterministic greedy placement algorithm, but it must report unplaced requirements and conflicts rather than claiming success. A later solver can improve placement without changing the timetable API.

The scheduling engine must check:

- Class availability and double-booking.
- Teacher availability and double-booking.
- Required weekly lesson count.
- Consecutive-period block length.
- Locked slots and approved amendments.
- School-specific fixed events, which must be configurable rather than hard-coded.

Recurring school events are now implemented as IT/Superuser-managed timetable configuration. Each definition is scoped by academic year and targets all or selected classes/teachers at weekday and teaching-period slots. Conflicting events for overlapping targets are rejected under the shared timetable configuration lock. Draft snapshots capture the event definition and resolved target IDs, so a later event edit makes an unapproved draft stale. The shared manual validator and automatic generator reserve those class/teacher slots against lesson placement; the browser and PDF/XLSX views display the event label in the reserved cell. Period 3 lunch remains the separate non-schedulable period. See [TIMETABLE_FIXED_EVENTS.md](TIMETABLE_FIXED_EVENTS.md).

Scheduling cannot start without a complete rule resolution. Each class included in a plan must resolve to exactly one active rule set for the academic period and effective date. The API must reject missing rules, duplicate rules, overlapping class/cluster targets and duplicate lesson placements; it must never select one rule arbitrarily.

Generation must create a new draft version or require an explicit replacement confirmation. It must never silently destroy an approved timetable.

### 15.3 Amend 4-up workspace

The production timetable browser follows the supplied redesign with a navy timetable sidebar and four sections: weekly timetable, reports/export, classes/teachers, and periods/rules. The weekly board toggles By class and By teacher. Amend 4-up supports the legacy page sizes 2/4/6/8/12/16/24/32, with denser compact tables for 12 or more classes.

Required interactions:

- Toggle By Class / By Teacher.
- Search class code, teacher code or teacher full name.
- Previous/next page.
- Click a populated cell to open the lesson form for amendment.
- Click an empty teaching cell to add a lesson after validating subject, teacher, class, availability and clashes.
- Select two unlocked lesson blocks and exchange their weekday/start positions through one revision-checked, full-grid-validated swap request.
- Drag an unlocked lesson to an empty teaching slot in the same class to move it, or onto another unlocked lesson in that class to swap them; validate the resulting full plan before saving.
- Open a lesson to change its weekday/start period or remove it; these actions remain keyboard-accessible and do not depend on context-menu gestures.
- Use the draft header's Rename action to submit a controlled rename.
- Lock/unlock a slot.
- Save amendments directly to the current draft and record an audit event.
- Return to the normal Schedule view without losing amendments.

The current browser implements cell click-to-add/edit, remove, lock/unlock, bounded generation, approval, explicit two-block swap, single-block move, drag/drop and draft rename. Move and rename requests include the current revision; the API rejects locked/non-draft changes, validates the entire resulting grid and commits one audit event. The lesson editor provides a keyboard-accessible alternative to dragging.

The UI must use the real weekday and period represented by each row/cell. The displayed order is P1, P2, P3 Lunch/Muster, P4, P5; existing API codes remain P1, P2, LUNCH, P3, P4 in that display order. Lunch is rendered for report alignment and rejects placement and edits.

### 15.4 PDF/report output

The browser report screen offers class and teacher report actions from the opened timetable version using a print-ready view that can be saved as PDF. A later reporting service should generate both official formats server-side from the same approved version:

- By Instructional Class: one page per eligible class group, showing subject and teacher.
- By Teacher: one page per teacher, showing subject and instructional class.

The export must be immutable/versioned, must not mutate shared timetable data while rendering, and must include the academic period, timetable version and generation timestamp. The latest supplied PDFs are acceptance references for layout and content.

### 15.5 Integration with student and attendance data

Instructional classes are not individual students. The timetable module links to the student/attendance domain through the controlled class reference. A class used in attendance must be mapped to its timetable instructional class where applicable. Changes to class definitions must be effective-dated and audited so historical attendance and timetable reports remain reproducible.

Operators manage timetable drafts and attendance sessions. IT Administrators manage reference data and conflict rules. Executives receive read-only approved timetable views and exports.

### 15.6 Resource setup and teacher profiles

Resource setup is a prerequisite to lesson scheduling. The application must provide controlled management for:

- Teacher profiles: stable ID, unique short code, full name, adjunct flag, active/effective dates and normalized availability. Composite profiles have a normalized member relation to individual teachers; nested groups are invalid. Snapshots preserve group membership and member availability so both the planner and PostgreSQL guard detect individual/group and group/group conflicts.
- Subjects: name, short code and description.
- Instructional classes: name, short name, description and reporting order.
- Class clusters: named groups of instructional classes used for shared period overrides.
- Period definitions: a default pattern inherited by all classes, plus effective-dated class or cluster overrides. `P3` is reserved for lunch and remains non-schedulable.
- Lesson requirements: subject, teacher, instructional class, weekly count and block length.

Scheduling rules are mandatory reference data for every planning run. Rules must be versioned and scoped to a class or cluster, with one unambiguous active rule per class and effective period. Duplicate or overlapping rules are invalid and must be blocked at the database and service layers.

A teacher profile is not an application login account. The Operator uses a teacher profile in a lesson; the IT Administrator controls reference data; the Executive only views approved outputs. A teacher may be unavailable for a slot even when the Operator is allowed to edit the timetable.

The lesson API must resolve references by stable IDs, validate weekly counts and block lengths, and reject inactive or unavailable resources. The scheduler and Amend 4-up editor must call the same conflict/availability service. If a teacher short code changes, the change must be audited and all related lesson references must remain intact.

Legacy availability migration requires an explicit conversion from the current 20-position string to four teaching periods per day, with the lunch column inserted only for visual alignment. The conversion must record the mapping and any exceptions.

#### First API/schema delivery

The production timetable UI exposes teachers, subjects, instructional classes, clusters, period definitions and scheduling rules through resource tabs and a dedicated periods/rules section. It supports editing default period times and creating class/cluster overrides. API configuration writes are restricted to IT Administrators and Superusers and audited. Teacher availability uses weekday keys MON–FRI and only the four teaching slots; lunch is not an availability slot. Superusers retain full access; Executives can only view approved timetable versions.

The current product-owner-directed display pattern is `P1`, `P2`, `Lunch`, `P3`, `P4`, with lunch at display position 3 and non-schedulable. The latest legacy code instead models five teaching periods (`P1`â€“`P5`) and its PDF overlays â€œLunch / Masterâ€ at the P3 time; the replacement intentionally follows the explicit product-owner lunch rule, so direct legacy slot parity remains an import/reconciliation decision. Default times are seeded from the legacy documentation. Class-specific overrides take precedence over the single cluster override, which takes precedence over the default slot. A class may belong to only one cluster so two cluster period patterns cannot ambiguously apply. Duplicate code, membership and scope/slot definitions are rejected by both service checks and database constraints; resolved time intervals are also checked for overlaps. The browser now creates teacher/subject/class/cluster resources, memberships, period overrides, rules and lesson requirements. Resource edit/deactivation remains future work.

#### Lesson-requirement delivery

`lesson_requirements` stores stable teacher, subject and instructional-class foreign keys, a normalized academic year, total weekly count (1â€“20), block length (1â€“4), active state, edit version and audit ownership. A database unique constraint prevents duplicate academic-year/class/teacher/subject combinations even after archival; restoration uses the existing row. Numeric limits and resource foreign keys are also database constraints.

Authenticated Operators, IT Administrators and Superusers can create, list, retrieve, replace, archive and restore requirements at `/api/v1/timetable/lessons`. Executives are read-only and can view approved timetable versions.

Period and cluster-membership changes revalidate active requirements. A shared PostgreSQL transaction advisory lock coordinates those changes with lesson creation/edit/archive across API workers, preventing a concurrent period edit and lesson save from jointly committing an invalid configuration. SQLite is for development and does not provide that coordination proof. CI exercises PostgreSQL race/constraint tests plus an additive-schema preservation rehearsal on SQLite. The shared period/lesson validation services are intended for reuse by generation and Amend 4-up.

#### Scheduling-rule resolution delivery

Rules now use explicit class/cluster foreign keys, effective date windows and atomic edit versions. Definition schema version 1 validates allowed weekdays, allowed teaching slots and maximum daily lessons. IT Administrators own writes; Operators can read and resolve. The shared bulk resolver returns one validated rule per active class or rejects the entire request for missing/ambiguous rules, invalid definitions or unresolved legacy targets. Class rules do not override cluster rules: any shared scope/date overlap is an error.

PostgreSQL statement/row triggers coordinate rule and membership writes through the shared transaction lock, rejecting overlap even for direct SQL callers. The app uses READ COMMITTED and triggers reject unsupported isolation levels. Revision 0004 preserves unresolved legacy rows for explicit reconciliation. Draft editing, generation, By class/By teacher browser boards and Amend 4-up consume shared validation services. Atomic swap, single-block move and rename controls use expected-revision checks and audited transactions; drag/drop submits only a destination and cannot bypass full-grid validation. Publishing coordination is implemented; server PDF output and other parity work remain outstanding.

#### Timetable draft and placement delivery

Revision `0005` introduces `timetable_versions`, selected-class links, lesson blocks and normalized occupied slots. New drafts snapshot current requirements/resources/periods and resolved rules for each weekday of a Monday-based week. Every mutation checks configuration currentness and the expected draft revision, validates the full proposed grid and commits the block/cell changes with an audit event. Shared validation enforces block/remainder quantities, lunch/gap exclusion, allowed days/periods, daily limits, availability and actual-time teacher/class conflicts. Swaps validate both directions before replacing either block's cells.

PostgreSQL guards enforce snapshot/class-selection immutability, occupied-cell uniqueness, actual-time clashes, snapshotted cell resource/time values, locked blocks and approved records. Composite groups use normalized member rows; snapshots freeze each member and availability, and both the API validator and slot trigger check member-level clashes. Full-grid reads use the transaction lock for consistent header/cell revisions. IT Administrators and Superusers can approve only complete, current drafts; Executives can read approved versions. Historical rendering uses snapshots. Automatic generation and weekly publication use the same validations and transaction services; see [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md). The browser offers By class/By teacher weekly views, clickable Amend 4-up, revision-guarded swaps and single-block moves, audited draft rename, browser print-to-PDF reports, resource tabs, period/rule management and configurable recurring fixed events. Published timetable classes can be consumed by attendance through IT-managed mapping and provenance-linked sessions. Draft copy/rebase, server-side PDF output and legacy `.pri` composite-group reconciliation remain to implement. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).
