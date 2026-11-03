# SPS Student Dashboard

Superuser access increment (27 October 2026): Superuser can use every workspace and action, including student intake, attendance, reports, timetable setup/planning/approval and account administration. The Superuser lands on the dashboard with all workspace navigation visible. API tests enforce this full-access role while preserving the separate IT Administrator, Operator and Executive boundaries. See [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md).

Identity increment (26 October 2026): IT Administrators can manage named non-Superuser accounts and reset temporary passwords. Password change, role/status change, reset and explicit logout revoke existing account tokens; the browser clears credentials on sign-out. Setup/recovery, complete API permission separation and deployment hardening remain required. See [IDENTITY_SECURITY.md](IDENTITY_SECURITY.md).

Attendance browser increment (26 October 2026): Operators can create/review sessions, record and correct attendance, adjust expected counts with reasons and close complete or explicitly acknowledged incomplete sessions. Versioned transactions protect concurrent work and dashboard refresh reads committed changes. New sessions preserve an encrypted roster snapshot so later profile changes do not rewrite session membership; monthly exports use those snapshots and label legacy partial coverage. Date-effective historical roster reconciliation and visual/formula parity with the legacy workbook remain required. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

Profile and intake update (3 November 2026): student categories and institutions are maintained as audited, versioned catalogs by IT Administrators and Superusers; profile forms and the 2023 intake importer resolve categories through the active catalog. Migration `20261103_0016` preserves existing category text and ciphertext while linking legacy category values. Older workbook mapping and full historical reconciliation remain to implement. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md) and [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

Browser increment (27 October 2026): the application follows the supplied timetable redesign with By class/By teacher weekly boards, separate report/print, classes/teachers, and periods/rules sections. Clickable Amend 4-up remains available with 4/8/12/16 class paging; period display shows P1, P2, P3 Lunch/Muster, P4 and P5. Superuser retains full application access. Browser print currently provides Save as PDF; native PDF generation and remaining setup/recovery gates are follow-up work. See [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md), [TIMETABLE_INTEGRATION.md](TIMETABLE_INTEGRATION.md) and [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).

Generation delivery note (26 October 2026): the API and production browser support generating weekly drafts while preserving existing lessons by default. Operators can explicitly regenerate unlocked lessons; locked lessons and approved timetables are protected. Each run saves a report of unplaced blocks and reasons, and incomplete schedules cannot be approved. See [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md).

## Product Description Document

**Version:** 1.0  
**Status:** Proposed product baseline  
**Audience:** SPS management, operators, IT administrators, developers and implementation partners

## 1. Product summary

SPS Student Dashboard is an internal network application for managing student intake profiles, attendance records and operational reporting in one controlled system.

The product replaces the current split workflow in which operators update Excel intake workbooks, UiPath processes generate attendance workbooks, and formula-based sheets provide dashboard summaries. The new system will provide authenticated browser access, role-based permissions, a central source of truth and near-real-time reporting after manual updates are saved.

Existing Excel workbooks remain supported as controlled import, export and archival formats. They are not the long-term system of record.

## 2. Product objectives

- Provide one reliable source for student profiles and attendance data.
- Reduce duplicate data entry between the Student Intake Updater and attendance generator.
- Allow authorised users to update information from the internal network.
- Make dashboard figures available shortly after an update is committed.
- Preserve the existing intake, class, category, OP/RT and active-status reporting rules.
- Maintain an auditable history of changes.
- Support printable and Excel-based reports required by operations and management.
- Provide a controlled first-run superuser for establishing the production user base.

## 3. Users and access model

### 3.1 Bootstrap superuser

The system is delivered with one protected default superuser so that the first administrator can start the application and configure it without a pre-existing user database.

The superuser can:

- Sign in during first-run setup.
- Change the initial credential and complete the setup wizard.
- Create and disable user accounts.
- Assign and revoke roles.
- Create the first IT Administrator account.
- Review security and system audit events.
- Use every application workspace and operation after setup, including student profiles/imports, attendance, reporting, timetable planning and approval.

After first-run setup, the Superuser retains full access. The dashboard is its initial workspace; account administration remains available from navigation. Superuser actions are audited. Named Operator, IT Administrator and Executive accounts remain the normal accounts for routine role-specific work.

The initial credential must not be documented as a permanent password. It must be supplied through a secure deployment mechanism or environment configuration, expire after first use, and require a password change. The application must prevent normal production use while the initial credential remains unchanged. A recovery procedure must exist for a lost superuser account and must be restricted to authorised IT personnel.

### 3.2 IT Administrator

The IT Administrator manages technical and reference configuration:

- Users, roles, account status and access recovery.
- Institutions, classes, categories, academic years and reporting criteria.
- Backup, restore and retention settings.
- Application settings and integration status.
- Import failures, processing jobs and error queues.
- Audit logs and operational diagnostics.

The IT Administrator should not edit student attendance or profile data unless explicitly granted an additional operational permission.

### 3.3 Operator

The Operator performs daily business processing:

- Create and update student intake profiles.
- Import and validate intake workbooks.
- Update student status, class and profile details.
- Record, correct and review attendance.
- Run daily processing and attendance generation.
- Produce operational reports and Excel outputs.
- Review validation warnings and failed imports.

Operators cannot manage users, security settings, backups or system configuration.

### 3.4 Executive

The Executive has read-only management access:

- View current intake and attendance dashboards.
- Filter by academic year, date, institution, class, category and status.
- View trends and summary indicators.
- Print or export approved reports.

Executives cannot alter source records or configuration.

## 4. Core product capabilities

### 4.1 Authentication and authorisation

- Internal network sign-in.
- Role-based access control.
- Account activation, deactivation and password reset.
- Optional Windows/Active Directory integration where available.
- Session timeout and reverse-proxy throttling of repeated sign-in attempts by client IP, with rejected bursts returned as HTTP 429.
- Audit records for sign-in, role changes and privileged actions.

### 4.2 Student intake and profile management

- Create, view, edit and search student profiles.
- Use `Pris No.` as the primary business identifier.
- Store student status, institution/class, category, academic year and profile fields.
- Track status changes instead of overwriting history.
- Validate duplicate identifiers, required fields, dates and class mappings.
- Import existing Excel intake workbooks with a preview and error report.
- Preserve source workbook copies and import batch history.

### 4.3 Attendance management

- Record attendance by student, class, date and session.
- Create an attendance session from the currently published timetable for the selected academic year/date, retaining which published version and instructional class informed its creation.
- Let IT Administrators maintain a separate, audited mapping between student profile classes and instructional timetable classes; never infer or reuse workbook-specific intake crosswalks for attendance.
- Support corrections with a reason and audit trail.
- Prevent duplicate attendance records for the same student/session.
- Allow operators to review missing or incomplete attendance.
- Generate the existing monthly attendance workbook format during migration.

### 4.4 Dashboards and reports

The dashboard will reproduce the business meaning of the current workbook sheets:

- Active student breakdown.
- Breakdown by institution and class.
- Category and age analysis.
- OP/RT analysis.
- Attendance totals, rates and missing records.
- Trends by day, month, academic year and class.
- Printable executive summaries.

Dashboard results must be based on committed database data and show the last refresh timestamp and active filter context. Class filters apply to student and attendance results; category, institution, status and academic-year filters apply to current student profiles; attendance date filters apply to sessions. Active student summaries include institution breakdown and age values from their recorded academic-year snapshots.

### 4.5 Excel and UiPath compatibility

- Import the existing intake workbook format.
- Export approved operational and executive reports to Excel/PDF.
- Operators and Executives can download a monthly Excel attendance register for one class, formatted as a printable AM/PM calendar grid with compact attendance codes.
- Retain UiPath integration while the new application is introduced.
- Treat the existing formula dashboards as reference specifications for acceptance testing.

## 5. Typical workflows

### Daily operator workflow

```text
Sign in → review alerts → update/import profiles → validate
→ record attendance → refresh dashboard → generate daily/monthly reports
```

### Executive workflow

```text
Sign in → select filters → review dashboards → print/export report
```

### First-run setup workflow

```text
Start application → sign in as default superuser → change credential
→ create IT Administrator → configure reference data → enable normal use
```

## 6. Product outcomes

The product is successful when:

- A user can complete the full intake-to-attendance workflow without manually copying data between workbooks.
- Dashboard totals reconcile with the underlying student and attendance records.
- Each change can be traced to a user, time and reason where applicable.
- Executives can obtain current reports without operator intervention.
- The application can be backed up and restored without losing audit history.

## 7. Initial scope and exclusions

Initial scope includes student profiles, attendance, reporting, Excel migration, user roles and internal network deployment.

The following are not required for the first release unless separately approved:

- Public internet access.
- Student or parent self-service access.
- Mobile application.
- Biometric attendance hardware.
- Automated attendance capture from external devices.
- Replacement of every existing UiPath automation on day one.

## 8. Product acceptance criteria

- The four account types—Superuser, IT Administrator, Operator and Executive—are enforced.
- The default superuser cannot remain on its initial credential.
- Operators can import or update student profiles and record attendance.
- Executives can view filtered dashboards but cannot edit data.
- Dashboard totals update after a committed manual change.
- Reports can be printed and exported.
- Invalid imports are rejected with actionable row-level messages.
- User, profile, attendance, import and privileged configuration changes are auditable.

## 9. Mandatory platform and security requirements

The production system must also satisfy the following requirements:

- CI/CD must be established as part of the project, with repeatable build, test, security-scan and deployment pipelines.
- Automated testing must be comprehensive and must be updated in the same change as every new feature or changed business rule.
- The complete application must be deployable through Docker Compose, including the application, database, reverse proxy and approved supporting services.
- Database protection must include encryption at rest, encrypted connections where supported, managed secrets and application-level encryption for designated sensitive fields.
- JWT access tokens must be short-lived, signed with a managed secret or key, validated server-side and never treated as proof of authorisation by the frontend alone.
- Frontend code must never connect directly to the database. All data access must pass through authenticated and authorised backend APIs.
- Security must be applied throughout design, development, testing, deployment, operations, logging, backup and recovery.

These requirements are release gates, not optional future enhancements.

## 10. Timetable scheduling module

The product also includes the Prison School Timetable workflow currently provided by the legacy `TImeTables-legacy` WinForms system. It schedules instructional class groups, teachers, subjects and weekly lesson requirements.

The timetable workflow is:

```text
Set up teachers, subjects, classes and lessons
        ↓
Generate an initial timetable
        ↓
Review unplaced lessons and conflicts
        ↓
Amend 4-up visual editing and approval
        ↓
Save the approved timetable
        ↓
Export By Instructional Class and By Teacher reports
```

The **Amend 4-up** workspace is the primary timetable function. It must support:

- By Instructional Class and By Teacher views.
- Four-up timetable review with configurable page density.
- Previous/next page navigation and search.
- Five weekdays with four teaching periods and a lunch interval displayed as Period 3.
- Double-click editing of a lesson.
- Click an empty teaching cell to add a lesson directly to the selected class or teacher view.
- Drag-and-drop movement with swap behavior where valid.
- Right-click shift/remove actions.
- Locking and conflict protection.
- Class/teacher rename with controlled cascade.
- Save, audit and return to the normal schedule view.

The module must generate both timetable report types and preserve a clear relationship between the timetable's instructional classes and the student intake/attendance classes. It must not silently overwrite an approved timetable when a new schedule is generated.

### 10.1 Timetable resource setup

Teacher profiles are separate from application login accounts. A teacher profile is a scheduling resource, not a user permission identity. Before a timetable can be generated, an Operator or IT Administrator must maintain:

- Teacher short code, full name, adjunct status and day/period availability.
- Subjects with name, short code and description.
- Instructional classes with short name and description.
- Class clusters that group instructional classes for shared scheduling changes.
- A default period pattern inherited by every class, with controlled period overrides for an individual class or cluster.
- Lesson requirements linking subject, teacher and instructional class, including weekly count and block length.

Scheduling rules are mandatory planning data. Before a draft is generated or an Amend 4-up change is accepted, every planned class must resolve to exactly one applicable rule set. Missing, duplicate or overlapping rules are rejected; the system must not silently choose between rules or create duplicate schedule placements.

The system must not allow a lesson to reference an unknown teacher. Teacher availability and teacher double-booking checks must apply both during draft generation and during Amend 4-up amendments. The prototype's Resource Setup view demonstrates this prerequisite workflow.
