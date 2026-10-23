# Timetable Integration Notes

## 1. Source system reviewed

The legacy source is `D:\RPA\TImeTables-legacy`, a .NET 9 Windows Forms application called **Prison School Timetables**. It schedules instructional class groups, teachers, subjects and weekly lesson requirements, then generates two reports:

- `Timetable By InstClass.pdf`
- `Timetable By Teacher.pdf`

The latest supplied PDFs at `C:\Users\Prisuser\Downloads\` are treated as the current visual and content references for the replacement report renderer.

The source documentation and changelog identify the latest operational behavior as five weekdays by five teaching periods. The 12:00–13:25 slot is Period 3; Period 5 is 15:10–16:55.

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

The legacy project is a `.pri` ZIP containing six encrypted data members. It is suitable as a migration source but not as the new system of record: the encryption key is embedded in source, links use names rather than stable IDs, and item IDs are list positions.

## 3. Why Amend 4-up is the key capability

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

The new implementation must retain the legacy fixes: Period 5 must render and accept moves, teacher double-booking must be blocked, Amend changes must sync back to Schedule, and editing after Day sorting must operate on the displayed weekday rather than a stale row index.

## 4. Integration with the dashboard system

The timetable becomes a module in the same authenticated application:

| Actor | Timetable access |
|---|---|
| Superuser | Bootstrap/recovery only; no daily timetable editing |
| IT Administrator | Reference data, rules, import support and audit |
| Operator | Create drafts, generate, amend, save and export |
| Executive | View approved timetable and download reports |

The timetable class reference must map to the student intake/attendance class reference. Student records remain separate from instructional class schedules. This is important because a timetable class is a teaching group, while attendance and intake may contain individual students and class/status history.

## 5. Prototype acceptance walkthrough

The HTML prototype should expose a Timetable/Schedule module with this walkthrough:

1. Open a draft schedule.
2. Choose By Class or By Teacher.
3. Search for a class or teacher.
4. Change tables per page.
5. Move between pages.
6. Double-click a lesson to edit it.
7. Drag a lesson to an empty slot or swap it with another valid lesson.
8. Try a teacher clash and see the move rejected.
9. Lock a slot and try to amend it.
10. Save the amendment and return to the schedule.
11. Download both report examples.

The prototype remains synthetic and in-memory. It demonstrates the workflow and information architecture; it does not implement the production scheduler, authentication, database or PDF renderer.

## 6. Migration and production priorities

1. Import a representative `.pri` project into staging.
2. Reconcile teachers, subjects, instructional classes, lesson counts and placed slots.
3. Compare the By Instructional Class and By Teacher outputs with the latest PDFs.
4. Implement Amend 4-up and test every edit path.
5. Publish an approved timetable version.
6. Link the approved instructional classes to attendance sessions.
7. Retain the legacy application as a read-only fallback during stabilisation.

## 7. Known legacy risks to remove

- Hard-coded school rules such as EA and ASMB/CT placement.
- Composite teacher conflict exceptions that bypass normal clash checks.
- No rooms or resource constraints.
- Greedy generation without backtracking.
- Hard-coded paths and required sidecar files.
- Embedded `.pri` encryption key.
- Silent failure for malformed project files.
- PDF generation that must not mutate shared timetable data.
