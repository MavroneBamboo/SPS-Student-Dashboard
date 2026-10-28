# SPS Student Dashboard

Sign-in rate-limit increment (27 October 2026): the Nginx reverse proxy applies a per-client-IP limit to `POST /api/v1/auth/login` and responds with HTTP 429 when a burst exceeds the configured threshold. CI validates the Nginx config and starts a local mock upstream to verify actual throttling. This is network-level protection; account-level lockout and distributed abuse controls remain follow-up work.


Monthly attendance export increment (27 October 2026): `GET /api/v1/reports/attendance/monthly.xlsx` generates an authenticated, class-and-month scoped `.xlsx` register for Operators and Executives. It mirrors the legacy AM/PM day columns, includes current active students, writes `P/A/L/E/M` for present/absent/late/excused/missing, leaves unrecorded sessions blank, and sets print scaling, repeated headers and frozen roster columns. Dashboard form initiates the download without exposing the bearer token in the URL, and cancels the request when the user signs out. API and browser tests cover the endpoint and download. This is a current-roster view; historical enrollment snapshots and exact legacy formula/color parity remain follow-up work.

Operational permission increment (26 October 2026): all student and attendance routes now enforce Operator server-side; dashboard and attendance CSV enforce Operator/Executive, while audit uses Superuser/IT Administrator. API tests exercise every role across reads and writes. See [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md) for the exact matrix and remaining authorization work.

Identity increment (26 October 2026): migration `0008` preserves accounts while adding token versions and case-insensitive username uniqueness. JWT validation requires a version and live active user; PostgreSQL advisory locking serializes account mutations and last-administrator checks. IT Administrators manage named accounts except Superusers. Password reset and logout revoke all tokens for one account. See [IDENTITY_SECURITY.md](IDENTITY_SECURITY.md); full permission separation, setup/recovery and deployment security remain required.

Attendance increment (26 October 2026): migration `0007` preserves attendance while adding session/record versions and class/date/type uniqueness, refusing ambiguous legacy sessions before DDL. PostgreSQL session/student row locks, required expected versions, immutable record identity, correction reasons and audited incomplete closure/count adjustments protect browser operations. Raw attendance APIs deny Executive access; historical roster/reconciliation and complete permission separation remain release work. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

Profile/import increment (28 October 2026): migration `0009` adds student intake attributes, `0010` adds encrypted source/staging storage, and `0011` adds the controlled 2023 intake-class crosswalk. Profile create/read/update and the Operator browser support academic, demographic and next-of-kin fields. The 2023 intake worksheet resolves source class labels to active instructional classes through IT-managed, versioned mappings; imports preview and commit in create-only or explicit update-existing mode with stale-mapping/profile checks and atomic audit/history writes. Category/institution catalogs, 2021 mapping and retention controls remain follow-up work. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md) and [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

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
┌──────────────┐       HTTPS        ┌───────────────────┐
│ Browser users│ ───────────────────▶│ Reverse proxy     │
└──────────────┘                     │ TLS + headers     │
                                     └─────────┬─────────┘
                                               │
                                               ▼
                                     ┌───────────────────┐
                                     │ Web/API application│
                                     │ Auth + business    │
                                     │ rules + reports    │
                                     └─────┬───────┬─────┘
                                           │       │
                                           ▼       ▼
                                   ┌──────────┐ ┌──────────┐
                                   │ Database │ │ Worker   │
                                   │ encrypted│ │ imports/ │
                                   │ storage  │ │ exports  │
                                   └──────────┘ └──────────┘
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

Installation creates a setup-state superuser with a one-time secret. On first use, the system requires a credential change and creation of a named IT Administrator. The setup state must block normal operation until completed. The bootstrap account is disabled or rotated after setup, and recovery requires audited server-level IT action.

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
- `attendance_sessions`, `attendance_records`
- `import_batches`, `import_rows`, `export_jobs`
- `audit_log`, `system_settings`

Important rules:

- `students.pris_no` is the preferred unique business identifier.
- Name-only matching is not allowed for an automatic update when duplicates exist.
- Attendance uniqueness is enforced by student, session and date according to the agreed attendance policy.
- Status changes are recorded as history; historical records are not silently overwritten.
- Reference data is effective-dated when needed for historical reporting.
- Business records use created/updated timestamps and actor IDs.
- Normal users cannot hard-delete students, attendance or audit records.

Student intake attributes include enrolment classifications, academic-year age, academic selections, demographics and next-of-kin details. The source worksheet's S/N is a display sequence and is not a business key. Age is stored with its academic year because a workbook may contain an age snapshot that cannot be reconstructed when DOB is absent. IC, DOB, gender, nationality, citizenship, birthplace, religion, race, marital status, next-of-kin identity/contact/address and student contact fields use authenticated application encryption; API responses decrypt them only for authorized Operators.

### 6.1 Sensitive data

Classify personal identifiers, dates of birth, contact numbers, addresses and next-of-kin data as sensitive. Designated profile fields currently use authenticated Fernet encryption via the external `APP_ENCRYPTION_KEY`. The current ciphertext format does not include an explicit key identifier; versioned key rotation and ciphertext migration remain required. Encryption keys are held outside the database and source repository. Database encryption at rest, TLS database connections and encrypted backups remain required in addition to field encryption.

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

Excel imports are staged before commit. The implemented `Student Intake 2023` path accepts bounded `.xlsx` bytes, validates the package and required headers, accepts only cached formulas in `AGE IN AY'23`, rejects other formulas and numeric `Pris No.`, detects duplicate identifiers, and validates profile fields. Numeric IC/NRIC/contact cells are converted from their stored number and require explicit acknowledgement of a leading-zero/precision warning. The preview exposes counts and sanitized row/field errors and warnings. `INSTN CLASS` resolves through an IT-managed crosswalk whose source labels are normalized with Unicode NFKC, whitespace collapse and case folding; unknown/inactive mappings block commit. The preview records mapping identity/version and canonical target, and commit rechecks the mapping and active instructional class under row locks. Source bytes and staged records are application-encrypted in `student_import_batches`; the creating Operator chooses create-only or explicit update-existing. The transaction rechecks profile versions and identifier conflicts, then writes all profile, status history, audit and batch changes atomically. Migration `0010` adds case/space-normalized identifier uniqueness and refuses existing collisions for explicit reconciliation; `0011` adds mappings without altering existing profile values. Category/institution catalogs, the 2021 sheet, malware scanning, retention policy and workbook-report parity remain open design/release work. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

Attendance writes validate student eligibility, session date, class consistency and duplicate records. Corrections require a reason and preserve the before/after values in the audit log.

## 9. Dashboard and reporting design

Reports query committed database records through tested views or service queries. The workbook reports `Active Breakdown`, `Active Breakdown By Categoy`, class sheets and OP/RT summaries become reconciliation specifications during migration.

Every dashboard response includes filters, result timestamp, data-through timestamp and requesting user. Report exports are generated by the backend/worker, stored with an expiry policy and authorised before download.

## 10. Docker Compose design

The repository must contain Compose definitions for development and production-like internal deployment. Baseline services are `proxy`, `app`, `worker` and `db`, with optional test dependencies. Use separate Compose overrides rather than changing application code per environment.

Containers must use pinned versions, non-root users where supported, health checks, restart policies, resource limits and private networks. Only the proxy publishes a user-facing port. The database port is not published externally. Persistent database volumes, encrypted backup mounts and secrets are externalised. The current Compose stack runs PostgreSQL health checks, then a one-shot Alembic migration service, then starts the API; the API must not create or alter schema at runtime. Migrations use the separate `DATABASE_ADMIN_URL` account. After schema migration, the runner provisions `sps_runtime` with SCRAM-SHA-256 credentials and grants only table DML and sequence access; the role has no superuser, role/database administration, schema creation or role-membership privileges. Default grants cover tables and sequences created by later migrations. The API container receives only the runtime connection URL. The initial baseline migration is deliberately non-reversible to prevent accidental table/data deletion; recovery uses verified backups or forward migrations.

## 11. CI/CD and testing design

The current pull-request workflow enforces Ruff lint/format checks, Bandit static analysis, `pip-audit`, API tests on isolated PostgreSQL, Alembic clean/repeat upgrade and model-parity checks, Python compilation, production-image build and Trivy scan, Compose configuration validation, and full-history Gitleaks scanning. Coverage is reported as an artifact while the baseline is established; no aggregate threshold is claimed yet. Dependabot proposes weekly Python and GitHub Actions updates, which must pass these same gates.

The WSL staging delivery job runs only for a `push` to `main`, after those GitHub-hosted jobs succeed. It targets the custom `sps-staging` self-hosted Linux runner and the protected GitHub `staging` environment, stages the checked-out commit in a stable release directory, builds locally with Compose and checks `/health/ready`. The Compose proxy binds to `127.0.0.1` by default. Pull request and fork jobs must never target this runner. This is a staging convenience, not an approved production release pipeline.

This is the CI foundation, not the complete release pipeline. Frontend/browser end-to-end tests, timetable/import/report golden tests, Compose runtime smoke tests, backup/restore drills, artifact signing/publication, deployment approvals and performance/security testing remain feature- or release-phase gates. Add each gate with the feature it verifies; promote only the exact tested artifact once a release workflow exists.

Tests are organised by unit, service/API, integration, end-to-end, security and migration/recovery suites. Every feature includes positive, negative, permission and audit tests where applicable. Critical workflows include bootstrap, all roles, duplicate detection, attendance correction, dashboard reconciliation and backup restore.

## 12. Observability and audit

Use structured logs with request/job correlation IDs. Never log passwords, JWTs, database credentials, encryption keys or plaintext sensitive fields. Capture application health, readiness, job failures, authentication failures, import errors and database connectivity without exposing data.

Audit events include actor, action, entity, entity ID, timestamp, outcome, request ID and safe before/after metadata. Audit history is append-only to normal application users.

## 13. Backup, recovery and deployment

The Compose `maintenance` profile runs PostgreSQL 17 `pg_dump` and `pg_restore` without publishing a database port. Backup streams are encrypted with age to a public recipient, written atomically without overwriting existing files, and can be pruned by age using a narrowly scoped filename pattern. Restore requires the private identity, an explicit host/database acknowledgement, and an empty target; `pg_restore` runs in a single transaction so authentication or restore errors roll back. The API runtime role reads backups; restore uses the administrative database role. See [DATABASE_BACKUPS.md](DATABASE_BACKUPS.md).

Production operations must schedule and monitor backups, store them outside the database host, protect a recoverable copy of the age identity, approve retention and recovery objectives, and regularly restore into an isolated environment. These controls are not provided by the one-shot Compose commands alone. Deployment runs migrations before enabling new application code, with a documented rollback strategy for both application and schema changes.

Production deployment requires a tagged, tested container artifact, approved configuration, verified backup and smoke tests for login, profile read, attendance and dashboard access. Database ports remain restricted throughout deployment.

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

- `timetable_versions` — academic period, status, owner, version and approval state.
- `teachers` — short code, full name, adjunct flag and availability by day/period.
- `subjects` — code, short code and description.
- `instructional_classes` — class code, description and reporting order.
- `class_clusters` and `class_cluster_members` — reusable groups of instructional classes.
- `period_definitions` — default and override period definitions, including scope, target, start/end time and schedulability.
- `scheduling_rules` and `scheduling_rule_targets` — versioned planning rules and their class/cluster scope.
- `lesson_requirements` — subject, teacher, class, weekly count and block length.
- `timetable_slots` — version, class, teacher, subject, weekday, period, note and lock state.
- `timetable_conflicts` — detected conflict type, severity, status and resolution.
- `timetable_audit_events` — every amendment, move, swap, removal, rename and approval.

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

Scheduling cannot start without a complete rule resolution. Each class included in a plan must resolve to exactly one active rule set for the academic period and effective date. The API must reject missing rules, duplicate rules, overlapping class/cluster targets and duplicate lesson placements; it must never select one rule arbitrarily.

Generation must create a new draft version or require an explicit replacement confirmation. It must never silently destroy an approved timetable.

### 15.3 Amend 4-up workspace

Amend 4-up is the main timetable editing surface. It displays multiple class or teacher mini-grids on one page, with Monday–Friday rows and five period columns. The page density is selectable (for example 2, 4, 6, 8, 12, 16, 24 or 32 tables per page).

Required interactions:

- Toggle By Class / By Teacher.
- Search class code, teacher code or teacher full name.
- Previous/next page.
- Double-click a cell to edit subject/teacher or class.
- Click an empty teaching cell to create a placed lesson after validating subject, teacher, class, availability and clashes.
- Drag a lesson to another slot; validate the destination and swap only when both moves are valid.
- Right-click a lesson to shift or remove it.
- Double-click a title to request a controlled rename.
- Lock/unlock a slot.
- Save amendments directly to the current draft and record an audit event.
- Return to the normal Schedule view without losing amendments.

The UI must use the real weekday and period represented by each row/cell, not its current sorted index. This prevents a known legacy failure where editing after sorting changed a different day. The current school layout is five displayed columns—`P1`, `P2`, `Lunch`, `P3`, `P4`—but only four are schedulable teaching periods. The lunch column is rendered for report alignment and must reject lesson drops and edits.

### 15.4 PDF/report output

The reporting service generates both current formats from the same approved timetable version:

- By Instructional Class: one page per eligible class group, showing subject and teacher.
- By Teacher: one page per teacher, showing subject and instructional class.

The export must be immutable/versioned, must not mutate shared timetable data while rendering, and must include the academic period, timetable version and generation timestamp. The latest supplied PDFs are acceptance references for layout and content.

### 15.5 Integration with student and attendance data

Instructional classes are not individual students. The timetable module links to the student/attendance domain through the controlled class reference. A class used in attendance must be mapped to its timetable instructional class where applicable. Changes to class definitions must be effective-dated and audited so historical attendance and timetable reports remain reproducible.

Operators manage timetable drafts and attendance sessions. IT Administrators manage reference data and conflict rules. Executives receive read-only approved timetable views and exports.

### 15.6 Resource setup and teacher profiles

Resource setup is a prerequisite to lesson scheduling. The application must provide controlled management for:

- Teacher profiles: stable ID, unique short code, full name, adjunct flag, active/effective dates and normalized availability.
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

The initial timetable-resource API slice is now implemented behind authenticated `/api/v1/timetable` endpoints: teacher, subject, instructional-class and cluster creation/listing; one-cluster-per-class membership; seeded default periods; class/cluster period overrides; and resolved periods for a class. Resource codes are normalized to uppercase and unique. Teacher availability uses weekday keys `MON`–`FRI` and only teaching slots `P1`–`P4`; lunch is not a teacher-availability slot. Writes are restricted to IT Administrators and audited; Superusers remain bootstrap/recovery identities, while Executives can read but cannot change resources.

The current product-owner-directed display pattern is `P1`, `P2`, `Lunch`, `P3`, `P4`, with lunch at display position 3 and non-schedulable. The latest legacy code instead models five teaching periods (`P1`–`P5`) and its PDF overlays “Lunch / Master” at the P3 time; the replacement intentionally follows the explicit product-owner lunch rule, so direct legacy slot parity remains an import/reconciliation decision. Default times are seeded from the legacy documentation. Class-specific overrides take precedence over the single cluster override, which takes precedence over the default slot. A class may belong to only one cluster so two cluster period patterns cannot ambiguously apply. Duplicate code, membership and scope/slot definitions are rejected by both service checks and database constraints; resolved time intervals are also checked for overlaps. The browser now creates teacher/subject/class/cluster resources, memberships, period overrides, rules and lesson requirements. Resource edit/deactivation remains future work.

#### Lesson-requirement delivery

`lesson_requirements` stores stable teacher, subject and instructional-class foreign keys, a normalized academic year, total weekly count (1–20), block length (1–4), active state, edit version and audit ownership. A database unique constraint prevents duplicate academic-year/class/teacher/subject combinations even after archival; restoration uses the existing row. Numeric limits and resource foreign keys are also database constraints.

Authenticated Operators and IT Administrators can create, list, retrieve, replace, archive and restore requirements at `/api/v1/timetable/lessons`. Executives and bootstrap Superusers cannot access draft requirements. Replacement and archival use an atomic version predicate; stale writes return 409 without an audit entry or data loss. Writes and audit events commit together. The initial implementation checks each requirement against active resources, resolved class periods and teacher availability. Full blocks plus a shorter remainder preserve the exact weekly total, matching legacy count splitting. Availability, lunch and configured time gaps split contiguous runs; disjoint block packing prevents reusing a period. This does not prove that all requirements can be scheduled together: collective workloads, rule completeness and class/teacher clashes remain scheduler checks.

Period and cluster-membership changes revalidate active requirements. A shared PostgreSQL transaction advisory lock coordinates those changes with lesson creation/edit/archive across API workers, preventing a concurrent period edit and lesson save from jointly committing an invalid configuration. SQLite is for development and does not provide that coordination proof. CI exercises PostgreSQL race/constraint tests plus an additive-schema preservation rehearsal on SQLite. The shared period/lesson validation services are intended for reuse by generation and Amend 4-up.

#### Scheduling-rule resolution delivery

Rules now use explicit class/cluster foreign keys, effective date windows and atomic edit versions. Definition schema version 1 validates allowed weekdays, allowed teaching slots and maximum daily lessons. IT Administrators own writes; Operators can read and resolve. The shared bulk resolver returns one validated rule per active class or rejects the entire request for missing/ambiguous rules, invalid definitions or unresolved legacy targets. Class rules do not override cluster rules: any shared scope/date overlap is an error.

PostgreSQL statement/row triggers coordinate rule and membership writes through the shared transaction lock, rejecting overlap even for direct SQL callers. The app uses READ COMMITTED and triggers reject unsupported isolation levels. Revision `0004` preserves old text-only rows as unresolved; IT must explicitly bind/archive applicable rows before planning. Rule and membership service checks also run in development SQLite, while PostgreSQL is required for database-level concurrency guarantees. See [SCHEDULING_RULES.md](SCHEDULING_RULES.md) for the complete API, reconciliation and concurrency contract. Draft editing, generation and an initial class-oriented Amend 4-up browser now consume the shared services. Teacher-oriented grids, swap/drag controls, exports and publishing coordination remain outstanding.

#### Timetable draft and placement delivery

Revision `0005` introduces `timetable_versions`, selected-class links, lesson blocks and normalized occupied slots. New drafts snapshot current requirements/resources/periods and resolved rules for each weekday of a Monday-based week. Every mutation checks configuration currentness and the expected draft revision, validates the full proposed grid and commits the block/cell changes with an audit event. Shared validation enforces block/remainder quantities, lunch/gap exclusion, allowed days/periods, daily limits, availability and actual-time teacher/class conflicts. Swaps validate both directions before replacing either block's cells.

PostgreSQL guards enforce snapshot/class-selection immutability, occupied-cell uniqueness, actual-time clashes, snapshotted cell resource/time values, locked blocks and approved records. Full-grid reads use the transaction lock for consistent header/cell revisions. IT Administrators can approve only complete, current drafts; Executives can read approved versions. Historical rendering uses snapshots. Automatic generation uses the same validations and transaction services; see [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md). The browser currently pages through 4/8/12/16 class grids, renders the non-editable lunch column, and supports manual block changes, generation and IT approval. Published-version coordination, draft copy/rebase, teacher-oriented grids, drag/swap controls, composite teachers, fixed events and exports remain to implement. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).
