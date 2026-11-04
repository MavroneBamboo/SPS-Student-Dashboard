# Timetable Integration Notes

Attendance boundary (26 October 2026): the browser supports daily attendance sessions/records but does not create them from unpublished timetable drafts. Published timetable-to-attendance mapping, instructional/student class reconciliation and historical roster policies remain required. See [ATTENDANCE_WORKSPACE.md](ATTENDANCE_WORKSPACE.md).

Profile boundary (26 October 2026): the production browser now supports core student profile processing and status history. Student class names still need an explicit mapping to instructional timetable class IDs during reconciliation; this increment does not infer that mapping or create timetable memberships. See [STUDENT_PROFILES.md](STUDENT_PROFILES.md).

UI redesign (27 October 2026): the actual `/ui/` timetable workspace now follows the supplied “SPS Timetable — UI UX Redesign” reference: navy timetable sidebar, By class / By teacher weekly boards, selected class/teacher controls, report export/print view, teacher/class/subject resource tabs, and a separate periods/rules screen. Clickable Amend 4-up remains available as a board mode with 4/8/12/16 class paging. Period display is P1, P2, P3 Lunch/Muster, P4 and P5 while stable API slot codes remain unchanged. Default periods can be edited; class/cluster overrides replace the matching default for future drafts. Superuser, IT and Operator access follows the backend role matrix. PDF export opens a browser print view; native server-generated PDF formatting, drag/swap editing, publishing coordination and fixed events remain follow-up work. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md) and [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md).

Generation increment (26 October 2026): the backend supports deterministic weekly generation with bounded iterative repair, shared manual validations, per-block unplaced explanations and persisted revision-linked reports. Fill-pending preserves existing blocks; explicit replace-unlocked retains all locked blocks. See [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md). Browser Amend 4-up, fixed events, composite teacher mapping, legacy reconciliation, publishing and PDF rendering remain outstanding; earlier increment descriptions below record their delivery sequence.

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

The legacy project is a `.pri` ZIP containing six AES-encrypted JSON members (`R01.bin`–`R06.bin`). The new read-only validator checks this fixed member set, enforces archive size limits, decrypts in memory, and reconciles resource references and placements without modifying the source. Inspection of the current sample and legacy code confirms 25 availability entries and five numeric placement periods. The new schedule has four teaching periods and reserves displayed Period 3 for lunch, so migration must explicitly map or reject legacy slots; no automatic slot conversion is safe. Composite teacher references and the legacy `ALL` whole-school event also require explicit reconciliation. The legacy encryption key is embedded in the old application source and must be supplied to the validator through `LEGACY_PRI_KEY_HEX`; links use names rather than stable IDs, and item IDs are list positions. AES-CBC has no authentication tag, so decryption is not an integrity check. No database import is performed yet; staging import requires explicit mapping/reconciliation and review.

Run the validator from the repository root after setting `LEGACY_PRI_KEY_HEX` to the hex-encoded legacy key in the current PowerShell process:

```powershell
$env:LEGACY_PRI_KEY_HEX = '<hex-encoded key from TImeTables-legacy source>'
python scripts/validate_legacy_pri.py 'D:\path\to\project.pri'
Remove-Item Env:LEGACY_PRI_KEY_HEX
```

It prints aggregate counts and issue codes by default. Add `--details` for row-indexed issue locations. Exit code `1` means reconciliation found issues or import blockers; `2` means the archive could not be read safely.

## 2.1 Resource setup is a prerequisite

The scheduler cannot add a teacher implicitly. The operator or administrator must first maintain the resource profiles used by lesson requirements:

1. **Teachers** — short code, full name, adjunct flag and availability by day/period.
2. **Subjects** — name, short code and description.
3. **Instructional Classes** — name, short name and description/reporting order.
4. **Lessons** — subject, teacher, instructional class, periods per week (`Count`) and block length (`Length`).

Class setup also includes cluster membership and period configuration. Every class starts with the default period pattern (`P1`, `P2`, `Lunch`, `P3`, `P4`). A period created for a single class or cluster may override the matching default without changing unrelated classes. Period 3 remains the lunch interval and cannot be converted into a teaching period.

### Initial production API increment

The application now defines the initial timetable resource schema and authenticated API routes under `/api/v1/timetable`: `teachers`, `subjects`, `classes`, `clusters`, cluster membership, `periods`, and resolved periods at `classes/{id}/periods`. The migration seeds the default five-column pattern and the documented times. Period definitions are unique by scope, target and slot. Class-specific period values override a matching cluster value, which overrides the default; a class is restricted to one cluster to avoid ambiguous inheritance. Writes are IT Administrator-only and audited. The first increment is backend-only: it does not yet include resource edit/deactivation UI, lesson requirements, scheduler rules, timetable generation, or Amend 4-up persistence.

The following lesson increment adds `/api/v1/timetable/lessons` for Operators and IT Administrators: create/list/retrieve, version-checked replacement, archive and restore. Requirements use resource IDs rather than names and reject duplicate academic-year/class/teacher/subject combinations. Weekly count remains the total; block length splits it into full consecutive blocks plus a shorter remainder (3 periods with length 2 means a double plus a single). Active-resource, availability and inherited-period checks run centrally, with lunch and time gaps breaking blocks. Configuration changes cannot invalidate active requirements, including when concurrent with requirement writes on PostgreSQL. These are requirement-level checks; rule completeness, whole-schedule clashes, generation and Amend 4-up remain later work.

Scheduling rules are a required prerequisite for every planning run. Each class must resolve to one and only one applicable rule set. Missing, duplicated or overlapping class/cluster rules must prevent generation and manual placement; duplicate timetable placements are also rejected.

The lesson editor should use controlled selectors populated from these profiles. It must reject a lesson that references a missing teacher, subject or instructional class. Teacher availability must be visible and editable before generation, and the scheduler plus Amend 4-up must use the same availability rules.

The legacy source serialises availability as a colon-separated array of 20 teaching slots. The visual report has a lunch column for daily alignment, but lunch must remain non-schedulable. The replacement system must use a versioned day/period availability model rather than an opaque positional string.

The clickable prototype now exposes this prerequisite through **Resource setup** before the Amend 4-up grid. It demonstrates teacher profile creation/editing, availability selection, subject and instructional-class references, class clusters, default periods, class/cluster period overrides, lesson requirements, duplicate short-code validation, teacher-code cascade and availability checks during timetable amendments.

## 3. Why Amend 4-up is the key capability

The production backend persists weekly drafts and the operations required by this workspace: add/amend/move, atomic swap, remove and block lock/unlock. It snapshots rules, resource labels/availability and inherited period times, preserves approved history, and reports pending requirement blocks. Edits revalidate the complete resulting grid and current rules under the timetable transaction lock. Approval is IT Administrator-only and requires completeness; Executive reads are approved-only. Generation uses these services and saves revision-linked planning reports. The first production browser increment now supports class-grid operations and generation; teacher grid modes and report rendering still need implementation. See [TIMETABLE_DRAFTS.md](TIMETABLE_DRAFTS.md) and [TIMETABLE_GENERATION.md](TIMETABLE_GENERATION.md).

Scheduling-rule resolution now has its own implementation slice: stable class/cluster IDs, inclusive effective dates, validated rule definitions and versioned edits. The resolver must find exactly one applicable rule for every planned class; a class rule and its cluster rule may not overlap. PostgreSQL guards and service validation also prevent membership changes from introducing conflicting scopes. Existing text-only rules remain unresolved until IT explicitly binds or archives them. See [SCHEDULING_RULES.md](SCHEDULING_RULES.md). This supplies the prerequisite service for future generation and manual placement; those workflows still require implementation.

Amend 4-up is the practical operational tool for finishing a generated timetable. It shows multiple mini-grids on one page and lets an operator inspect and correct the timetable in the same visual arrangement used by the printed reports.

The integrated system should make this the primary timetable workspace, with:

- By Class / By Teacher toggle.
- Configurable 2, 4, 6, 8, 12, 16, 24 or 32 tables per page.
- Previous/Next paging.
- Search by instructional class, teacher code or full teacher name.
- Five day rows and five period columns.
- Double-click cell editing.
- Drag-and-drop movement and validated swaps.
- Right-click shift/remove.
- Lock/unlock.
- Double-click title rename with controlled cascade.
- Save amendments directly to the draft timetable.
- Audit event for every material change.

The new implementation must retain the legacy fixes: the lunch column must render but reject moves, teacher double-booking must be blocked, Amend changes must sync back to Schedule, and editing after Day sorting must operate on the displayed weekday rather than a stale row index.

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
