# Recurring timetable fixed events

## Purpose

IT Administrators and Superusers can configure school-specific recurring events without hard-coding legacy school values. Events can target all active classes or teachers, or an explicit list of targets, within one academic year. This supports events such as a teacher duty or class assembly while preserving the approved lunch definition: fixed-event slots accept teaching codes P1–P4 only, and the separate non-schedulable lunch row remains Period 3.

## Rules

- Each event has a required academic year, display label, audience (`CLASS` or `TEACHER`), target mode (`ALL` or `SELECTED`), and one or more weekday/teaching-period pairs. The editor shows timetable display labels; API slot keys remain P1–P4, with `LUNCH` excluded.
- Selected target IDs must be unique and reference active classes or teachers of the chosen audience. `ALL` events store no target IDs.
- An active event cannot overlap another active event in the same academic year and audience when their target sets and weekday/period pairs intersect. An all-target event overlaps every event of that audience at the same slot. Class and teacher events are separate audiences.
- Configuration writes and draft snapshot reads use the timetable transaction advisory lock. API writes are audited and event updates use an expected version. Deactivation preserves the definition and audit history.
- Fixed events reserve the matching class or teacher period. Both the shared manual validator and automatic generator reject lesson placements in reserved cells, so a newly configured event cannot be double-booked. Events do not create lesson placements or change teacher availability. The browser, print view and workbook show the event label in an otherwise empty cell; an immutable historical snapshot continues to show its stored lesson if one exists.
- A draft snapshot captures applicable event definitions, target IDs, slots and versions. Any subsequent event change makes a draft stale; operators must create a replacement draft before changing placements or approving it. Approved versions and exports continue to render from their original snapshot.

## API

- `GET /api/v1/timetable/fixed-events`: read all definitions; Superuser, IT Administrator, Operator and Executive.
- `POST /api/v1/timetable/fixed-events`: create; Superuser and IT Administrator.
- `PUT /api/v1/timetable/fixed-events/{id}`: update or activate/deactivate using `expected_version`; Superuser and IT Administrator.

The `/ui/` **Fixed events** workspace provides the same management flow, including all/selected targets, a weekday-by-period selector, edit and activation controls. All permitted roles can read the table; write controls are limited to IT Administrators and Superusers.

Class/teacher browser boards, print reports and audited By InstClass/By Teacher workbooks render an event only in an otherwise empty cell. Historical versions without `fixed_events` remain readable and export normally.

## Data and verification

Migration `20261110_0020` adds the event definition table without changing student, attendance, timetable, or user records. JSON fields store target IDs and weekday/period pairs; schema validation and the shared PostgreSQL configuration lock enforce uniqueness and overlap rules across API writers. The tests cover role boundaries, invalid definitions, overlap behavior, optimistic updates, snapshot staleness and XLSX output.
