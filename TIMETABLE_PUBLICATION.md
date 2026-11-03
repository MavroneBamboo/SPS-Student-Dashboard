# Timetable publication

An approved weekly timetable becomes available to downstream readers only after an IT Administrator publishes it. Publication does not edit the approved schedule grid and does not increment its content revision.

## Current publication rules

- At most one version is current for an `(academic_year, week_start)` pair. A partial unique database index protects this invariant.
- Only IT Administrators can publish or unpublish. An unapproved draft and a stale expected revision are rejected.
- Publishing a replacement clears the current flag from the previously published version in the same transaction. The old version remains approved, immutable and reportable; its last publication timestamp and actor are retained.
- Unpublishing leaves no current version for that week. It does not delete or alter timetable history.
- Publish, replace and unpublish actions write audit events. Executive, Operator and IT clients can query currently published versions by academic year and optional week; the response contains the frozen snapshot and placements.

## API

- `POST /api/v1/timetable/versions/{id}/publish` with `{"expected_revision": N}`
- `POST /api/v1/timetable/versions/{id}/unpublish` with `{"expected_revision": N}`
- `GET /api/v1/timetable/published?academic_year=2026&week_start=2026-10-26`
- `GET /api/v1/timetable/published?academic_year=2026&offset=0&limit=20`

Publication fields are included in timetable summaries. The production timetable workspace shows current publication status and exposes publish/unpublish actions to IT Administrators only.

Attendance integration uses a separate IT-managed mapping from the normalized student profile `class_name` to one instructional class. Each profile class and instructional class can have only one mapping. This is intentionally independent of the Student Intake 2023 crosswalk, whose labels are specific to that workbook. Mapping updates are versioned and audited.

Operators can call `GET /api/v1/attendance/scheduled-classes?academic_year=2026&session_date=2026-10-26` to find classes with teaching slots on a date in the currently published timetable. Results include the immutable version ID, instructional class, mapped profile class, lesson count and current active roster count. `POST /api/v1/attendance/sessions` may include both `timetable_version_id` and `instructional_class_id`; the server revalidates publication, week, weekday, class mapping and lesson availability before it captures the usual roster snapshot. Session provenance remains even if the timetable is later unpublished or replaced. Existing manual session creation remains available and stores null timetable provenance.

Migration `20261103_0014` creates the attendance-specific class mapping and adds paired nullable timetable provenance fields to attendance sessions. Existing session data and roster snapshots are retained. An unmapped instructional class is not offered as a scheduled attendance class; IT must configure the mapping first.

## Verification

PostgreSQL tests cover IT-only mutation, approved-only publication, stale revisions, replacement of the one current weekly version, unpublish behavior, audit history, Executive visibility and unchanged timetable revision. Attendance integration tests cover mapping uniqueness/permissions, active roster counts, scheduled class lookup, date/day validation, saved publication provenance, unpublished-version rejection and unchanged manual session behavior. Browser acceptance covers the IT publish/unpublish controls and published-version lookup.
