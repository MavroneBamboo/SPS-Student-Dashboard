# First-run setup

## Initial sign-in

The bootstrap identity is controlled by BOOTSTRAP_USERNAME and BOOTSTRAP_PASSWORD. It is seeded as a Superuser with mandatory password rotation. The account can use only authentication and setup operations until initial setup is complete.

1. Sign in with the bootstrap identity.
2. Change the temporary password when prompted.
3. Create a named IT Administrator with a temporary password. Deliver that password through the organisation's approved secure channel.
4. Confirm setup completion. The account creation, completed setup state and audit events are committed in one transaction.
5. The IT Administrator must change their temporary password at first sign-in. The bootstrap account remains a full-access Superuser and should be retained for emergency administration.

Until step 4 succeeds, protected business APIs reject requests even if a caller bypasses the browser. The API permits password change, identity lookup, setup status and setup completion during this state.

## Migration behavior

The setup migration creates one durable setup-state row. A database that already has an active Superuser whose mandatory password change is cleared and an active IT Administrator is marked complete, preserving normal use. Other installations remain gated and must finish setup. Existing user, attendance, student and timetable data is not rewritten.

The setup-state row is a singleton and the completion endpoint serializes concurrent attempts. Duplicate usernames, a non-bootstrap actor, an unchanged bootstrap credential, an existing active IT Administrator, or a repeated completion request are rejected without partial account or audit writes.

## Audit

Successful completion writes setup.initial_it_administrator.created and setup.completed events. The events identify the acting bootstrap Superuser and the new administrator, and do not contain the temporary password. Failed and duplicate attempts do not mark setup complete.

## Recovery

If bootstrap access is lost, follow the authorised server-side recovery procedure. Do not modify setup state or user passwords directly in SQL.
