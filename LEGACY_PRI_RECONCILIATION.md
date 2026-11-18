# Legacy `.pri` reconciliation findings

Reviewed 18 November 2026 from the legacy TImeTables source and representative local `.pri` samples. Counts below are aggregate counts; this document intentionally omits personal/resource names and decrypted field values. The source archives were only read by the bounded validator and were not changed. Automated tests exercise import with synthetic archives; no representative legacy archive has been imported into staging.

## Slot and availability interpretation

| Legacy numeric period | Replacement display | Import treatment |
|---:|---|---|
| 1 | P1 | Teaching slot |
| 2 | P2 | Teaching slot |
| 3 | Lunch | Never a teaching slot; report for review |
| 4 | P3 | Teaching slot |
| 5 | P4 | Teaching slot |

The legacy availability dialog stores 20 flags in weekday-major order: four teaching periods for Monday, then Tuesday through Friday. This matches the replacement's four schedulable slots; a deterministic helper maps the flags to `MON`–`FRI` / `P1`–`P4` during import. Some saved projects contain 25 binary flags; the legacy UI does not explain that shape. Such profiles are reported as `legacy_availability_mapping_required` and block import. The importer does not guess their meaning.

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

After the redacted report, IT Administrators and Superusers may explicitly choose **Inspect source labels for mapping**. This separate audited endpoint reveals teacher, subject and class labels plus lesson-requirement references so IT can reconcile source rows to dashboard resources. Names are not written to audit events, and sign-out clears the displayed source data. The archive is still processed in memory and discarded; inspection does not create or change resources.

After inspection, IT can map each source teacher, subject and class to an existing application resource. Composite teacher references require an existing composite group whose member IDs exactly match the mapped source teachers. The importer does not create or alter resource profiles. It creates a weekly DRAFT, creates missing lesson requirements transactionally, reuses only exact active matches, packs source periods into configured lesson blocks and validates every placement with the shared timetable rules. Any conflicting requirement, duplicate mapping, schedule clash or incomplete mapping rolls back the whole import.

The import request is processed in memory and is bounded to a 10 MiB archive plus 256 KiB of mapping options. The application stores no .pri file; it stores a SHA-256 fingerprint with academic year/week and draft ID. A unique database constraint prevents the same archive from being imported twice for a given week, including concurrent attempts. Audit data contains the fingerprint and aggregate counts, never decrypted labels. Imported drafts remain unapproved and unpublished. Lunch placements, ALL whole-school entries, pending/unplaced rows and ambiguous 25-flag availability profiles are rejected for reconciliation. Preserve the original archive in its controlled source location because the application does not back it up.

Synthetic automated tests cover mapping, transaction, validation and duplicate protection. A representative source archive still needs a witnessed staging import and row/slot reconciliation before migration sign-off.
Successful decryption is not proof of archive integrity because the legacy AES-CBC format has no authentication tag. Preserve the source archive and reconcile the generated draft against it. Synthetic tests cover the import boundary; representative staging verification and business sign-off remain open.
