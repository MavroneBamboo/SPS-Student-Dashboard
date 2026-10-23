# Clickable HTML Prototype

Open [`index.html`](index.html) in a browser. No server, package installation or database is required.

The prototype simulates:

- Superuser, IT Administrator, Operator and Executive sign-in roles.
- Role-based navigation and read-only Executive access.
- Dashboard filters and attendance indicators.
- Student profile search, creation and duplicate `Pris No.` validation.
- Attendance updates and report generation actions.
- User administration and system-health views.
- Timetable/Schedule navigation with By Class/By Teacher Amend 4-up editing, paging, density, drag/swap, lock, shift, remove and save-draft actions.

All data is in-memory demo data. Refreshing the page resets changes; no real authentication, JWT, database or report file is connected.

The timetable walkthrough is available from the left navigation or directly at [`timetable.html`](timetable.html). It uses synthetic class, teacher and lesson data based on the legacy timetable workflow and the latest By Instructional Class/By Teacher report layouts. It displays `P1`, `P2`, `Lunch`, `P3`, `P4`; Period 3 is lunch and is non-schedulable.
