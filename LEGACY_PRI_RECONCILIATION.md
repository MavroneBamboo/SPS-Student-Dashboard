# Legacy `.pri` reconciliation findings

Reviewed 10 November 2026 from the legacy TImeTables source and representative local `.pri` samples. Counts below are aggregate counts; this document intentionally omits personal/resource names and decrypted field values. The source archives were only read by the bounded validator and were not changed. No staging database import was run.

## Slot and availability interpretation

| Legacy numeric period | Replacement display | Import treatment |
|---:|---|---|
| 1 | P1 | Teaching slot |
| 2 | P2 | Teaching slot |
| 3 | Lunch | Never a teaching slot; report for review |
| 4 | P3 | Teaching slot |
| 5 | P4 | Teaching slot |

The legacy application source defines 20 availability flags for four teaching periods across five weekdays. Some saved projects contain 25 binary flags. The validator recognizes both shapes, but neither is silently rewritten into the replacement availability model. Confirm the intended meaning of 25-entry profiles with the operator before migration.

Period 3 placements are excluded from lesson occupancy and placed-versus-required totals. A period-3 row with a named teacher is flagged `lesson_in_lunch_slot`. A blank-teacher period-3 row is flagged `lunch_entry_requires_review` so a legacy placeholder is visible and cannot be mistaken for a confirmed lesson. A period-3 `ALL` row also requires whole-school event mapping.

## Representative sample aggregates

| Sample | Classes | Teachers | Subjects | Requirements | Placement rows | Period 3 findings |
|---|---:|---:|---:|---:|---:|---|
| 24 February 2026 | 19 | 50 | 34 | 93 | 172 | 37 assigned-teacher rows; flagged as lunch conflicts |
| 29 June 2026 | 20 | 37 | 22 | 115 | 296 | 100 blank-teacher placeholders; flagged for review, one per class/day |
| 29 June 2026, converted copy | 20 | 37 | 21 | 113 | 286 | 90 blank-teacher placeholders; flagged for review |

The 29 June sample also contains 24 `ALL` rows outside the lunch-slot handling and 15 composite-teacher placements. These require explicit event/teacher mapping. The validator does not expand composites or infer which teacher is responsible.

## Validation and import boundary

The read-only validator checks archive/member bounds, exact encrypted member names, resource references, duplicate class/teacher occupancy, requirement counts, availability shape, and special teacher/event mappings. It emits aggregate counts and row-indexed issue codes; it does not expose values by default, mutate the `.pri`, or write to the application database.

## Archive format verification

The checked-in legacy source defines a `periodsFile` path for `R07.bin` and comments that configurable periods are saved there. A source search of the current save/load implementation found no code that reads or writes that member. The implemented and observed project format remains exactly six encrypted JSON members, `R01.bin` through `R06.bin`. The dashboard parser therefore accepts only that verified format; it does not infer or accept an undocumented seventh member. Revisit this contract if a real project produced by a later legacy build demonstrates otherwise.

IT Administrators and Superusers can run the same bounded preflight from **Legacy timetable preflight** in the application. The browser sends the archive as an in-memory binary upload capped at 10 MiB, matching the reverse proxy limit. The API reads the six encrypted members in memory, returns only aggregate counts, period mappings and issue codes, and writes a redacted audit event. It does not persist the uploaded archive or import any records. Configure `LEGACY_PRI_KEY_HEX` in the protected environment file to enable this feature; leave it unset when legacy preflight is not required. Do not put the key in source control or print it in terminal output.

Successful decryption is not proof of archive integrity because the legacy AES-CBC format has no authentication tag. Before an importer is approved, an operator must reconcile resource names to stable application IDs, confirm availability semantics, review lunch placeholders and conflicts, resolve composite and `ALL` rows, and receive a no-data-loss reconciliation report. Import must preserve source backups and be repeatable without duplicate creation.
