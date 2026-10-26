# Operational role boundaries

This increment applies the product's least-privilege separation to the existing student, attendance and report APIs. The server checks these roles for every route; browser navigation is only a usability aid.

| API area | Superuser | IT Administrator | Operator | Executive |
| --- | --- | --- | --- | --- |
| Student profiles and status history | Denied | Denied | Read/write | Denied |
| Attendance sessions and records | Denied | Denied | Read/write | Denied |
| Live dashboard and attendance CSV | Denied | Denied | Read | Read |
| Security/operation audit | Read | Read | Denied | Denied |
| Named account administration | Full | Non-Superuser only | Denied | Denied |

The Superuser is reserved for bootstrap/recovery and user administration. IT Administrators handle support, named accounts and scheduling reference configuration. An IT user needing daily data operations must use a separately assigned Operator account. Executives use aggregated dashboards and approved reporting; they do not receive raw session or student-profile API access. The current attendance CSV contains identifying data and is limited to Operator and Executive; report export logging/redaction policy remains a release decision.

Tests use named Operator identities for student and attendance work, separate administrator identities for audit and account changes, and a full role-by-endpoint matrix. Timetable resource, lesson, draft and approval role rules remain as documented in the timetable guides. Further permission hardening, setup/recovery, reporting policy and deployment security are still required.
