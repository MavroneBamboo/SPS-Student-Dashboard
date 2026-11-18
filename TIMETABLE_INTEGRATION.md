# Timetable Integration Notes

Resource lifecycle delivery (18 November 2026): the `/ui/` **Classes & teachers** workspace now lets IT Administrators and Superusers edit teacher, subject and instructional-class profiles, then deactivate or reactivate them. The API returns a deterministic SHA-256 revision for each resource; updates require that revision, serialize with timetable configuration writes, and record audit events. Deactivation is blocked while active scheduling dependencies remain. Teacher availability changes recalculate composite-group availability and are rejected if they would invalidate active lesson requirements. No schema migration is needed. The API and Chromium workflows are covered by `tests/test_timetable_resource_lifecycle.py` and `browser_tests/test_timetable.py`.

Attendance integration (3 November 2026): operators can create provenance-linked attendance sessions from classes scheduled in the currently published timetable, using a separate IT-managed attendance class mapping. Manual session creation remains supported. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md) and [TIMETABLE_PUBLICATION.md](TIMETABLE_PUBLICATION.md).

Profile boundary (26 October 2026): the production browser now supports core student profile processing and status history. Student class names still need an explicit mapping to instructional timetable class IDs during reconciliation; this increment does not infer that mapping or create timetable memberships. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md).

UI redesign (27 October 2026): the actual `/ui/` timetable workspace follows the supplied “SPS Timetable — UI UX Redesign” reference: navy timetable sidebar, By class / By teacher weekly boards, selected class/teacher controls, report export/print view, teacher/class/subject resource tabs and a separate periods/rules screen. Clickable Amend 4-up supports all legacy class page sizes (2/4/6/8/12/16/24/32), same-class drag moves and occupied-block swaps with the shared validator. Period display is P1, P2, P3 Lunch/Muster, P4 and P5 while stable API slot codes remain unchanged. Default periods can be edited; class/cluster overrides replace matching defaults for future drafts. Superuser, IT and Operator access follows the backend role matrix. Recurring fixed events support configurable class/teacher targets, reserve lesson slots and appear in the timetable, print view and exports. PDF export opens a browser print view; native server-generated PDF formatting and legacy `.pri` group reconciliation remain follow-up work. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md), [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) and [TIMETABLE_FIXED_EVENTS.md](TIMETABLE_FIXED_EVENTS.md).

Generation increment (26 October 2026): the backend supports deterministic weekly generation with bounded iterative repair, shared manual validations, per-block unplaced explanations and persisted revision-linked reports. Fill-pending preserves existing blocks; explicit replace-unlocked retains all locked blocks. Composite teacher groups can be configured from individual profiles and are checked for every member's availability and timetable clashes. Recurring fixed events reserve configured class and teacher slots. See [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) and [TIMETABLE_FIXED_EVENTS.md](TIMETABLE_FIXED_EVENTS.md). The audited legacy preflight and explicit resource-mapping import are implemented; import creates only an unapproved draft. Representative staging import and slot-by-slot business reconciliation remain outstanding. Publishing coordination is implemented; server-side PDF parity remains follow-up work. Earlier increment descriptions below record their delivery sequence.

## 1. Source system reviewed

The legacy source is `D:\RPA\TImeTables-legacy`, a .NET 9 Windows Forms application called **Prison School Timetables**. It schedules instructional class groups, teachers, subjects and weekly lesson requirements, then generates two reports:

- `Timetable By InstClass.pdf`
- `Timetable By Teacher.pdf`

The latest supplied PDFs at `C:\Users\Prisuser\Downloads\` are treated as the current visual and content references for the replacement report renderer.

The current timetable layout is five weekdays with four teaching periods and a lunch interval: `P1`, `P2`, `Lunch`, `P3`, `P4`. Period 3 is the lunch column in the displayed report layout; it is not a teaching slot.

**Source/version discrepancy:** the latest `TImeTables-legacy` changelog and `FormAmend.cs` instead show five teaching periods (`P1`–`P5`), with 12:00–13:25 as teaching Period 3; the teacher PDF separately overlays “Lunch / Master” at that position. The product owner has explicitly directed that Period 3 be lunch and non-schedulable in the replacement. This implementation follows that instruction (four teaching periods plus lunch) and therefore must not claim slot-for-slot compatibility with the latest legacy `.pri` files until the mapping is approved and reconciled.

## 2. Existing workflow

```text
Teachers + availability
Subjects
Instructional classes
Lesson requirements
        ↓
Greedy first-fit schedule generation
        ↓
Pending/unplaced lesson review
        ↓
Manual schedule corrections
        ↓
Amend 4-up review and save
        ↓
By InstClass + By Teacher PDF export
```

The legacy project is a `.pri` ZIP containing six AES-encrypted JSON members (`R01.bin`–`R06.bin`). The read-only validator checks this fixed member set, enforces archive size limits, decrypts in memory, and reconciles resource references and placements without modifying the source. IT Administrators and Superusers may separately reveal source labels and requirement references to support explicit resource reconciliation; audit events contain counts and issue codes only, and the source archive is not persisted. Reconciliation of the checked samples established the legacy numeric slot map as 1→P1, 2→P2, 3→LUNCH, 4→P3, 5→P4 for the replacement product. Period 3 is never imported as a lesson: rows with an assigned teacher are reported as `lesson_in_lunch_slot`; blank-teacher lunch rows are retained as `lunch_entry_requires_review`. The legacy availability UI stores 20 flags in weekday-major order, four teaching periods per weekday; a deterministic helper maps this verified shape to the replacement's `MON`–`FRI` and `P1`–`P4` model during import. The meaning of 25-entry profiles remains unverified, so they block import and require external reconciliation before retry. Composite teacher references map only to existing groups with exact source members; the legacy `ALL` whole-school event requires fixed-event reconciliation. The legacy encryption key is embedded in the old application source and must be supplied to the validator through `LEGACY_PRI_KEY_HEX`; links use names rather than stable IDs, and item IDs are list positions. AES-CBC has no authentication tag, so decryption is not an integrity check. IT Administrators and Superusers can map source rows to existing resources and create a validated draft through the audited import flow. It rejects unresolved lunch, whole-school, pending and ambiguous availability data. Representative staging import and slot-by-slot reconciliation remain required.

Sample audit evidence (aggregate counts only; source names and personal values are not included) and the mapping decisions are recorded in [LEGACY_PRI_RECONCILIATION.md](LEGACY_PRI_RECONCILIATION.md). The preflight remains read-only; import is a separate explicit action. The importer rejects ambiguous 25-entry availability arrays and does not silently reinterpret them.

Run the validator from the repository root after setting `LEGACY_PRI_KEY_HEX` to the hex-encoded legacy key in the current PowerShell process:

```powershell
$env:LEGACY_PRI_KEY_HEX = '<hex-encoded key from TImeTables-legacy source>'
python scripts/validate_legacy_pri.py 'D:\path\to\project.pri'
Remove-Item Env:LEGACY_PRI_KEY_HEX
```

It prints aggregate counts and issue codes by default. Add `--details` for row-indexed issue locations. Exit code `1` means reconciliation found issues or import blockers; `2` means the archive could not be read safely.

IT Administrators and Superusers can also run a 10 MiB bounded preflight from **Legacy timetable preflight** in the application. The API uses `LEGACY_PRI_KEY_HEX` from the protected environment file, processes the encrypted archive in memory, and returns aggregate results with issue codes and source indexes but no names. The UI shows 1-based issue locations; a separate audited inspection reveals the matching resource, requirement and placement rows. Each source collection is capped at 5,000 rows. Preflight records a redacted audit event and does not retain or import the file. The existing CLI remains available for offline projects up to the validator's 25 MiB archive bound.

## 2.1 Resource setup is a prerequisite

The scheduler cannot add a teacher implicitly. The operator or administrator must first maintain the resource profiles used by lesson requirements:

1. **Teachers** — short code, full name, adjunct flag and availability by day/period.
2. **Subjects** — name, short code and description.
3. **Instructional Classes** — name, short name and description/reporting order.
4. **Lessons** — subject, teacher, instructional class, periods per week (`Count`) and block length (`Length`).

Class setup also includes cluster membership and period configuration. Every class starts with the default period pattern (`P1`, `P2`, `Lunch`, `P3`, `P4`). A period created for a single class or cluster may override the matching default without changing unrelated classes. Period 3 remains the lunch interval and cannot be converted into a teaching period.

### Initial production API increment

The initial timetable resource increment defined authenticated API routes under `/api/v1/timetable` for teachers, subjects, classes, clusters, membership, periods and resolved class periods. It seeded the five-column pattern, enforced unique period definitions and class-over-cluster-default inheritance, and audited IT-only writes. At that point the increment was backend-only; later slices added resource editing, lesson requirements, rules, generation and persistent Amend 4-up workflows.

The lesson API at `/api/v1/timetable/lessons` supports Operator and IT Administrator create/list/retrieve, version-checked replacement, archive and restore. Requirements use resource IDs and reject duplicate academic-year/class/teacher/subject combinations. Weekly count is split into full consecutive blocks plus a shorter remainder; unavailable periods, lunch and time gaps break blocks. Active-resource and inherited-period checks run centrally, and configuration changes cannot invalidate active requirements, including during concurrent PostgreSQL writes. Scheduling rules, complete-grid clash validation, generation and Amend 4-up now use the shared planning validation; see [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) and [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md).

Scheduling rules are a required prerequisite for every planning run. Each class must resolve to one and only one applicable rule set. Missing, duplicated or overlapping class/cluster rules must prevent generation and manual placement; duplicate timetable placements are also rejected.

The lesson editor uses controlled selectors populated from these profiles and rejects references to missing or inactive teachers, subjects and instructional classes. Teacher availability is managed in the resource workspace; requirement validation, schedule generation and Amend 4-up placement use the shared availability rules.

The legacy source serialises availability as a colon-separated array of 20 teaching slots. The visual report has a lunch column for daily alignment, but lunch must remain non-schedulable. The replacement system uses a day/period availability model. IT can create named composite teacher groups from individual profiles; all members must be available and are independently checked for clashes. Composite source references can map only to an existing group whose member IDs match the selected source teachers. `ALL` whole-school entries still require fixed-event reconciliation before import.

The production application exposes resource setup before scheduling. IT Administrators and Superusers maintain versioned teacher, subject and class profiles, clusters, default periods and class/cluster overrides; Operators create lesson requirements and work with the draft timetable. Resource edits are audited, use stale-write protection and preserve stable IDs and approved snapshots.

## 3. Why Amend 4-up is the key capability

The production backend persists weekly drafts and supports add/amend/move, atomic swap, remove and block lock/unlock. It snapshots rules, resource labels and availability, inherited period times and fixed events; preserves approved history; and reports unplaced requirement blocks. Edits revalidate the complete resulting grid and current configuration under the timetable transaction lock. The browser provides By Class and By Teacher views, Amend 4-up, generation, audited XLSX reports and a browser print view. IT approval requires a complete draft, publication exposes the current approved version to attendance, and Executive access is limited to approved timetables. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md), [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md) and [TIMETABLE_REPORT_EXPORTS.md](TIMETABLE_REPORT_EXPORTS.md).

Scheduling-rule resolution uses stable class/cluster IDs, inclusive effective dates, validated definitions and versioned edits. Every planned class must resolve to exactly one applicable rule. Class and cluster rule scopes cannot overlap, and PostgreSQL guards plus service validation prevent membership changes from creating conflicting scopes. Legacy text-only rules remain unresolved until IT explicitly binds or archives them. Generation and manual placement call this resolver and reject missing or ambiguous rules. See [SCHEDULING_RULES.md](SCHEDULING_RULES.md).

Amend 4-up is the practical operational tool for finishing a generated timetable. It shows multiple mini-grids on one page and lets an operator inspect and correct the timetable in the same visual arrangement used by the printed reports.

The production Amend 4-up workspace provides:

- By Class / By Teacher toggle.
- Configurable 2, 4, 6, 8, 12, 16, 24 or 32 tables per page.
- Previous/Next paging.
- Search by instructional class, teacher code or full teacher name.
- Five day rows and five period columns.
- Click-to-add/edit and validated drag-and-drop movement or swaps.
- Remove and lock/unlock controls.
- Double-click title rename with controlled cascade.
- Save amendments directly to the draft timetable.
- Audit event for every material change.

The shared validator keeps lunch non-schedulable, blocks teacher and class double-booking, and applies edits to stable weekday/period identifiers regardless of visual sorting. Right-click legacy interactions and exact `.pri` parity remain follow-up work.

## 4. Integration with the dashboard system

The timetable becomes a module in the same authenticated application:

| Actor | Timetable access |
|---|---|
| Superuser | Bootstrap/recovery only; no daily timetable editing |
| IT Administrator | Reference data, rules, import support and audit |
| Operator | Create drafts, generate, amend, save and export |
| Executive | View approved timetable and download reports |

The 2023 intake workbook's source class labels now map through the IT-managed crosswalk to active instructional classes. Student records remain separate from instructional class schedules: a timetable class is a teaching group, while attendance and intake contain individual students and class/status history. Student profiles still store the class name, so explicit student-to-instructional-class reconciliation and historical attendance reconciliation remain follow-up work. Category, institution and academic-year catalog integration is described in [STUDENT_REFERENCE_CATALOGS.md](STUDENT_REFERENCE_CATALOGS.md).

## 5. Prototype acceptance walkthrough

The HTML prototype should expose a Timetable/Schedule module with this walkthrough:

1. Open a draft schedule.
2. Choose By Class or By Teacher.
3. Search for a class or teacher.
4. Change tables per page.
5. Move between pages.
6. Double-click a lesson to edit it.
7. Click an empty teaching cell to add a lesson after resource and conflict validation.
8. Drag a lesson to an empty slot or swap it with another valid lesson.
9. Try a teacher clash and see the move rejected.
10. Lock a slot and try to amend it.
11. Save the amendment and return to the schedule.
12. Download both report examples.

The prototype remains synthetic and in-memory. It demonstrates the workflow and information architecture; it does not implement the production scheduler, authentication, database or PDF renderer.

## 6. Migration and production priorities

1. Import a representative `.pri` project into staging.
2. Reconcile teachers, subjects, instructional classes, lesson counts and placed slots.
3. Compare the By Instructional Class and By Teacher outputs with the latest PDFs.
4. Implement Amend 4-up and test every edit path.
5. Publish an approved timetable version.
6. Configure the separate IT-managed mapping between each student profile class and its instructional timetable class.
7. Let Operators load classes scheduled for the attendance date, create a session from the selected published week and retain timetable-version provenance; continue to allow manual sessions where no published schedule applies.
8. Retain the legacy application as a read-only fallback during stabilisation.

## 7. Known legacy risks to remove

- Hard-coded school rules such as EA and ASMB/CT placement.
- Composite teacher conflict exceptions that bypass normal clash checks.
- No rooms or resource constraints.
- Greedy generation without backtracking.
- Hard-coded paths and required sidecar files.
- Embedded `.pri` encryption key.
- Silent failure for malformed project files.
- PDF generation that must not mutate shared timetable data.
## Legacy .pri import increment

IT Administrators and Superusers can map source teacher, subject and class rows to existing application resources in **Legacy timetable preflight**, then import the reconciled archive as a weekly draft. The import is atomic: it creates absent lesson requirements, reuses only exact active matches, packs single-period source placements into the source block lengths, and validates the resulting draft against current rules, availability, configured period times, fixed events and clash checks. It stores a source fingerprint and draft provenance, writes a redacted audit event and rejects a repeat import of the same archive for the same academic week. It never approves or publishes the draft.

The file and mappings are bounded and processed in memory; the original archive is not retained. The import fails closed on conflicting mappings/requirements, unavailable resources, lunch placements, pending or unplaced records, whole-school `ALL` entries and ambiguous 25-flag availability. Composite references require an existing group with the exact mapped source members. A synthetic API test verifies the transactional path; representative archive import and slot-by-slot staging reconciliation are still required before migration sign-off.
