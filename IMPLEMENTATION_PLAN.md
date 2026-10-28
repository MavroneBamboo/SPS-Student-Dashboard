# SPS Student Dashboard

## Implementation Plan

**Version:** 1.0  
**Status:** Active implementation plan; delivered slices are recorded below
**Companion document:** [TECHNICAL_DESIGN_DOCUMENT.md](TECHNICAL_DESIGN_DOCUMENT.md)

## 1. Delivery approach

Build the system in vertical increments. Each increment must produce a deployable, tested slice rather than a large unverified handover. The team should maintain a single backlog, protect `main`, require pull requests and run the full CI pipeline on every change.

The initial release should be delivered in phases over approximately 16–20 weeks, subject to staffing, environment approval and data-migration complexity. Dates are planning estimates, not commitments.

### Current delivery checkpoint (28 October 2026)

- Timetable interface redesign (27 October): production UI implements By class/By teacher weekly views, browser print-to-PDF reports, teacher/class/subject tabs, period and rule management, and clickable Amend 4-up at 4/8/12/16 classes per page. Display maps the lunch interval to P3 while preserving stable database/API slot codes. See [TIMETABLE_INTEGRATION.md](TIMETABLE_INTEGRATION.md).

- Operational role increment (26 October): students and attendance require Operator access. Dashboards and exports allow Operator or Executive; audit allows Superuser or IT. Tests use named Operator identities and cover all four roles. See [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md).

- Identity increment (26 October): versioned account-wide token revocation, explicit logout, IT management of non-Superuser accounts, administrator reset, case-insensitive unique usernames and preserved last administrators. Verify migration, API and browser cases in CI. Complete least-privilege permissions, setup/recovery and deployment controls in later slices. See [IDENTITY_SECURITY.md](IDENTITY_SECURITY.md).
- Sign-in abuse-control increment (27 October): Nginx limits login attempts by client IP to 30 per minute with a burst of 10, returning HTTP 429 when exceeded. CI verifies actual proxy behavior and confirms other API routes remain reachable. Persistent account-level lockout and distributed abuse detection remain follow-up work.
- Database account separation increment (27 October): Compose migrations run with the admin URL, then provision a separate SCRAM-authenticated runtime role with DML and sequence rights only. CI verifies the runtime user can access application records while DDL and role/database administration are denied. TLS, at-rest encryption and encrypted backups remain separate release gates.

- Attendance browser increment (26 October): session create/search, captured-roster lookup, mark/correct/review, reasoned count adjustment and complete/explicit incomplete closure. Version/lock/duplicate/migration-race tests and browser acceptance run with the feature. Capture-time snapshots now preserve future sessions across profile changes; date-effective historical reconciliation, granularity, monthly visual/formula parity and full permissions remain required. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

- Profile browser increment (26 October): Operator profile forms, status history, paged search, atomic version-checked saves and API/Chromium race/privacy/lifecycle checks. Existing-row version migration is additive and covered by preservation rehearsal. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md).

- Extended intake-profile increment (27 October): migration `0009` adds the supplied workbook's enrolment, academic, demographic and next-of-kin fields without rewriting current profile data. Sensitive additions are application-encrypted; the browser supports create/read/update/clear with optimistic versioning.
- Student workbook import increment (28 October): migration `0010` stages the source `.xlsx` and normalized rows as application-encrypted data. Operator upload is bounded and package/header/row validated; the actual age-column cached formulas are consumed, while other formulas are rejected. Numeric IC/NRIC/contact cells require explicit acknowledgement of leading-zero/precision warnings. Preview exposes counts and sanitized row errors/warnings. `CREATE_ONLY` and explicit `UPDATE_EXISTING` commits are atomic, stale-version checked, audited and idempotent. Case/space-normalized `Pris No.` uniqueness is enforced, with migration refusal if legacy collisions need reconciliation. Browser, API, migration, encryption, stale update, duplicate and rollback cases are added. The 2023 sheet is supported; class/catalog reconciliation, 2021 mapping, import retention controls and report parity remain required. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

- WSL staging delivery increment: after all GitHub-hosted quality, test, secret-scan and container gates pass on a push to `main`, a separately labeled self-hosted WSL runner deploys that exact commit using Docker Compose. Staging binds to localhost by default, uses a runner-local secrets file and persistent named database volume, and performs a readiness smoke check. Pull requests never run on the self-hosted runner. See [STAGING_DEPLOYMENT.md](STAGING_DEPLOYMENT.md). This is synthetic-data staging; HTTPS, backup/restore, retention and key rotation, release rollback and production deployment gates remain outstanding.
- Controlled intake-class mapping increment (28 October): migration `0011` adds the IT-managed `Student Intake 2023` source-label crosswalk to active instructional classes, without rewriting existing profiles. Label matching uses Unicode normalization, whitespace collapse and case folding; mappings are unique per normalized label, versioned, audited, deactivatable and never inferred from fuzzy matches. The import preview stores the mapping version and canonical class target; commit rechecks both mapping and target class under lock and rejects stale previews. Operators can read the map but only IT Administrators can change it. API and browser tests cover permissions, normalization, remapping and stale-preview rejection. Manual profile class entry remains free text; controlled categories/institutions, 2021 import, retention and report parity remain planned. See [STUDENT_IMPORTS.md](STUDENT_IMPORTS.md).

- Monthly attendance export increment (27 October): Operators and Executives can download a class-and-month scoped Excel register that follows the legacy AM/PM calendar grid and is print configured. Attendance status codes are P/A/L/E/M; unrecorded slots stay blank. Migration `0012` adds per-session encrypted rosters; new exports use the month’s roster snapshots and label incomplete legacy coverage or the no-session current-roster fallback. API and browser coverage verifies workbook content/layout, download behavior and role/month validation. Visual/formula parity remains follow-up work.

- Attendance roster snapshot increment (28 October): migration `0012` captures encrypted student identity/status per newly created session. Lookup and record authorization use the session snapshot even after later profile transfer, deactivation or renaming. Existing sessions are backfilled only from students with recorded attendance and marked `LEGACY_PARTIAL`; the migration does not invent missing historical identities. Monthly Excel/CSV exports read captured identities and status, and the Excel sheet labels partial legacy or no-session/current-roster basis. Retrospective session creation still does not reconstruct membership on the attendance date; visual/formula parity and business reconciliation remain required. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

- Browser increment (26 October): deliver sign-in/rotation, Superuser accounts and live dashboard as the first actual frontend, with local assets and Chromium CI against the API/PostgreSQL. Profile/attendance/resource/timetable forms, full setup/recovery, IT account-management permissions and deployment hardening remain required. See [BROWSER_WORKSPACE.md](BROWSER_WORKSPACE.md).

- PR #18 established the initial encrypted student/API foundation and is merged.
- PR #19 established CI quality, security, PostgreSQL migration, production-image and Compose validation gates and is merged.
- PR #28 is merged and includes the resource setup, persistent lesson requirements and stable-target rule-resolution foundations originally submitted through #26/#27/#28. The earlier #26/#27 PRs are superseded by that merged code.
- Rule resolution includes typed definitions, versioned edits/archive/binding, exactly-one-rule bulk resolution and PostgreSQL overlap guards. Legacy text rules require explicit reconciliation; see [SCHEDULING_RULES.md](SCHEDULING_RULES.md).
- The timetable-draft increment adds weekly snapshots, persistent block/cell placement, full-grid validation for manual changes, revision guards, approval and executive reads of approved versions. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).
- The generation increment adds deterministic first-fit plus bounded repair, default preservation of existing lessons, explicit replacement of unlocked blocks and persisted per-revision reports. It uses the manual validator and transactional placement services; see [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md). Publishing coordination, teacher-oriented views, swap/drag and report exports remain outstanding.
- The timetable browser increment adds IT forms for teachers/subjects/classes/clusters/membership/period overrides/rules and lesson requirements. Operators create weekly drafts, page through 4/8/12/16 class grids, add/amend/remove/lock lessons by clicking cells and run generation. IT Administrators approve complete drafts. Chromium acceptance tests cover editing, lunch placement, generation, approval and resource setup. Teacher-oriented grids, drag/swap, publishing, legacy reconciliation and report exports remain outstanding.
- The defensive validation increment (PR #30) compares persisted cells with validated blocks before every amendment and approval. Regression tests cover missing cells, extra cells and changed block anchors, requiring rejection without revision, grid or audit changes.
- The production timetable browser increment (PR #37) delivers IT resource forms and class-oriented Amend 4-up with 4/8/12/16 class paging, clickable add/edit/remove/lock, generation and IT approval. Teacher-oriented views, swap/drag, publishing, legacy reconciliation and printable report exports remain outstanding.
- The existing pull-request CI job runs the new resource API tests alongside PostgreSQL migration/model-parity gates; covered cases include normalized duplicates, cluster membership, default/cluster/class period resolution, overlap rejection, lunch exclusion and Superuser-vs-IT-Administrator write permissions.
- Local Python execution is unavailable in the current workstation environment; full GitHub CI is the verification gate for this increment. Docker daemon availability must be rechecked before relying on local Compose.

## 2. Delivery principles

- No direct commits to `main`.
- Every feature has automated tests and documentation updates.
- Security and audit are implemented with the feature, not postponed.
- Database migrations are versioned, reviewed and tested on clean and upgrade databases.
- Only tested, versioned container artifacts are promoted.
- Existing Excel and UiPath workflows remain available during controlled transition.
- Business reconciliation is required before data migration sign-off.

## 3. Workstreams

| Workstream | Outcome |
|---|---|
| Product and rules | Approved roles, workflows, data definitions and reports |
| Platform | Repository, CI/CD, Compose environments and deployment runbook |
| Security | Bootstrap, RBAC, JWT, encryption, secrets, audit and threat model |
| Data | Schema, migrations, Excel staging/import and reconciliation |
| Operations | Student profiles, attendance and corrections |
| Reporting | Dashboards, exports and legacy report comparison |
| Quality | Automated tests, security scans, performance and recovery tests |
| Transition | Pilot, training, cutover, support and UiPath retirement plan |

## 4. Phase plan

### Phase 0 — Discovery and technical decisions

**Estimated duration:** 1–2 weeks

Activities:

- Confirm business owners and approval authority.
- Confirm Active Directory or local account strategy.
- Select approved application framework, database and hosting platform.
- Define attendance granularity, active status, OP/RT, category and historical rules.
- Inventory intake workbooks, UiPath versions, reports and data retention needs.
- Define RTO/RPO, environments and network zones.
- Approve sensitive-field classification and encryption key custody.

Deliverables:

- Signed requirements baseline.
- Architecture decision record.
- Data dictionary and report catalogue.
- Threat-model scope.
- Delivery backlog and acceptance-test catalogue.

Exit criteria: unresolved decisions are assigned owners and the technical stack is approved.

### Phase 1 — Repository, environments and CI/CD foundation

**Estimated duration:** 2 weeks

Activities:

- Create application repository structure and branch protection.
- Create Dockerfiles and Compose development/test environments.
- Add database service, migration runner, health checks and seed strategy.
- Establish CI for linting, unit tests, integration tests, Compose startup, dependency scanning, container scanning and secret scanning.
- Publish versioned build artifacts to the approved internal registry or release store.
- Create development, test and production-like configuration templates.
- Document secrets and environment-variable handling.

Deliverables:

- Reproducible local environment.
- Green pull-request pipeline.
- Deployment skeleton and rollback runbook.

Exit criteria: a clean checkout can start the Compose stack, run tests and produce a versioned artifact without secrets in source control.

### Phase 2 — Identity, bootstrap and security baseline

**Estimated duration:** 2–3 weeks

Browser workspace delivery update (26 October 2026): the initial production timetable screen is being added as the next implementation slice. It connects the existing version, requirement, generation, placement, lock and approval APIs. Operators can create weekly drafts, page through 4/8/12/16 class grids, add/amend/remove/lock lesson blocks by clicking cells, and generate pending requirements. IT Administrators can create teacher, subject, class, cluster, membership, period override and rule records, and approve complete drafts. Period 3 is rendered as a non-clickable Lunch column. This slice includes Chromium acceptance tests for these workflows. Drag-and-drop, teacher-oriented grids, swap controls, exports and broader legacy parity remain follow-up work.

Activities:

- Implement setup-state superuser and forced first credential change.
- Implement named users, password policy, account disablement and recovery workflow.
- Implement roles and permission matrix.
- Implement JWT issuance, validation, expiry, refresh rotation and revocation.
- Add secure headers, HTTPS configuration, rate limiting and request correlation.
- Add authentication and authorisation audit events.
- Complete initial threat model and security test cases.

Deliverables:

- Secure login and first-run setup.
- Tested permissions for all four roles.
- Secret/key configuration and rotation procedure.

Exit criteria: unauthorised API calls fail, tokens cannot bypass permissions, bootstrap cannot remain active and all security tests pass.

### Phase 3 — Reference data and student profiles

**Estimated duration:** 2–3 weeks

Activities:

- Implement institutions, classes, categories, academic years and configuration screens.
- Implement student schema and profile search/create/update.
- Make `Pris No.` the primary matching identifier.
- Implement status history, duplicate detection and sensitive-field encryption.
- Add operator and administrator audit history.
- Build profile API, frontend forms and validation tests.

Deliverables:

- Operator profile workflow.
- IT reference-data workflow.
- Profile search and audit trail.

Exit criteria: profile tests pass, sensitive values are protected, duplicate identifiers are blocked and role restrictions are verified.

### Phase 4 — Excel import and migration rehearsal

**Estimated duration:** 2–3 weeks

Activities:

- Build staged workbook upload and header mapping.
- Validate dates, required fields, reference data, identifiers and duplicate rows.
- Produce preview, row-level error and reconciliation reports.
- Import historical data into a non-production environment.
- Compare active, class, category and OP/RT totals with the source workbooks.
- Preserve source files, import batches and migration decisions.

Deliverables:

- Repeatable import job.
- Migration runbook.
- Reconciliation report and exception register.

Exit criteria: a representative workbook imports without data loss, exceptions are explainable and reconciliation is signed off by the business owner.

### Phase 5 — Attendance operations

**Estimated duration:** 2–3 weeks

Activities:

- Implement attendance sessions and records.
- Implement class/date/session entry, review and missing-record views.
- Prevent duplicates and validate eligibility.
- Implement correction workflow requiring a reason.
- Add attendance exports and transitional UiPath handoff.
- Test concurrent updates, retry behavior and audit history.

Deliverables:

- Operator attendance workflow.
- Attendance export compatible with the current monthly generator.
- Correction and reconciliation reports.

Exit criteria: operators can complete a daily process, duplicate records are prevented and corrected records are fully auditable.

### Phase 6 — Dashboards and executive reports

**Estimated duration:** 2–3 weeks

Activities:

- Rebuild the active breakdown and category dashboards from database queries.
- Add class, institution, category, status, date and academic-year filters.
- Add attendance totals, rates and missing-record indicators.
- Implement executive read-only access and approved exports.
- Compare dashboard results with the existing workbook sheets.
- Add performance tests for expected concurrent users and data volume.

Deliverables:

- Executive dashboard.
- Operational dashboard.
- Printable/exportable reports.
- Dashboard reconciliation evidence.

Exit criteria: totals reconcile with approved source data, executive users cannot mutate records and report exports are authorised and auditable.

### Phase 7 — Hardening, recovery and production readiness

**Estimated duration:** 2 weeks

Activities:

- Complete end-to-end, security, migration, load and accessibility tests.
- Test encrypted backups and restore. The initial Compose maintenance slice now provides an age-encrypted PostgreSQL logical backup, no-overwrite atomic publication, empty-target restore, bounded retention pruning, and CI round-trip/tamper coverage. Production scheduling, off-host storage and restore drills remain.
- Test key rotation and recovery procedures.
- Run container and dependency vulnerability remediation.
- Verify network segmentation and database non-exposure.
- Complete operational monitoring, alerting and support runbooks.
- Conduct user acceptance testing and operator/executive training.

Deliverables:

- Production readiness report.
- Security review and outstanding-risk register.
- Restore evidence.
- Training and support material.

Exit criteria: no open critical/high release blockers, restore test passes, security gates pass and business owners approve cutover.

### Phase 8 — Pilot, cutover and transition

**Estimated duration:** 1–2 weeks

Activities:

- Run a controlled pilot with selected operators and executives.
- Freeze and snapshot source workbooks before final migration.
- Perform final import and reconciliation.
- Enable production access and monitor the first operating period.
- Keep UiPath fallback/export capability during the agreed stabilisation period.
- Review incidents and decide which legacy automations can be retired.

Deliverables:

- Production release.
- Signed cutover checklist.
- Support ownership and post-implementation review.

Exit criteria: pilot users complete agreed scenarios, reporting is accepted and rollback/fallback remains available until the stabilisation exit review.

## 5. CI/CD pipeline gates

CI is an evolving product control: whenever a feature adds a new module, security boundary, migration, workflow, or report, its automated tests and relevant CI gate must be added in the same change. The pipeline must remain proportional to implemented behavior; future gates are not represented as already complete.

The current pull-request workflow runs:

1. Ruff lint and formatting checks on application, test, and migration code.
2. Bandit static security analysis and `pip-audit` dependency vulnerability checks.
3. API/business-rule tests against an isolated PostgreSQL 17 service, with coverage uploaded as an artifact (coverage is reported but has no arbitrary threshold until a measured baseline is established).
4. Alembic clean-database upgrade, repeat-upgrade idempotency, and model/schema parity checks.
5. Python compile checks for application and migration sources.
6. Production Docker image build, Trivy scan for fixable critical/high vulnerabilities, and Docker Compose configuration validation.
7. Gitleaks scan across repository history for committed secrets.

As the application grows, add and require these gates alongside their owning feature:

- Frontend lint, unit, accessibility, and browser-level workflow tests when the production UI is introduced.
- Timetable invariant/property tests for unique placements, rule completeness, lunch exclusion, and teacher/class conflicts before timetable planning or Amend 4-up is implemented.
- Workbook-import golden fixtures, malformed-file cases, and reconciliation totals with the Excel intake/import feature.
- Report golden-data reconciliation and export authorization tests with each report implementation.
- Compose end-to-end startup, readiness, and smoke tests in a disposable environment before release deployment.
- Backup/restore, load, and expanded security tests before production-readiness approval.
- Increase coverage thresholds from the observed baseline in small, explicit steps; critical security, migration, and scheduling invariants must have direct tests regardless of aggregate coverage.

The release pipeline additionally performs immutable artifact publication, integrity/signature recording, deployment validation, smoke tests and approval gates. A failed security, migration, or required behavior gate blocks promotion. Temporary exceptions must identify an owner, rationale, and expiry.

## 6. Definition of done

A feature is done only when:

- Requirements and acceptance criteria are documented.
- Backend, frontend and database changes are implemented.
- Positive, negative, permission and audit tests are added or updated.
- Sensitive data and secrets follow the security design.
- Database migrations are reviewed and tested.
- Docker Compose startup and health checks pass.
- CI security scans pass or have an approved exception.
- Documentation and operational impact are updated.
- The feature is demonstrated and approved through a pull request.

## 7. Release and rollback strategy

Use immutable, versioned container artifacts. Deploy to test first, then production-like staging, then production after approval. Database migrations must be backward-compatible during rolling application changes where practical. If rollback is required, redeploy the prior artifact and follow the migration rollback or forward-fix procedure; never restore a database casually without assessing data loss.

Before production deployment:

- Verify backup completion and restore point.
- Verify secrets and key versions.
- Verify image digests.
- Run smoke tests.
- Record approver and release version.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Legacy workbook formulas disagree with new reports | Reconciliation fixtures and business sign-off |
| Duplicate names cause wrong updates | Use `Pris No.` and reject ambiguous matches |
| Network restrictions prevent image retrieval | Approved internal image registry or offline image bundle |
| Encryption keys are lost | Protected key custody, rotation records and recovery drills |
| Scope expands during build | Phase gates, change control and prioritised backlog |
| UiPath and application produce different outputs | Golden test workbooks and parallel stabilisation period |
| Incomplete tests for new features | Definition of done and mandatory CI coverage gates |

## 9. Immediate next actions

1. Complete the ordered Dependabot review queue (#20–25), refreshing and rerunning CI after each merge to the protected `main` branch.
2. Implement controlled institution/class/category reference data and workbook intake upload, staging, validation, preview, commit and reconciliation. Use `Pris No.` as the stable match key; never overwrite on ambiguous name-only matching.
3. Add a synthetic golden workbook fixture, malformed/oversized/hostile workbook tests, row-level validation tests, duplicate and stale-write tests, and migration preservation coverage with the import feature.
4. Keep each slice aligned to its CI gates and expand coverage for Compose runtime, import/export, and report reconciliation as those capabilities arrive.

## 10. Timetable integration workstream

The timetable system is added as a first-class workstream, with Amend 4-up treated as the primary user experience.

### Timetable phase A — Legacy inventory and migration adapter

**Estimated duration:** 1–2 weeks

- Inventory `.pri` projects, teachers, subjects, instructional classes, lesson requirements and placed slots.
- Capture the latest By Instructional Class and By Teacher PDFs as golden layout references.
- Define mappings from timetable instructional classes to intake/attendance classes.
- Build a read-only `.pri` import and validation tool.
- Report legacy composite teachers, invalid references, unplaced lessons and duplicate slots.

Exit criteria: a representative legacy project imports into a staging database with a reconciliation report and no silent data loss.

### Timetable phase B — Resources and scheduling draft

**Estimated duration:** 2–3 weeks

- Implement teachers, subjects, instructional classes, availability and lesson requirements.
- Implement deterministic draft generation with five days and four teaching periods, displayed as `P1`, `P2`, `Lunch`, `P3`, `P4`.
- Report unplaced lessons, class clashes, teacher clashes and availability failures.
- Make fixed school events configurable.
- Preserve approved versions when generating a replacement draft.

Resource setup is an explicit delivery slice before lesson scheduling:

- Build teacher profile CRUD with short code, full name, adjunct status and availability editor.
- Build subject and instructional-class reference data.
- Build class-cluster membership and period-definition management: seed a default period pattern for all classes, then allow class or cluster overrides.
- Build versioned scheduling-rule management and resolution for every planned class; reject missing, duplicate and overlapping rules.
- Build lesson-requirement CRUD with controlled teacher/subject/class selectors.
- Import and reconcile legacy teacher availability as 20 teaching slots; represent lunch as a non-schedulable display interval.
- Add tests for inactive teachers, duplicate codes, unavailable slots, weekly count and block length.
- Lesson API increment: stable foreign keys, one requirement per academic-year/class/teacher/subject combination, paginated reads, version-checked replacement/archive/restore and audited writes. Block planning preserves the weekly total with a shorter final block when needed. Period/cluster changes revalidate active requirements under a shared PostgreSQL transaction lock.
- Extend CI with lesson permission/lifecycle tests, real simultaneous-save and configuration-change races, database constraint checks, block-packing cases and a baseline-data upgrade preservation rehearsal.
- Add rule-completeness, rule-overlap, duplicate-placement and exactly-one-applicable-rule tests before generation and Amend 4-up placement.
- Rule increment tests cover date boundaries/open ends, missing/ambiguous bulk resolution, unresolved legacy binding, direct database overlap rejection and concurrent class/cluster or membership changes.
- Draft/placement tests now cover persistent lifecycle, class/teacher actual-time clashes, rule/availability/lunch/block invariants, midweek rule resolution, stale configuration/revision handling, simultaneous saves, lock protection, swap rollback in both directions and immutable approval. UI/browser tests remain pending.
- Timetable Excel exports now provide audited By InstClass and By Teacher workbooks from immutable version snapshots, with Executive access restricted to approved timetables. Legacy PDF golden comparison and attendance publishing coordination remain open phase-D items; see [TIMETABLE_REPORT_EXPORTS.md](TIMETABLE_REPORT_EXPORTS.md).
- Timetable publication now records a single current approved version per academic-year/week, with IT-only publish/unpublish, downstream lookup and audit events. Attendance class mapping/session consumption remains a distinct phase-D item; see [TIMETABLE_PUBLICATION.md](TIMETABLE_PUBLICATION.md).

Exit criteria: a draft can be generated, conflicts are visible and the legacy project can be compared slot-for-slot.

Resource setup exit criteria: an Operator can create a teacher profile, mark availability, create a lesson requirement using that profile and see invalid references rejected before generation.
Class-period exit criteria: every class resolves to the default period pattern unless an explicit class or cluster override exists; Period 3 remains lunch and cannot be made schedulable.
Scheduling-rule exit criteria: no planning run or manual placement can proceed without exactly one applicable rule per class, and no duplicate or overlapping rule/placement is accepted.

### Timetable phase C — Amend 4-up

The first browser increment covers class-oriented Amend 4-up editing. It is not yet full legacy parity; subsequent increments should add teacher-oriented views, drag/swap and other parity actions.

**Estimated duration:** 2–3 weeks

- Implement By Class and By Teacher modes.
- Implement 2/4/6/8/12/16/24/32 table density, paging and search.
- Implement double-click edit, drag/swap, shift, remove, lock and title rename.
- Implement click-to-add on empty teaching cells with the same controlled resource and conflict validation as lesson requirements.
- Validate all moves against teacher/class availability and double-booking.
- Ensure sort order never changes the real day/period being edited.
- Add draft save, audit events and return-to-schedule behavior.

Exit criteria: operators can correct a generated draft entirely in Amend 4-up, save it, reopen it and reproduce the same result.

### Timetable phase D — Reports and approval

**Estimated duration:** 1–2 weeks

- Generate By Instructional Class and By Teacher reports from the same approved version.
- Compare output against the latest supplied PDFs.
- Add version, timestamp and audit metadata.
- Add executive read-only timetable view and downloads.
- Add approval and publish status before attendance users consume the timetable.

Exit criteria: both report types reconcile with the approved grid and the report renderer does not mutate timetable data.

### Timetable testing gates

- Five-column rendering with lunch in the third column and four schedulable teaching periods.
- Lunch-column drop, edit and shift rejection.
- Teacher and class double-booking prevention.
- Composite-teacher behavior defined and tested.
- Locked-slot protection.
- Drag/swap validation in both directions.
- Edit-after-sort uses the visible weekday.
- Rename cascade and audit history.
- Draft versus approved version protection.
- PDF golden-file/layout comparison for both outputs.
- Import/export reconciliation with representative `.pri` projects.
- Teacher profile, availability and lesson-reference reconciliation.
- Resource setup permissions and audit events.
