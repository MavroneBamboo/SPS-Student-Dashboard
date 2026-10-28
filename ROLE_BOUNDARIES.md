# Operational role boundaries

Superuser is the highest-trust application role. It can use every workspace and action, including user and role administration, student profiles and imports, attendance, reports, audit, timetable resources, scheduling rules, lesson requirements, draft editing and timetable approval. The browser opens Superuser on the dashboard and keeps account administration available in navigation. Backend authorization remains authoritative, and mutations continue to create audit events.

| API area | Superuser | IT Administrator | Operator | Executive |
| --- | --- | --- | --- | --- |
| Student profiles, status history and intake imports | Full | Denied | Read/write | Denied |
| Attendance sessions and records | Full | Denied | Read/write | Denied |
| Live dashboard and attendance CSV | Read | Denied | Read | Read |
| Security/operation audit | Read | Read | Denied | Denied |
| Named account administration | Full | Non-Superuser only | Denied | Denied |
| Timetable resources, class mapping, periods and rules | Full | Full | Read | Read |
| Lesson requirements and timetable drafts | Full | Full | Full | Approved read-only |
| Timetable approval | Full | Full | Denied | Denied |

IT Administrators handle support, named accounts and scheduling reference configuration. Operators handle daily profile, intake, attendance and timetable planning work. Executives use aggregated dashboards, reports and approved timetable views; they do not receive raw student-profile or attendance-session API access. The attendance CSV contains identifying data and is limited to Superuser, Operator and Executive; report export logging and redaction policy remain release decisions.

Tests exercise the full role-by-endpoint matrix, including Superuser access through the API and browser. UI visibility is only a usability aid; the API enforces the same access rules on every request. Changes to permissions must update this matrix and its tests in the same pull request.
