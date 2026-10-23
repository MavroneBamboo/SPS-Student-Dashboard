# SPS Student Dashboard

## Technical Follow-up Document

**Version:** 1.0  
**Status:** Proposed technical baseline  
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

## 3. Security and first-run bootstrap

### 3.1 Bootstrap design

The installation creates a single bootstrap identity in a setup state. It is not a normal shared account.

Required controls:

1. Store only a strong password hash, never a plain-text password.
2. Deliver the initial secret through a deployment secret or one-time setup token.
3. Force a credential change on first sign-in.
4. Require creation of a named IT Administrator before normal operation is enabled.
5. Record bootstrap completion in an immutable audit event.
6. Disable or rotate the bootstrap identity after setup.
7. Provide a documented, audited recovery procedure requiring server-level IT access.

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

Migration steps:

1. Create a read-only copy of each source workbook.
2. Import reference values from `Filtering Criteria` and `Class DefinItion`.
3. Load students using `Pris No.` as the matching key.
4. Resolve duplicate identifiers and missing identifiers before final commit.
5. Load status history and preserve the original source filename and import batch.
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

- Student exists and is active or otherwise eligible for the session.
- Session date and academic year are valid.
- Class and institution are consistent.
- No duplicate record exists.
- Corrections contain a reason and retain the previous value in audit history.

The existing UiPath monthly attendance generator can initially consume an approved export generated by the application. The later target is for the application to generate the same workbook directly or invoke a controlled export service.

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

- Daily full database backup.
- More frequent transaction/log backup where supported.
- Separate backup location and retention policy.
- Routine restore testing.
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

CI/CD is part of the product build and must be established before production deployment. Every pull request should run a reproducible pipeline containing at least:

1. Source checkout and dependency lock verification.
2. Formatting, linting and static analysis.
3. Unit tests for domain and service logic.
4. API/integration tests against an isolated test database.
5. End-to-end tests for login, role enforcement, intake, attendance and reporting.
6. Migration tests against a clean database and an upgrade database.
7. Container build and Docker Compose startup validation.
8. Dependency, container and secret scanning.
9. Test coverage and quality thresholds.
10. Build artifact/version publication.

The pipeline must fail on test failures, migration failures, critical security findings, leaked secrets or a broken Compose deployment. Production deployment must require an approved change and must use the exact tested artifact. Environment-specific secrets must be injected by the deployment environment and must not be committed to the repository.

## 15. Living test policy

Tests are maintained with the feature they protect. A pull request that adds or changes behavior must include updated automated tests, including negative and permission tests where relevant. The test suite must cover at least:

- Authentication, token expiry, logout and failed-login handling.
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

Containers must run with pinned image/dependency versions, non-root users where supported, health checks, restart policy, resource limits and explicit networks. Database volumes and backup destinations must be externalised and must not be removed by routine application redeployment. Production secrets must be supplied through protected environment files or a secrets manager, not committed `.env` files.

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
