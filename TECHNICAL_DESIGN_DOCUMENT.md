# SPS Student Dashboard

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

### 6.1 Sensitive data

Classify personal identifiers, dates of birth, contact numbers, addresses and next-of-kin data as sensitive. Use application-level authenticated encryption for designated fields, with key version metadata. Encryption keys are held outside the database and source repository. Database encryption at rest, TLS database connections and encrypted backups remain required in addition to field encryption.

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

Excel imports are staged before commit. The pipeline validates file type, required headers, reference values, duplicate `Pris No.`, date formats, status values and class mappings. The operator sees a preview and row-level errors. Confirmation commits the batch in one transaction or rejects it without partial business updates.

Attendance writes validate student eligibility, session date, class consistency and duplicate records. Corrections require a reason and preserve the before/after values in the audit log.

## 9. Dashboard and reporting design

Reports query committed database records through tested views or service queries. The workbook reports `Active Breakdown`, `Active Breakdown By Categoy`, class sheets and OP/RT summaries become reconciliation specifications during migration.

Every dashboard response includes filters, result timestamp, data-through timestamp and requesting user. Report exports are generated by the backend/worker, stored with an expiry policy and authorised before download.

## 10. Docker Compose design

The repository must contain Compose definitions for development and production-like internal deployment. Baseline services are `proxy`, `app`, `worker` and `db`, with optional test dependencies. Use separate Compose overrides rather than changing application code per environment.

Containers must use pinned versions, non-root users where supported, health checks, restart policies, resource limits and private networks. Only the proxy publishes a user-facing port. The database port is not published externally. Persistent database volumes, encrypted backup mounts and secrets are externalised.

## 11. CI/CD and testing design

Pull requests run formatting, linting, static analysis, unit tests, API/integration tests, end-to-end tests, migration tests, Compose startup checks, dependency scanning, container scanning, secret scanning and coverage thresholds. The exact artifact promoted to production must be the artifact tested in CI.

Tests are organised by unit, service/API, integration, end-to-end, security and migration/recovery suites. Every feature includes positive, negative, permission and audit tests where applicable. Critical workflows include bootstrap, all roles, duplicate detection, attendance correction, dashboard reconciliation and backup restore.

## 12. Observability and audit

Use structured logs with request/job correlation IDs. Never log passwords, JWTs, database credentials, encryption keys or plaintext sensitive fields. Capture application health, readiness, job failures, authentication failures, import errors and database connectivity without exposing data.

Audit events include actor, action, entity, entity ID, timestamp, outcome, request ID and safe before/after metadata. Audit history is append-only to normal application users.

## 13. Backup, recovery and deployment

Backups are encrypted, stored separately from the database host and regularly restored in a test environment. Deployment runs migrations before enabling new application code, with a documented rollback strategy for both application and schema changes.

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

Generation must create a new draft version or require an explicit replacement confirmation. It must never silently destroy an approved timetable.

### 15.3 Amend 4-up workspace

Amend 4-up is the main timetable editing surface. It displays multiple class or teacher mini-grids on one page, with Monday–Friday rows and five period columns. The page density is selectable (for example 2, 4, 6, 8, 12, 16, 24 or 32 tables per page).

Required interactions:

- Toggle By Class / By Teacher.
- Search class code, teacher code or teacher full name.
- Previous/next page.
- Double-click a cell to edit subject/teacher or class.
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

A teacher profile is not an application login account. The Operator uses a teacher profile in a lesson; the IT Administrator controls reference data; the Executive only views approved outputs. A teacher may be unavailable for a slot even when the Operator is allowed to edit the timetable.

The lesson API must resolve references by stable IDs, validate weekly counts and block lengths, and reject inactive or unavailable resources. The scheduler and Amend 4-up editor must call the same conflict/availability service. If a teacher short code changes, the change must be audited and all related lesson references must remain intact.

Legacy availability migration requires an explicit conversion from the current 20-position string to four teaching periods per day, with the lunch column inserted only for visual alignment. The conversion must record the mapping and any exceptions.
