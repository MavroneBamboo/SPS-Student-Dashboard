# Timetable report exports

`GET /api/v1/timetable/versions/{id}/reports.xlsx?kind=both` generates a workbook from the saved timetable version. `kind` accepts `class`, `teacher`, or `both` and defaults to `both`.

The saved timetable workspace exposes this through **Download class and teacher reports**; the button uses the active authenticated session and downloads the server response.

The workbook has a `Version` metadata sheet plus the requested report sheets. `By InstClass` contains each selected instructional class's weekday/period grid, including configured period times and the non-schedulable Lunch / Muster interval. `By Teacher` shows each teacher's saved schedule, class and subject assignments, available free periods, unavailable periods, and lunch. Both views use the version's stored snapshot and placement cells, so later edits to live teacher/class profiles do not rewrite historical report labels or times. The metadata sheet records version identity, revision, status, export timestamp, actor ID and audit-event ID.

Operators and IT Administrators may export drafts and approved versions. Executives can export approved versions only; unavailable or draft versions return 404. Exports do not change the timetable revision or placements. Each successful download adds a `timetable.report.exported` audit event with actor, version, report kind, format, revision and approval state. Responses are sent with `Cache-Control: no-store`.

This is a server-generated Excel report, not the final legacy PDF renderer. Visual comparison against the supplied `Timetable By InstClass.pdf` and `Timetable By Teacher.pdf`, PDF parity and a publish pointer that coordinates the version consumed by attendance remain future phase-D work.

## Verification coverage

The export API tests open the generated workbook, verify both report sheets, lunch and free-period rows, report content, role restrictions, audit metadata and unchanged timetable revision/placements. The existing PostgreSQL CI workflow exercises this route with the rest of the API and migration suite.
