# Identity and account administration increment

The subsequent operational role slice enforces the student, attendance, dashboard and audit boundaries in [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md). The remaining release controls listed below still apply.

This document records the identity increments through Alembic `20261103_0018`. Migration `20261026_0008` preserves users, sets `token_version = 0`, and adds a unique index on lowercase usernames; it stops with a reconciliation error if existing usernames differ only by case. Migration `20261103_0018` adds an initially empty `auth_sessions` table. Since older access tokens were not recorded as sessions, users must sign in again after this migration. No account is silently renamed or deleted.

## Current API contract

- `POST /api/v1/auth/login` accepts usernames without case distinction, records the generated session ID, token version and expiry, then returns a short-lived JWT. The server verifies account activity, token version and session revocation on every authenticated request.
- `GET /api/v1/auth/sessions` lists the current user's active sessions with sign-in/expiry times and marks the current browser. `DELETE /api/v1/auth/sessions/{session_id}` revokes one owned session; other users' session IDs return 404.
- `POST /api/v1/auth/change-password` rotates the hash, clears mandatory rotation, increments token version and returns a fresh token. All earlier tokens for that account become invalid.
- `POST /api/v1/auth/logout` returns 204 and revokes only the presented session. The browser clears its in-memory token immediately, then attempts server revocation. If the network fails, the session remains valid until explicitly revoked or its short expiry.
- `GET/POST /api/v1/users` and `PATCH /api/v1/users/{id}` allow Superusers and IT Administrators. IT Administrators cannot list, create, promote to, edit or reset a Superuser. Self-deactivation is rejected, and at least one active account of each administrator role is preserved. Role/active changes revoke all target-account tokens.
- `POST /api/v1/users/{id}/reset-password` takes a new temporary password, returns 204, forces rotation at the next login and revokes all target-account tokens. It rejects self reset. Passwords and token values are excluded from audit details.

Password, role and active-status changes increment `token_version`; these account-wide changes invalidate every prior session. Explicit logout and the session manager revoke one session without invalidating the user's other browsers. Expired session rows are pruned during successful logins. Security mutations take one PostgreSQL transaction advisory lock and re-read the actor after acquiring it. This serializes account changes and the last-administrator check, while authenticated reads use the live database row. The browser exposes named-account management to IT Administrators and password reset to both permitted roles. Temporary passwords must be delivered through the deployment's approved secure channel.

## Still required before production acceptance

The reverse proxy now limits `POST /api/v1/auth/login` to 30 requests per minute per client IP, with a burst of 10 and HTTP 429 responses after the burst. CI exercises this behavior through Nginx and a mock API upstream. Persistent sign-in audit, account-level lockout, distributed abuse controls, setup completion and Superuser recovery, TLS/secret handling, and tested backup/restore remain release work. The proxy limit does not replace those controls.

The API process now uses a separate `sps_runtime` PostgreSQL role with table read/write and sequence privileges only; the migration role is confined to the one-shot Compose migration service. CI checks that the runtime identity cannot create database objects or administer roles/databases and that its password is stored as a SCRAM verifier.

Setup completion and Superuser recovery, persistent sign-in audit and account-level failed-login controls, TLS/secret handling, and tested backup/restore remain release work. These increments do not claim those controls are complete.
