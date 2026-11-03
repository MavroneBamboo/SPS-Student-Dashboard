# Timetable report exports

`GET /api/v1/timetable/versions/{id}/reports.xlsx?kind=both` generates a workbook from the saved timetable version. `kind` accepts `class`, `teacher`, or `both` and defaults to `both`.

The saved timetable workspace exposes this through **Download class and teacher reports**; the button uses the active authenticated session and downloads the server response.

The workbook has a `Version` metadata sheet plus the requested report sheets. `By InstClass` contains each selected instructional class's weekday/period grid, including configured period times and the non-schedulable Lunch / Muster interval. `By Teacher` shows each teacher's saved schedule, class and subject assignments, available free periods, unavailable periods, and lunch. Both views use the version's stored snapshot and placement cells, so later edits to live teacher/class profiles do not rewrite historical report labels or times. The metadata sheet records version identity, revision, status, export timestamp, actor ID and audit-event ID.

Operators and IT Administrators may export drafts and approved versions. Executives can export approved versions only; unavailable or draft versions return 404. Exports do not change the timetable revision or placements. Each successful download adds a `timetable.report.exported` audit event with actor, version, report kind, format, revision and approval state. Responses are sent with `Cache-Control: no-store`.

The browser also provides **Print class report**, **Print teacher report**, and **Print class and teacher reports**. These open a print-ready report from the saved timetable snapshot; users can print it or save it as PDF in the browser. The landscape A4 layout follows the legacy report structure: one class or teacher per page, weekdays as rows, periods as columns, configured period times, a non-editable Lunch / Muster column at displayed Period 3, SPS crest, and generated timestamp. The timetable's stable stored slot codes remain unchanged. Browser PDF is not a server-generated PDF artifact and requires the browser print dialog.

The browser acceptance test checks one-page A4 landscape output, weekday/period grid orientation, configured times, lunch, a placed synthetic lesson and the packaged crest. This verifies the implemented layout contract; exact pixel-for-pixel parity with the supplied `Timetable By InstClass.pdf` and `Timetable By Teacher.pdf` has not been established. The existing XLSX API remains available for audited, server-generated workbooks. Attendance consumes currently published schedules through the separate mapping and provenance flow documented in [TIMETABLE_PUBLICATION.md](TIMETABLE_PUBLICATION.md).

## Verification coverage

The export API tests open the generated workbook, verify both report sheets, lunch and free-period rows, report content, role restrictions, audit metadata and unchanged timetable revision/placements. The browser acceptance test verifies the print view and generated PDF page dimensions. The CI workflow exercises both alongside the API, migration and browser suites.
