# Timetable drafts and manual amendments

The timetable API now persists weekly drafts, immutable configuration snapshots, lesson blocks and their occupied grid cells. It supports the server operations needed by Amend 4-up. Automatic generation is documented in [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md). The production browser workspace, copy/rebase of drafts and timetable exports remain subsequent work.

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
- `POST /versions/{id}/swap` accepts `expected_revision`, `first_placement_id` and `second_placement_id`. Both complete blocks exchange weekday/start positions; both destinations and the entire resulting grid are validated together.

Validation checks rule completeness/currentness, allowed days/periods, maximum daily lessons, teacher availability, required weekly block counts, contiguous times and class/teacher conflicts. Teacher and class conflicts compare actual start/end intervals, including class/cluster period overrides; shared period labels alone do not determine a clash. Each block must fit within a contiguous teaching run, excluding lunch, configured gaps and the end of the day. Weekday values are stable identifiers rather than visual row indexes.

A stale client revision returns 409. Failed validation, swaps and database conflicts leave revision, placements, cells and audit history unchanged. All material changes and audit events commit in one transaction. PostgreSQL also guards occupied-cell uniqueness, snapshot resource/time consistency, actual-time double booking, locked blocks and approved records. SQLite is for development and does not supply these production trigger/concurrency guarantees.

## Configuration changes and approval

Every edit and approval re-resolves rules for all five dates and compares the live configuration with the stored snapshot under the shared transaction lock. A changed relevant rule/resource/requirement/period makes the draft stale; reconcile live rules if needed and create a replacement draft. This increment preserves the old draft and does not silently rewrite its snapshot. Copy/rebase workflows are not yet implemented.

IT Administrators approve a complete, valid draft using `POST /versions/{id}/approve` with `expected_revision`. Approval fails while any requirement remains unplaced or configuration has changed. Approval records the actor/time and increments the revision. Approved header, blocks, cells and selected classes are immutable; replacements use a new version. Operators cannot approve. Executives can list/read approved versions only, while bootstrap Superusers have no timetable-planning access.

Each version is a self-contained planning/reporting unit. Clash checks apply within that version; a current-published-version pointer and coordination of separate published plans remain part of the future publishing workflow. The generation API fills pending blocks or explicitly replaces unlocked blocks using the same validations. The production Amend 4-up browser, combined-teacher groups, fixed school events and PDF rendering remain outstanding.

## Verification

Every mutation expands the stored blocks through the shared validator and compares the complete expected cell multiset with persisted cells, including parent block, resources, weekday, period and actual times. Missing, extra or mismatched cells return 409 before any write or audit event. This protects approval from an incomplete grid following direct database maintenance. Reads remain available for IT investigation; the API does not silently repair damaged data. Repair must restore consistency or use a replacement draft. Regression tests exercise missing cells, extra cells and changed block anchors, checking that rejected requests preserve the grid, revision and audit history.

CI runs PostgreSQL migration/model parity, full API lifecycle tests, revision races, two-direction swap rollback, actual-time conflicts under overrides, rule/availability/lunch/block checks, remainder counts, approval permissions, snapshot history and direct database immutability checks. Migration `0005` only adds timetable tables/guards; existing student/profile/rule data is preserved, with the existing upgrade rehearsal exercising the complete migration chain.
