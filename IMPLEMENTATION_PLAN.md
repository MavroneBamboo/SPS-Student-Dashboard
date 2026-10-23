# SPS Student Dashboard

## Implementation Plan

**Version:** 1.0  
**Status:** Proposed delivery plan  
**Companion document:** [TECHNICAL_DESIGN_DOCUMENT.md](TECHNICAL_DESIGN_DOCUMENT.md)

## 1. Delivery approach

Build the system in vertical increments. Each increment must produce a deployable, tested slice rather than a large unverified handover. The team should maintain a single backlog, protect `main`, require pull requests and run the full CI pipeline on every change.

The initial release should be delivered in phases over approximately 16–20 weeks, subject to staffing, environment approval and data-migration complexity. Dates are planning estimates, not commitments.

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
- Test encrypted backups and restore.
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

Every pull request must run:

1. Formatting and linting.
2. Static analysis and dependency lock checks.
3. Unit and service tests.
4. API/integration tests using an isolated database.
5. End-to-end role and workflow tests.
6. Database migration up/down or forward-upgrade tests.
7. Docker Compose health and startup tests.
8. Dependency, container and secret scans.
9. Coverage and critical-test thresholds.

The release pipeline additionally performs artifact signing or integrity recording, deployment validation, smoke tests and approval gates. A failed security or migration gate blocks promotion.

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

1. Approve this TDD and identify technical decision owners.
2. Confirm the application/database stack and internal hosting target.
3. Confirm authentication integration and key-management approach.
4. Convert Phase 0 and Phase 1 deliverables into tracked issues.
5. Build the minimal Compose stack and CI pipeline first.
6. Establish the acceptance-test catalogue before profile implementation.

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
- Build lesson-requirement CRUD with controlled teacher/subject/class selectors.
- Import and reconcile legacy teacher availability as 20 teaching slots; represent lunch as a non-schedulable display interval.
- Add tests for inactive teachers, duplicate codes, unavailable slots, weekly count and block length.

Exit criteria: a draft can be generated, conflicts are visible and the legacy project can be compared slot-for-slot.

Resource setup exit criteria: an Operator can create a teacher profile, mark availability, create a lesson requirement using that profile and see invalid references rejected before generation.
Class-period exit criteria: every class resolves to the default period pattern unless an explicit class or cluster override exists; Period 3 remains lunch and cannot be made schedulable.

### Timetable phase C — Amend 4-up

**Estimated duration:** 2–3 weeks

- Implement By Class and By Teacher modes.
- Implement 2/4/6/8/12/16/24/32 table density, paging and search.
- Implement double-click edit, drag/swap, shift, remove, lock and title rename.
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
