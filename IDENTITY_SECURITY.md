# Identity and account administration increment

The subsequent operational role slice enforces the student, attendance, dashboard and audit boundaries in [ROLE_BOUNDARIES.md](ROLE_BOUNDARIES.md). The remaining release controls listed below still apply.

This increment follows the attendance browser branch and requires Alembic `20261026_0008` before the new application code starts. The migration preserves users, sets `token_version = 0`, and adds a unique index on lowercase usernames. It stops with a reconciliation error if existing usernames differ only by case. No account is silently renamed or deleted. Tokens issued by the earlier implementation lack the new required version claim and require a fresh login after deployment.

## Current API contract

- `POST /api/v1/auth/login` accepts usernames without case distinction and returns a short-lived JWT. The server verifies account activity and token version on every authenticated request.
- `POST /api/v1/auth/change-password` rotates the hash, clears mandatory rotation, increments token version and returns a fresh token. All earlier tokens for that account become invalid.
- `POST /api/v1/auth/logout` returns 204 and increments token version, revoking all tokens for the account. This is account-wide logout; there is no per-device session table yet. Browser sign-out clears its in-memory token immediately, then attempts server revocation. If the network fails, it reports that revocation was not confirmed and the token expires normally.
- Login successes and failures are persisted as audit events before the response is returned. Known-account failures are associated with that user ID; unknown usernames use an anonymous actor and generic entity identifier. Events contain only the outcome and never store the submitted username or password. Unknown usernames follow the same password-hash verification path as known accounts.
- `GET/POST /api/v1/users` and `PATCH /api/v1/users/{id}` allow Superusers and IT Administrators. IT Administrators cannot list, create, promote to, edit or reset a Superuser. Self-deactivation is rejected, and at least one active account of each administrator role is preserved. Role/active changes revoke all target-account tokens.
- `POST /api/v1/users/{id}/reset-password` takes a new temporary password, returns 204, forces rotation at the next login and revokes all target-account tokens. It rejects self reset. Passwords and token values are excluded from audit details.

Security mutations take one PostgreSQL transaction advisory lock and re-read the actor after acquiring it. This serializes account changes and the last-administrator check, while authenticated reads use the live database row. The browser exposes named-account management to IT Administrators and password reset to both permitted roles. Temporary passwords must be delivered through the deployment's approved secure channel.

## Still required before production acceptance

The reverse proxy limits `POST /api/v1/auth/login` to 30 requests per minute per client IP, with a burst of 10 and HTTP 429 responses after the burst. CI exercises this behavior through Nginx and a mock API upstream. Account-level lockout, distributed abuse controls, setup completion and Superuser recovery, TLS/secret handling, session/device-level revocation, and tested backup/restore remain release work. The proxy limit does not replace those controls.

The API process now uses a separate `sps_runtime` PostgreSQL role with table read/write and sequence privileges only; the migration role is confined to the one-shot Compose migration service. CI checks that the runtime identity cannot create database objects or administer roles/databases and that its password is stored as a SCRAM verifier.

Setup completion and Superuser recovery, account-level failed-login controls, TLS/secret handling, session/device-level revocation, and tested backup/restore remain release work. These increments do not claim those controls are complete.
