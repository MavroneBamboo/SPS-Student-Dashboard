# SPS Student Dashboard

Amend 4-up follow-up (6 November 2026): the API adds an audited draft-rename action and a revision-guarded single-block move endpoint. The browser supports legacy page sizes 2/4/6/8/12/16/24/32, drag/drop to an empty slot, and drag/drop swaps onto another unlocked block in the same class; keyboard-accessible movement remains available through the lesson editor. These actions use the full-grid validator; locked blocks and approved versions remain immutable. API and Chromium CI cover success, stale revisions, conflicts and audit history. Broader legacy parity and release recovery checks remain outstanding.

Current timetable UI status (6 November 2026): the production browser follows the supplied redesign with By class/By teacher boards, Amend 4-up, browser print-to-PDF reports, teacher/class/subject tabs, default/class/cluster period editing, revision-guarded swaps and moves, and draft rename. Superuser has full application access. Source-workbook reconciliation, remaining legacy interactions, server-side PDF output and full deployment/recovery verification remain follow-up items. Earlier delivery notes below describe prior increments.

Operational permissions follow-up (26 October 2026): the server now restricts student/attendance reads and writes to Operators; only Operators/Executives can read the dashboard or attendance CSV, and only Superuser/IT Administrator can read audit. See [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md). Timetable permissions, setup/recovery and export policy remain separate release checks.

Identity follow-up (6 November 2026): account changes and administrator resets revoke every token through the live account version. Login-issued tokens have append-only session creation/revocation events; the API lists active sessions, revokes one session or all other sessions, and rejects revoked tokens on each authenticated request. The browser provides an Account sessions screen, and sign-out revokes its current session. Migration `0008` adds token versions and lowercase username uniqueness, with an explicit duplicate reconciliation gate. Sign-in audit events drive a five-failures/15-minute account cooldown; PostgreSQL serializes login attempts by account, correct credentials remain usable during cooldown, and successful sign-in resets the failure sequence. Distributed abuse detection, TLS/secret handling, production session/deployment verification and backup/restore remain required. See [IDENTITY_SECURITY.md](IDENTITY_SECURITY.md).

Attendance follow-up (28 October 2026): Operator browser and APIs support versioned daily sessions/records, corrections, missing review, count controls and closure with audit and row locking. Migration `0012` captures encrypted rosters for new sessions; migrated sessions are marked `LEGACY_PARTIAL` and contain only students with recorded attendance. Monthly exports use captured identities and label their roster basis. Session-creation snapshots do not reconstruct membership for retrospective sessions; date-effective enrollment reconciliation, full-day granularity policy, reopening/corrections, visual/formula parity and complete permissions remain required. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

Profile/import increment (28 October–4 November 2026): migrations `0009`–`0011` add extended profile data, encrypted intake staging and versioned class mappings; `20261104_0018` adds encrypted-payload retention; `20261104_0019` adds support for both 2021 and 2023 intake sheets, version-separated class mappings and source-year import batch metadata. The Operator selects a sheet explicitly, inspects sanitized errors, and commits create-only or explicit update-existing changes atomically; changed mappings invalidate old previews. The 2021-only `VERIFY` field is encrypted and `ELECTIVE` is retained. Migrations `0016` and `0017` enforce active category, academic-year, and optional institution values with catalog-version checks at commit. Full report reconciliation, historical corrections, support/operational permission separation and production-scale search remain required. Database backup/WAL expiry remains separately managed. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md), [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md), and [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Student reference catalog increment (4 November 2026): versioned, audited IT/Superuser catalog administration for categories, institutions, and academic years is available under **Reference data**. Migration `20261104_0016` follows first-run setup migration `20261104_0015` and backfills existing category and academic-year labels without changing student or timetable records. The profile/reference integration adds controlled profile writes, optional institution storage, import snapshot validation, and institution reporting. Remaining work includes reconciliation of legacy labels that are not present in the catalogs. See [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

Student profile reference integration (4 November 2026): migration `20261104_0017` adds optional institution to Student. Profile writes use active catalog values for categories, academic years and institution; imports validate category/year at preview and recheck version/activity at commit. Institution is optional/manual because it is absent from the supplied workbook sheets. Dashboard/profile lists provide institution breakdown and filtering. Existing archived values remain readable and unchanged unless explicitly replaced. Remaining profile work includes institution source/reconciliation policy and broader historical attendance reconciliation.

Browser follow-up (26 October 2026; updated 6 November): `/ui/` provides real sign-in, mandatory password change, Superuser account administration, committed-data dashboards, Operator profile/attendance workspaces and a class-oriented timetable workspace. The timetable UI supports IT reference setup, draft creation, clickable placement/edit/remove/lock, generation, atomic swap and move, audited draft rename and IT approval; Chromium CI covers these workflows. Imports/exports, complete setup/recovery, HTTPS and session hardening remain separate release work. See [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md) and [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).

Generation follow-up (3 November 2026; updated 6 November): the weekly draft API and browser provide deterministic generation with bounded repair, preserved manual/locked blocks, explicit replace-unlocked mode and atomic grid/revision/audit reports. Shared manual-placement validation remains authoritative. Partial results expose every pending block and cannot pass approval. Amend 4-up supports full-grid-validated swaps and single-block moves, drag/drop movement, and audited draft rename. Fixed events, composite teachers, import reconciliation and load/recovery validation remain follow-up work. See [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md).

## Technical Follow-up Document

**Version:** 1.0  
**Status:** Active technical baseline; implementation is proceeding in tested vertical slices
**Related product document:** [PRODUCT_DESCRIPTION.md](PRODUCT_DESCRIPTION.md)

## 1. Recommended architecture

The recommended target is an internal web application with a central relational database:

```text
Browser clients on SPS network
              │
              ▼
       Web/API application
              │
       ┌──────┴──────┐
       ▼             ▼
Relational DB   Background jobs
       │             │
       └──────┬──────┘
              ▼
     Excel/PDF exports and
     transitional UiPath jobs
```

The database becomes the source of truth. The application performs validation and calculations centrally. Excel files are used for controlled import/export, not concurrent multi-user storage.

## 2. Deployment model

For the internal network, deploy:

- Web application on an approved Windows or Linux server.
- Relational database on the same server or a protected database server.
- HTTPS using an internal certificate.
- Browser access from approved SPS workstations.
- Scheduled database backups to a separate protected location.
- Optional Windows/Active Directory authentication if the environment supports it.

The application must be usable in an air-gapped or restricted network. External cloud services must not be required for core operation.

Implementation note: the initial API foundation is present, with signed-in, role-guarded resources and encrypted student fields. Timetable resource setup, persistent lesson requirements and rule resolution are being delivered through reviewed feature branches. Lesson writes validate active references, availability and blocks, preserve archived data, and coordinate with period configuration changes. The scheduler, the production UI and full recovery verification remain outstanding; this document remains the target design.

## 3. Security and first-run bootstrap

Scheduling-rule delivery now uses stable targets, validated definitions, atomic edit versions and shared resolution. Applicable unresolved legacy rules block planning pending explicit IT reconciliation. PostgreSQL enforces cross-scope overlap checks and serializes membership/rule writes. The scheduler and production UI must still consume this service; details are in [SCHEDULING_RULES.md](SCHEDULING_RULES.md).

The timetable draft increment consumes that service for every weekday and amendment. It persists immutable configuration snapshots, block/cell placements, pending counts, locks and approval; actual-time conflicts and optimistic revisions protect manual edits. IT Administrators approve complete drafts and Executives read approved snapshots. Automatic generation, weekly publishing, browser editing, audited exports and attendance consumption of the published version are implemented; draft copy/rebase, fixed events, composite teachers and server-side PDF generation remain subsequent work; see [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).

### 3.1 Bootstrap design

The installation creates a single bootstrap identity in a setup state. It is not a normal shared account.

Required controls:

1. Store only a strong password hash, never a plain-text password.
2. Deliver the initial secret through a deployment secret or one-time setup token.
3. Force a credential change on first sign-in.
4. Require creation of a named IT Administrator before normal operation is enabled. Implemented with the persisted setup gate and first-run browser wizard.
5. Record bootstrap completion and IT Administrator creation in immutable audit events in the same transaction as setup completion.
6. Preserve the bootstrap identity as a full-access Superuser after its temporary credential is changed; use named accounts for routine work.
7. Provide a documented, audited recovery procedure requiring server-level IT access. Implemented as an interactive Compose command; production acceptance still requires confirming Docker-host access controls and rehearsing the recovery with a backup.

The default superuser is therefore a controlled installation mechanism, not an account intended for daily use.

### 3.2 Authorisation

Use deny-by-default permissions. Roles are collections of permissions rather than hard-coded screen checks.

Suggested permission groups:

- `users.manage`
- `settings.manage`
- `reference-data.manage`
- `students.read`
- `students.write`
- `attendance.read`
- `attendance.write`
- `reports.read`
- `reports.export`
- `imports.run`
- `audit.read`
- `backup.manage`

The default role mapping is:

| Role | Main permissions |
|---|---|
| Superuser | All permissions during bootstrap and recovery |
| IT Administrator | User, settings, reference data, audit and support permissions |
| Operator | Student, attendance, import and operational report permissions |
| Executive | Read-only dashboard and report export permissions |

## 4. Proposed domain model

Core tables should include:

- `users`, `roles`, `permissions`, `user_roles`
- `students`
- `student_status_history`
- `institutions`, `classes`, `categories`, `academic_years`
- `attendance_sessions`, `attendance_records`
- `import_batches`, `import_rows`, `export_jobs`
- `dashboard_definitions` or versioned report queries
- `audit_log`
- `system_settings`

Important constraints:

- `students.pris_no` must be unique within the agreed business scope.
- Attendance must be unique by student, session and date according to the attendance policy.
- Reference data should be effective-dated where historical reporting requires it.
- Deletes should normally be soft deletes or status changes.
- Every business record should include created/updated timestamps and actor identifiers.

## 5. Data migration and Excel compatibility

The existing `Student Intake 2023` workbook is the migration source. Its important fields include:

- `Pris No.`
- `NAME`
- `INSTN CLASS`
- `STATUS`
- `STATUS EFFECTIVE`
- `CAT`
- profile and next-of-kin fields

The supplied workbook contains 2021 and 2023 intake sheets. Both can be staged and imported with an explicit year selection and a separate IT-managed class crosswalk; `CLASS` is used for 2021 and `INSTN CLASS` for 2023. The current profile schema and browser preserve shared fields, encrypt the 2021-only `VERIFY` detail, and retain `ELECTIVE`. `S/N` is a worksheet row sequence, not an identifier. Category and academic-year values are checked against active catalogs during profile writes and intake preview/commit. Institution is optional and selected from its catalog because neither sheet supplies it. Legacy-label reconciliation and full report parity remain outstanding.

Migration steps:

1. Create a read-only copy of each source workbook.
2. Import reference values from `Filtering Criteria` and `Class DefinItion`.
3. Load students using `Pris No.` as the matching key.
4. Resolve duplicate identifiers and missing identifiers before final commit.
5. Load status history and retain the encrypted source workbook and import-batch metadata; the original filesystem path/name is not stored.
6. Reconcile active counts, class counts and category totals with the original workbook.
7. Freeze the migration snapshot and obtain business sign-off.

The current Student Intake Updater appears to match by `NAME` in its active workflow. The replacement must use `Pris No.` wherever available and report ambiguous name-only matches instead of silently updating the wrong student.

## 6. Dashboard implementation

The existing workbook dashboards should be treated as calculation specifications:

- `Active Breakdown` is the high-level active-student rollup.
- `Active Breakdown By Categoy` is the category/institution/age analysis.
- Individual sheets such as `TM1`, `TM1 CCU`, `A1`–`A4` and `B1`–`B5` are class-level reports.
- `Filtering Criteria` and `Class DefinItion` provide reference mappings.

The application should calculate dashboard results from database queries or tested views rather than copying Excel formulas. Each dashboard response should include:

- Applied filters.
- Result timestamp.
- Data-through timestamp.
- User who requested the report.

The current dashboard increment accepts class, institution, category, status and academic-year profile filters, with active status as the default. It calculates matching totals and class/category/institution groupings in SQL and follows the workbook's `<=21` / `>21` age split, exposing missing age snapshots separately. Dashboard responses carry the requesting username, query completion time and latest matching source update times. `GET /api/v1/reports/dashboard.xlsx` applies the same filter contract and emits Overview, Profile breakdowns and Attendance sessions sheets for Operator, Executive and Superuser roles; user-supplied strings are written as literal text, no student identifiers or names are exported, and each successful download writes an audit event with the filters and aggregate counts. Attendance continues to use class and date filters against attendance sessions and their captured rosters; current profile filters cannot revise historical membership. Automated tests cover these calculations, workbook contents, formula-safe text, freshness metadata, audit recording and role access, but full source-workbook reconciliation and business sign-off are still open.

For near-real-time behavior, query committed records on page refresh or use a short polling interval. A cache may be introduced later, but cached results must show their age.

## 7. Import and validation pipeline

```text
Upload workbook
    ↓
Virus/file/type check
    ↓
Read into staging tables
    ↓
Validate headers and reference values
    ↓
Detect duplicate Pris No. and ambiguous matches
    ↓
Show preview and row-level errors
    ↓
Operator confirms import
    ↓
Commit transaction and audit batch
    ↓
Refresh dashboard queries
```

An invalid row must not partially overwrite a valid existing profile unless the operator explicitly confirms an approved correction workflow. Failed imports should remain available for review.

## 8. Attendance processing

Attendance entry should be transactional and should validate:

- Student belongs to the session's captured roster. New sessions capture active class membership at creation; existing migrated sessions preserve only identities already present in attendance records and are explicitly marked partial.
- Session date and academic year are valid.
- Class and institution are consistent.
- No duplicate record exists.
- Corrections contain a reason and retain the previous value in audit history.

The application generates the monthly AM/PM workbook from roster snapshots and saved records. A visible workbook note identifies partial legacy snapshots or the current-roster fallback when no sessions exist for the month. Visual and formula reconciliation against the existing UiPath workbook, plus date-effective handling of retrospective sessions, remain required before replacing the legacy output.

## 9. Audit, backup and recovery

Audit events should cover:

- Login success/failure and logout.
- User creation, role assignment, disablement and reset.
- Student profile changes.
- Attendance creation and correction.
- Import confirmation and rejection.
- Report export.
- System and reference-data changes.
- Backup and restore operations.

Minimum operational controls:

- Daily full database backup. The Compose `maintenance` profile now provides an age-encrypted PostgreSQL logical dump, atomic no-overwrite output and an explicit restore into an acknowledged empty database. See [DATABASE_BACKUPS.md](DATABASE_BACKUPS.md).
- More frequent transaction/log backup where supported.
- Separate backup location and retention policy.
- Routine restore testing. CI verifies a real PostgreSQL 17 dump/restore round trip and rejects corrupted ciphertext; production still needs a scheduled off-host restore drill.
- Recovery runbook owned by IT Administrator.
- No deletion of audit history through the normal user interface.

## 10. API and application boundaries

Suggested application services:

- `AuthenticationService`
- `UserAdministrationService`
- `StudentService`
- `AttendanceService`
- `ImportService`
- `ReportService`
- `ExportService`
- `AuditService`
- `SystemConfigurationService`

Business rules should live in the service/database layer so that browser screens, imports and UiPath integrations use the same validation rules.

## 11. Testing strategy

### Functional testing

- First-run superuser setup and forced credential change.
- Role permission matrix.
- Student create/update/search.
- Excel import preview, validation and commit.
- Attendance entry and correction.
- Dashboard filters and report export.

### Reconciliation testing

- Compare migrated active totals with the original workbook.
- Compare class and category totals.
- Compare OP/RT results.
- Compare monthly attendance output with the existing generator.

### Security testing

- Attempt access to every restricted endpoint as each role.
- Verify disabled users cannot sign in.
- Verify passwords and tokens are not logged.
- Verify audit records cannot be modified through the UI.
- Test session timeout and failed-login handling.

### Operational testing

- Backup and restore.
- Network interruption during import.
- Concurrent operator updates.
- Large workbook import.
- Formula/report performance under expected user load.

## 12. Implementation sequence

1. Confirm business rules and report definitions.
2. Choose application/database stack approved for the SPS network.
3. Implement authentication, bootstrap superuser and role permissions.
4. Implement reference data and student profiles.
5. Implement Excel staging/import and migration reconciliation.
6. Implement attendance and audit history.
7. Implement dashboards and exports.
8. Integrate or retire the existing UiPath jobs.
9. Conduct user acceptance testing.
10. Deploy with backup, recovery and support procedures.

## 13. Open decisions

The following must be confirmed before implementation:

- Whether Windows/Active Directory authentication is available.
- Approved server and database technology.
- Whether attendance is per day, per lesson or per session.
- Exact definitions of OP, RT, active status and category groups.
- Historical data retention and correction policy.
- Required report formats and print layouts.
- Whether executives can view personally identifiable student fields.
- Production backup location and recovery-time objective.

## 14. Mandatory CI/CD and quality gates

The pull-request CI foundation runs for every pull request, including stacked pull requests whose base is another feature branch. It runs Ruff lint/format checks, Bandit static analysis, `pip-audit`, API tests against disposable PostgreSQL, clean and repeat Alembic upgrades plus model/schema parity, Python compilation, production-container build and Trivy scanning, Compose configuration validation, and Gitleaks full-history scanning. It uploads coverage while the baseline is being established; aggregate coverage thresholds are intentionally deferred until they can be based on measured results. Dependabot is configured to propose weekly Python and GitHub Actions updates.

The current workflow does not yet verify all of the release gates below. Add gates with the associated feature and keep the implementation status explicit:

1. Frontend unit and accessibility tests; Chromium end-to-end coverage exists for delivered workspaces and must continue to grow with each feature.
2. Timetable invariant/property and PDF golden-output tests with scheduling and Amend 4-up.
3. Broader workbook import malformed-file, production-template golden fixture and catalog/reconciliation tests. Synthetic tests already cover parser, encryption, permissions, duplicate handling and atomic commit.
4. Report reconciliation fixtures with each approved business report.
5. Disposable Compose full-stack startup/readiness/smoke tests and artifact publication before release deployment.
6. Backup/restore, load, expanded penetration/security, signing and deployment approval gates before production readiness.

The required workflow must fail on test failures, migration failures, critical/high container vulnerabilities, dependency advisories, secret detections or broken required behavior. Production deployment will require an approved change and the exact tested artifact once that release workflow is implemented. Environment-specific secrets must remain outside source control.

## 15. Living test policy

Tests are maintained with the feature they protect. A pull request that adds or changes behavior must include updated automated tests, including negative and permission tests where relevant. The test suite must cover at least:

- Authentication, token expiry, logout and failed-login handling, including durable sign-in audit events that omit credentials and unknown usernames.
- Superuser bootstrap, forced credential rotation and recovery controls.
- Every role and every protected API permission.
- Student profile validation, duplicate `Pris No.` detection and import reconciliation.
- Attendance creation, duplicate prevention and correction audit history.
- Dashboard filters, totals and reconciliation with source records.
- Database migrations, backup/restore and failure recovery paths.
- API input validation, output filtering and error handling.

Coverage percentage alone is not sufficient. Critical workflows must have explicit tests, and the test plan must be reviewed whenever a new feature is added.

## 16. Docker Compose deployment standard

The project must provide a version-controlled Docker Compose deployment for development, testing and production-like internal deployment. The baseline services are:

- `app` — backend API and application services.
- `db` — relational database with a persistent named volume.
- `proxy` — HTTPS termination and request routing.
- `worker` — background imports, report generation and scheduled jobs where required.

Containers must run with pinned image/dependency versions, non-root users where supported, health checks, restart policy, resource limits and explicit networks. Database volumes and backup destinations must be externalised and must not be removed by routine application redeployment. Production secrets must be supplied through protected environment files or a secrets manager, not committed `.env` files. `APP_ENV=production` now rejects local SQLite/non-psycopg URLs, known development secrets, short JWT/bootstrap secrets and invalid or duplicate Fernet keys at settings initialization. This catches configuration mistakes but does not replace protected secret delivery, TLS or key-custody controls.

## 17. Data protection and application security

The frontend is an untrusted client. It must communicate only with the backend API over HTTPS. It must not contain database credentials, database connection strings, encryption keys or privileged service credentials.

The backend must:

- Enforce authentication and authorisation on every protected endpoint.
- Validate JWT signature, issuer, audience, expiry and token type.
- Use short-lived access tokens and a controlled refresh-token strategy, preferably with refresh-token rotation and revocation.
- Apply server-side role and permission checks; frontend route guards are only usability controls.
- Use parameterised queries or a safe data-access layer.
- Apply input validation, output filtering, rate limiting and secure error responses.
- Protect cookies/tokens against XSS, CSRF and replay according to the selected browser authentication design.
- Record security events without logging passwords, tokens, connection strings or plaintext sensitive data.

Database protection must include:

- Encryption at rest using the database/server storage capabilities.
- TLS for database connections where supported and practical.
- Least-privilege database accounts separated by application role where appropriate.
- Application-level authenticated encryption for designated sensitive fields, such as personal identifiers and contact details.
- Key versioning and rotation without losing the ability to decrypt retained records.
- Keys stored outside the database and outside source control.
- Encrypted backups with separately protected keys.

Application-level encryption does not replace database encryption at rest. Both controls are required for the fields classified as sensitive.

Application ciphertext now carries a key identifier. The API decrypts the active key and configured prior keys while new writes use only the active key. `python -m app.rotate_encryption` performs a read-only verification by default; `--apply` rotates student profile fields, captured attendance roster names, and both staged-import ciphertext payloads in one transaction. Run with application writes stopped, retain old keys for every backup that may contain their ciphertext, and verify a zero-rotation dry run afterward. See [ENCRYPTION_KEY_ROTATION.md](ENCRYPTION_KEY_ROTATION.md). Production key custody and a restore rehearsal remain release requirements.

## 18. Security assurance and operations

Security must be observed across the full lifecycle:

- Threat model the authentication, import, reporting, export and administration flows.
- Maintain dependency and container vulnerability scanning.
- Apply secure headers, HTTPS, restricted CORS and network segmentation.
- Keep production database ports inaccessible from user networks and frontend containers.
- Separate development, test and production credentials and data.
- Review audit logs and security alerts.
- Patch base images and dependencies on a defined schedule.
- Test backup restoration and key recovery.
- Perform security review before production release and after material changes.
- Maintain incident response, credential rotation and vulnerability remediation procedures.

## 19. Required repository deliverables

The implementation repository must include:

- Dockerfiles and Docker Compose files for supported environments.
- CI/CD workflow definitions.
- Automated test suites and test data strategy.
- Database migration scripts.
- Secure configuration and secret-handling documentation.
- Health/readiness endpoints and deployment runbook.
- Backup, restore and disaster-recovery runbook.
- Security threat model and release checklist.

## 20. Timetable resource and teacher profile requirements

The timetable scheduler requires a resource-management layer in addition to application users and roles. These identities must not be conflated:

- An application user signs in and receives permissions through Superuser, IT Administrator, Operator or Executive roles.
- A teacher profile is a scheduling resource referenced by lesson requirements and timetable slots.

The teacher profile must contain a stable ID, unique short code, full name, adjunct flag, active/effective dates and normalized availability by weekday and period. Subjects, instructional classes and lesson requirements must be maintained as controlled reference data. A lesson requirement includes subject, teacher, instructional class, weekly count and block length.

Teacher profiles must be created or imported before lessons can be created. The API must reject missing or inactive teacher references, duplicate short codes, invalid availability and lesson requirements with impossible counts. Availability and double-booking rules must be shared by the scheduler and Amend 4-up editor.

The legacy application stores availability as a positional colon-separated value with 20 teaching slots: four teaching periods per day. The visual timetable has a fifth daily column for lunch, but lunch is not a teaching slot. The new database must store explicit day/period rows or a versioned availability structure, with lunch represented as a non-schedulable interval.

Class scheduling reference data must also include named class clusters and period definitions. Every instructional class inherits the default `P1`, `P2`, `Lunch`, `P3`, `P4` pattern. A class- or cluster-scoped period definition can override the matching default; overrides must be effective-dated, audited and prevented from changing Period 3 from lunch. Amend 4-up must support adding a lesson by selecting an empty teaching cell, then validating the subject, teacher, class, availability and double-booking rules before placement.

Every schedule-planning operation must have an applicable scheduling rule set before it can proceed. Rule resolution must return exactly one active rule for each planned class; missing, duplicate or overlapping class/cluster rules must fail validation. Duplicate timetable placements and duplicate rule definitions are not allowed, and the database must enforce the relevant uniqueness constraints.
