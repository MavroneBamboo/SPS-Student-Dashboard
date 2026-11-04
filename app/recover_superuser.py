import argparse
import getpass
import sys

from app.db import SessionLocal
from app.superuser_recovery import RecoveryRefused, recover_superuser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover a Superuser account through an audited server-side operation.")
    parser.add_argument("--username", required=True, help="Existing Superuser username to recover")
    parser.add_argument("--performed-by", required=True, help="IT Administrator identity responsible for the recovery")
    parser.add_argument("--reason", required=True, help="Incident or support-ticket reference and short reason")
    args = parser.parse_args(argv)

    if not sys.stdin.isatty():
        parser.error(
            "Run this command with an interactive terminal so the recovery password is not passed as an argument or environment value."
        )
    if input(f"Type RECOVER to reset Superuser account '{args.username}': ") != "RECOVER":
        print("Recovery cancelled.", file=sys.stderr)
        return 1

    password = getpass.getpass("New temporary password (12-200 characters): ")
    confirmation = getpass.getpass("Confirm new temporary password: ")
    if password != confirmation:
        print("Recovery refused: the password confirmation did not match.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        try:
            user_id = recover_superuser(db, args.username, args.performed_by, args.reason, password)
        except RecoveryRefused as exc:
            db.rollback()
            print(f"Recovery refused: {exc}", file=sys.stderr)
            return 2
    print(
        f"Recovered Superuser account id {user_id}. It is active, existing tokens are revoked, and password change is required at next sign-in."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
