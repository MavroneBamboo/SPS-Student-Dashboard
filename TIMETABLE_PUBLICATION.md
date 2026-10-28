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

This slice provides the version pointer and an authenticated read API for downstream consumers. Mapping published instructional classes to student attendance classes and using the published schedule to create or prefill attendance sessions remain separate integration work. The existing intake class crosswalk is explicitly source-specific and is not silently reused as an attendance mapping.

## Verification

PostgreSQL tests cover IT-only mutation, approved-only publication, stale revisions, replacement of the one current weekly version, unpublish behavior, audit history, Executive visibility and unchanged timetable revision. Browser acceptance covers the IT publish/unpublish controls and published-version lookup.
