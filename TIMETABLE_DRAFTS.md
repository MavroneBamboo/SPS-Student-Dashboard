# Timetable drafts and manual amendments

The timetable API persists weekly drafts, immutable configuration snapshots, lesson blocks and occupied grid cells. The production browser follows the supplied timetable UI reference with By class and By teacher weekly boards, report/print screens, resource tabs, period/rule management and a recurring fixed-events workspace. Its board mode supports clickable lesson placement/edit/removal/locking; Amend 4-up supports 2/4/6/8/12/16/24/32 class paging, clickable editing, atomic swaps, drag/drop moves to empty slots and swaps onto occupied unlocked slots within the same class, and draft rename. The visible week is P1, P2, P3 Lunch/Muster, P4 and P5, using existing stable API slot codes. Configured class and teacher events reserve their matching slots against manual and generated lessons and appear in those cells in the browser, print view and XLSX reports. Browser print generates class/teacher report layouts for Save as PDF. The API also generates audited Excel workbooks for By InstClass and By Teacher from a version's stored snapshot; see [TIMETABLE_REPORT_EXPORTS.md](TIMETABLE_REPORT_EXPORTS.md) and [TIMETABLE_FIXED_EVENTS.md](TIMETABLE_FIXED_EVENTS.md). Copy/rebase, broader legacy parity and server-side PDF output remain subsequent work.

## Create and inspect a draft

Operators and IT Administrators can create a draft with `POST /api/v1/timetable/versions`:

```json
{"name":"Week 43 draft","academic_year":"2026","week_start":"2026-10-19","class_ids":[1,2]}
```

`week_start` must be a Monday. Every selected class must be active and resolve exactly one rule on each of the five teaching dates. A midweek rule transition is captured separately for each weekday. The snapshot stores class labels/periods, resolved rule IDs/versions/definitions, active lesson requirements, teacher availability/labels and subject labels. This is a new version: creating it does not replace any earlier version or its amendments.

`GET /versions` lists summaries with academic-year filtering and pagination. `GET /versions/{id}` returns the snapshot, placements and pending lesson requirements. Reads return a consistent revision/grid under the timetable transaction lock. A pending requirement reports remaining periods and block lengths. Approved versions continue to render from their snapshots after live reference data changes.

## Amend blocks

Create a block at `POST /versions/{id}/placements` under `/api/v1/timetable`:

```json
{"expected_revision":1,"lesson_requirement_id":10,"weekday":"MON","start_period":"P1","period_count":2,"note":""}
```

The requirement must belong to the snapshot. A length-two requirement normally places double blocks; a weekly count of three accepts one double and one single remainder. Extra blocks and the wrong block-size distribution are rejected. A block is indivisible when moved or removed. The five display columns remain P1, P2, Lunch, P3, P4; lunch is the third display column and cannot receive a placement or be crossed by a block.

All mutations require the last loaded version revision and return the updated grid/revision:

- `PUT /versions/{id}/placements/{placement_id}` replaces the block's requirement, weekday, start period, size and note using the same payload as creation.
- `DELETE /versions/{id}/placements/{placement_id}?expected_revision=N` removes an unlocked block and returns its periods to the pending list.
- `PATCH /versions/{id}/placements/{placement_id}/lock` accepts `expected_revision` and `is_locked`; a locked block must be explicitly unlocked before editing, moving, swapping or removal.
- `PATCH /versions/{id}/placements/{placement_id}/move` accepts `expected_revision`, `weekday` and `start_period` to move one unlocked block without changing its lesson requirement, size or note.
- `POST /versions/{id}/swap` accepts `expected_revision`, `first_placement_id` and `second_placement_id`. Both complete blocks exchange weekday/start positions; both destinations and the entire resulting grid are validated together.
- `PATCH /versions/{id}/name` accepts `expected_revision` and a trimmed 1–120 character name. Draft rename increments the revision and records the old/new names; approved versions cannot be renamed.

The Amend 4-up browser exposes swaps through a deliberate selection workflow: enter swap mode, select two unlocked blocks, confirm, then receive the refreshed revision. Operators can drag an unlocked block onto an empty slot to move it or onto another unlocked block in the same class to swap them; the API revalidates the complete destination and draft atomically. The lesson editor remains the keyboard-accessible way to choose a block's weekday and start period. Locked blocks cannot be moved. Drafts can be renamed from the version header. A server validation or stale-revision failure keeps the saved grid unchanged; the user can reload the current draft and retry.

Validation checks rule completeness/currentness, allowed days/periods, maximum daily lessons, teacher availability, required weekly block counts, contiguous times and class/teacher conflicts. Composite teacher profiles are created by IT at `POST /api/v1/timetable/teacher-groups` from at least two active individual teachers; nested groups are rejected. Draft snapshots retain each group's member IDs and each member's availability. A team lesson is available only when every member is available, and every member is checked independently for actual-time clashes with individual teachers and other groups. The PostgreSQL slot trigger enforces the same member-aware clash rule against the immutable snapshot. By Teacher boards and exports show group lessons for each member as well as the group profile. Teacher `ALL` remains a fixed-school-event mapping and is not represented as an ordinary teacher group. Teacher and class conflicts compare actual start/end intervals, including class/cluster period overrides; shared period labels alone do not determine a clash. Each block must fit within a contiguous teaching run, excluding lunch, configured gaps and the end of the day. Weekday values are stable identifiers rather than visual row indexes.

A stale client revision returns 409. Failed validation, swaps and database conflicts leave revision, placements, cells and audit history unchanged. All material changes and audit events commit in one transaction. PostgreSQL also guards occupied-cell uniqueness, snapshot resource/time consistency, actual-time double booking, locked blocks and approved records. SQLite is for development and does not supply these production trigger/concurrency guarantees.

## Configuration changes and approval

Every edit and approval re-resolves rules for all five dates and compares the live configuration with the stored snapshot under the shared transaction lock. A changed relevant rule/resource/requirement/period makes the draft stale; reconcile live rules if needed and create a replacement draft. This increment preserves the old draft and does not silently rewrite its snapshot. Copy/rebase workflows are not yet implemented.

IT Administrators and Superusers can approve a complete, valid draft using `POST /versions/{id}/approve` with `expected_revision`. Approval fails while any requirement remains unplaced or configuration has changed. Approval records the actor/time and increments the revision. Approved header, blocks, cells and selected classes are immutable; replacements use a new version. Operators cannot approve. Executives can list/read approved versions only.

Each version is a self-contained planning/reporting unit. Clash checks apply within that version. IT Administrators can publish one approved version per academic-year/week; publishing a replacement clears the prior current flag but preserves the approved version and audit history. `GET /api/v1/timetable/published` exposes the frozen version for downstream readers. Operators can load classes scheduled for a date and create provenance-linked attendance sessions after IT maps profile class names to instructional classes; manual attendance sessions remain available without timetable provenance. The publish and attendance flow is documented in [TIMETABLE_PUBLICATION.md](TIMETABLE_PUBLICATION.md) and [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md). The generation API fills pending blocks or explicitly replaces unlocked blocks using the same validations. The browser includes redesigned By class/By teacher boards, Amend 4-up, composite teacher profiles and print-ready reports. Automatic legacy `.pri` group reconciliation, fixed school events and server-generated PDF output remain outstanding.

## Verification

Every mutation expands the stored blocks through the shared validator and compares the complete expected cell multiset with persisted cells, including parent block, resources, weekday, period and actual times. Missing, extra or mismatched cells return 409 before any write or audit event. This protects approval from an incomplete grid following direct database maintenance. Reads remain available for IT investigation; the API does not silently repair damaged data. Repair must restore consistency or use a replacement draft. Regression tests exercise missing cells, extra cells and changed block anchors, checking that rejected requests preserve the grid, revision and audit history.

CI runs PostgreSQL migration/model parity, full API lifecycle tests, revision races, two-direction swap rollback, single-block move conflict/lock/stale-revision checks, audited draft rename and approved-version immutability, actual-time conflicts under overrides, rule/availability/lunch/block checks, remainder counts, approval permissions, snapshot history and direct database immutability checks. Chromium covers drag/drop movement and draft rename in Amend 4-up. Migration `0005` only adds timetable tables/guards; existing student/profile/rule data is preserved, with the existing upgrade rehearsal exercising the complete migration chain.
