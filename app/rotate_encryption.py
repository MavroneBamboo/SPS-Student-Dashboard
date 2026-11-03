"""CLI: python -m app.rotate_encryption [--apply]"""

import argparse
import json
import sys

from app.db import SessionLocal
from app.encryption_rotation import rotate_encrypted_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and rotate application-encrypted database values")
    parser.add_argument("--apply", action="store_true", help="commit the re-encryption; default is a read-only dry run")
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            result = rotate_encrypted_data(db, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
    except Exception as exc:
        print(f"Encryption verification failed ({type(exc).__name__}); no changes were committed.", file=sys.stderr)
        return 1

    result["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
