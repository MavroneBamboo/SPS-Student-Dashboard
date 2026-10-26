# Attendance browser and transaction increment

Operators open **Attendance** in the actual browser application. Search class/date sessions with 25-row paging, or choose **New session**, select a class with current active students, date, Morning/Afternoon/Full day, expected count and optional notes. The active class count is a starting value for the expected count; the operator verifies it against the register. One class/date/session-type combination is permitted, including closed sessions.

Open a session to review entered records, unentered expected records and records explicitly marked MISSING. Use a Pris No. directly or search current eligible class students (25 displayed; refine when more match), select a student and save PRESENT, ABSENT, LATE, EXCUSED or MISSING. The backend validates current active status, class membership, duplicate records, session state and expected-count capacity. Selection is a convenience, never the authorization/eligibility boundary. Saved notes and correction reasons render as text.

Corrections keep the same student identity and require a new nonblank reason. Both the previous and new values/version are audited. A stale save keeps entered form values and requires **Reload session** to load the winning change; it never overwrites another operator's update. An expected-count adjustment requires a reason and cannot go below entered records. It is audited and versioned, allowing a deliberate count correction before adding more students.

Close a complete session normally. If records are unentered or marked MISSING, closure returns 409 unless the operator explicitly checks **Close incomplete attendance** and supplies a reason. Closed sessions are read-only and cannot be reopened or silently changed in this increment. The dashboard missing figure now includes both unentered expected records and explicit MISSING marks. Refresh the dashboard to see committed attendance.

## API and concurrency contract

Migration `20261026_0007` adds version=1 to existing sessions and records, and a unique class/date/type session index. It checks duplicate or untrimmed legacy sessions before DDL and fails with an explicit reconciliation requirement if found. It does not delete, merge or guess which historical record to retain. Clean existing fields, attendance and reasons are preserved. Downgrade refuses destructive removal of the version/uniqueness guarantees.

- `POST /attendance/sessions` retains date/type/class/expected-count/notes and returns a session version. Duplicate concurrent creation returns 409 through the database index.
- `GET /attendance/sessions` accepts class/date filters, offset and limit (default/max 100), returning the existing list shape. Invalid reversed date ranges return 422.
- `GET /attendance/sessions/{id}` returns the session, records and missing/marked-missing counts from a consistent session-locked read. The existing `/records` endpoint returns records with record/session versions.
- `POST /attendance/sessions/{id}/records` now requires `expected_session_version` alongside Pris No., mark and optional nonblank reason. A save increments the session version; the new record begins at version 1.
- `PATCH /attendance/records/{id}` now requires `expected_session_version`, record `expected_version`, the unchanged Pris No., mark and a nonblank correction reason. It advances both versions atomically.
- `PATCH /attendance/sessions/{id}` accepts `expected_version`, revised `expected_count` and reason. The class/date/type identity is immutable.
- `POST /attendance/sessions/{id}/close` now requires a JSON body with `expected_version`; optional `allow_incomplete=true` also requires a reason. It advances the session version and freezes normal API amendments.

These version fields/close bodies are required changes for clients of the original foundation API. PostgreSQL row locks serialize writes/read grids by session, and version comparisons reject stale clients. Adding records also locks the selected student row so a concurrent profile eligibility change is ordered with attendance creation. Duplicate/capacity/close checks run under the session lock. Record, session revision, audit and closure/count changes commit or roll back together; write responses are captured before releasing the transaction. SQLite is a migration/development convenience, not the proof of these production locking guarantees.

Raw session/record APIs now deny Executive access; Executives retain dashboard/report access. Support/bootstrap API roles retain the foundation's broader access pending complete permission-matrix hardening. Browser daily attendance controls are Operator-only. Sign-out, expiry or revoked-access responses clear attendance records, eligible lists and forms; old request/selection results cannot restore them.

## Boundaries and verification

Eligibility is still based on **current** active profiles and class membership. This is not a frozen or historical roster, and the UI says so. Expected counts are controlled register values, not proof of historical enrollment. Date-effective class/status reconciliation, roster snapshots, attendance granularity policy (including mixing FULL_DAY with other types), reopening/historical corrections, legacy monthly Excel output and complete permission hardening remain required before cutover. No claims of legacy reporting parity or production readiness follow from these screens.

CI adds lifecycle/missing/closure tests, duplicate session and record/close races, concurrent corrections, identity/reason/version checks, count controls, Executive denial and transaction-failure rollback. Migration rehearsals preserve existing rows/reasons and refuse ambiguous duplicate sessions without deleting data. Chromium tests exercise new-session prompts, lookup, marks, corrections, count adjustments, explicit incomplete closure, dashboard updates, stale forms/reload, duplicate sessions and sign-out clearing. The production image check includes the local attendance module; all prior browser, API, migration and security gates continue to run.
