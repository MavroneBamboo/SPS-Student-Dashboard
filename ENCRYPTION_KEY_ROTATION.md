# Application encryption key rotation

Sensitive student profiles, attendance roster names and staged intake workbooks are encrypted by the application. New ciphertext includes a non-secret key identifier. Existing untagged Fernet values remain readable during migration.

## Configuration

- `APP_ENCRYPTION_KEY` is the active Fernet key. New values are always encrypted with this key.
- `APP_ENCRYPTION_PREVIOUS_KEYS` is an optional comma-separated list of prior Fernet keys, newest first. The application uses these only to decrypt legacy values during a rotation window.
- Keep all key material in the deployment secret store or protected environment file. Never put keys in source control, logs, chat or database records.

Generate a Fernet-compatible key in a trusted environment with:

```sh
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

## Rotation runbook (Docker Compose)

1. Verify a recent encrypted database backup and confirm the current and new keys are recoverable by authorized operators.
2. Schedule a maintenance window. Stop application writes so no old-key ciphertext can be created during the rotation:

   ```sh
   docker compose stop app
   ```

3. In the protected `.env`, set `APP_ENCRYPTION_KEY` to the new key and set `APP_ENCRYPTION_PREVIOUS_KEYS` to the prior active key plus any older keys needed to decrypt existing rows. Do not print or share these values.
4. Run the verifier in dry-run mode. It checks every encrypted student field, attendance roster name and both encrypted workbook payloads without changing rows:

   ```sh
   docker compose run --rm --no-deps app python -m app.rotate_encryption
   ```

   Review the JSON counts. If verification fails, keep the application stopped, restore the correct key configuration and investigate using the error result; the command does not print ciphertext or plaintext.
5. Apply the rotation in one database transaction:

   ```sh
   docker compose run --rm --no-deps app python -m app.rotate_encryption --apply
   ```

   The command uses the least-privilege runtime database account. Any unreadable value aborts the transaction. The default invocation is read-only.
6. Run the dry-run command again. Require `values_to_rotate` to be zero and `encrypted_values_verified` to match the apply run. Start the application and verify health and a profile read through the API.
7. Keep retired keys available while any retained database backup can contain ciphertext encrypted by them. Remove an old key from `APP_ENCRYPTION_PREVIOUS_KEYS` only after all live records and retained restore points no longer depend on it. Then restart the application.

The rotation holds row locks and one transaction for all affected records. Plan sufficient maintenance time for the data volume and storage capacity. Never run the apply command against production before a verified backup and a tested recovery path are available.

## Compatibility and storage coverage

The key identifier is embedded in the encrypted value, so no schema migration is required. The rotation process verifies and handles:

- every `students.*_encrypted` profile field;
- `attendance_roster_entries.student_name_encrypted`;
- `student_import_batches.source_ciphertext` and `rows_ciphertext`.

New writes use only the active key. During the rotation window, reads accept the active key, configured previous keys, and pre-versioned Fernet ciphertext. Unknown key IDs, malformed values and authentication failures fail closed with a generic error.
