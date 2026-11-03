# Academic year configuration

Academic years are shared reference data for student year-bound age snapshots, dashboard filters, lesson requirements, scheduling rules, timetable drafts and published-timetable attendance lookup.

## Administration

IT Administrators and Superusers manage years under **User administration → Student reference data**. Each year has a unique case-insensitive code, display label, start date, end date, active flag and optimistic version. The end date must be on or after the start date. Activating a year requires both dates. Dates are explicit configuration; the application does not infer them from a year label or from observed timetable/student data.

Operators, IT Administrators, Executives and Superusers can read the catalog. Only IT Administrators and Superusers can create or update it. Create/update actions are audited, version-checked, and deactivation preserves existing profile, lesson, rule and timetable history.

## Legacy migration

Migration `20261103_0019` collects distinct nonblank labels from student profiles, lesson requirements, scheduling rules and timetable versions. It preserves each label as a catalog code and display label, with no dates and an inactive state. No existing profile values, schedule records, ciphertext or snapshots are rewritten. An IT Administrator must confirm the correct dates and activate a legacy year before it can be assigned to a new profile or used for new schedule planning.

## Operational rules

- New or changed student academic-year assignments must reference a configured active year. Existing inactive year values remain readable; unrelated edits do not require historical configuration. The age snapshot remains manually entered and is never recalculated from DOB.
- New lesson requirements and active scheduling rules require an active configured year. Rule effective dates must fit inside that year's configured range.
- New weekly timetable drafts require an active configured year, and the Monday-to-Friday teaching week must fit inside its dates. Draft snapshots preserve their year label after later deactivation.
- Dashboard and published-timetable selectors are populated from the catalog. Historical inactive years remain available in dashboard filtering.
- The supported 2023 intake workbook retains its source year in imported profiles. Import preview/commit does not assign academic-year boundaries or activate a year on IT's behalf.

## API

- `GET /api/v1/student-reference/academic-years` is available to operational and Executive roles.
- `POST /api/v1/student-reference/academic-years` creates a dated year; `PATCH /api/v1/student-reference/academic-years/{id}` updates its label, both dates, and/or active state with `expected_version`.
- Student profile writes validate new year assignments. Lesson, active rule and draft creation APIs enforce the shared catalog and applicable date boundaries.

The catalog is not a replacement for effective-dated student class history. A year defines a reporting/planning period; it does not imply which class a student attended during that period.
