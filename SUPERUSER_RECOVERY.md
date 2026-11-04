# Superuser account recovery

Use this procedure only when the target Superuser has lost access and no other active Superuser is available to perform a normal password reset. It requires authorised Docker-host administration and an incident or service-ticket reference. There is no public recovery endpoint.

## Recovery command

Run from the deployed Compose directory:

```sh
docker compose exec -it app python -m app.recover_superuser \
  --username bootstrap-admin \
  --performed-by it.operator \
  --reason "INC-2048: verified loss of Superuser credentials"
```

The command requires an interactive terminal, an explicit `RECOVER` confirmation, and a new password entered twice through hidden prompts. Do not pass the password in command arguments or environment variables. Use the organisation's approved method to provide the temporary password to the account holder.

## Safety and audit behavior

- The target must be an existing Superuser account. The command will not create an account or change another role.
- Recovery is refused if any other active Superuser exists; that Superuser should use normal account administration instead.
- The command activates the target account, replaces its password hash, requires password change at next sign-in, and increments the token version to revoke existing access tokens.
- Account changes and the audit event commit in one database transaction. The event records the target account ID, the stated IT operator identity and the incident reason. It does not record the password. The system actor ID is `0` because recovery occurs outside an authenticated application session.
- The command uses the API's restricted runtime database account. It does not expose a recovery API route or accept secrets through arguments.

## After recovery

1. Have the account holder sign in with the temporary password and choose a new private password immediately.
2. Confirm the recovery audit event appears in the Superuser/IT audit view as `security.superuser.recovered`.
3. Close the incident only after the account holder confirms access and the temporary password has been replaced.

If the target account does not exist, another Superuser is active, or the database is unavailable, the command refuses the operation. Resolve identity/database integrity through the separately approved host and database recovery procedures; do not bypass the checks with direct SQL.
