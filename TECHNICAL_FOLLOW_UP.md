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
