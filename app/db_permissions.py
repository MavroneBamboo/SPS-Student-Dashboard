"""Provision the least-privilege database role used by the API process."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def _psycopg_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("Database role provisioning requires PostgreSQL")
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def _scram_verifier(password: str) -> str:
    """Build a PostgreSQL SCRAM-SHA-256 verifier without sending the raw password."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", password):
        raise RuntimeError("DATABASE_RUNTIME_PASSWORD must use URL-safe characters (letters, digits, '_' or '-')")
    iterations = 4096
    salt = secrets.token_bytes(16)
    salted_password = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, iterations)
    client_key = hmac.digest(salted_password, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted_password, b"Server Key", "sha256")
    encode = lambda value: base64.b64encode(value).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{encode(salt)}${encode(stored_key)}:{encode(server_key)}"


def _provision() -> None:
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    password = os.environ.get("DATABASE_RUNTIME_PASSWORD")
    role_name = os.environ.get("DATABASE_RUNTIME_ROLE", "sps_runtime")
    if not admin_url or not password:
        raise RuntimeError("DATABASE_ADMIN_URL and DATABASE_RUNTIME_PASSWORD are required")

    admin = make_url(admin_url)
    owner_name = admin.username
    database_name = admin.database
    if not owner_name or not database_name:
        raise RuntimeError("DATABASE_ADMIN_URL must include a database and migration-owner username")
    if role_name == owner_name:
        raise RuntimeError("The API runtime role must be separate from the migration role")

    with psycopg.connect(_psycopg_url(admin_url)) as connection:
        connection.execute("SET password_encryption = 'scram-sha-256'")
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)).fetchone()
        if exists:
            memberships = connection.execute(
                """
                SELECT granted.rolname
                FROM pg_auth_members AS membership
                JOIN pg_roles AS granted ON granted.oid = membership.roleid
                JOIN pg_roles AS member ON member.oid = membership.member
                WHERE member.rolname = %s
                """,
                (role_name,),
            ).fetchall()
            if memberships:
                names = ", ".join(name for (name,) in memberships)
                raise RuntimeError(f"Runtime role {role_name!r} inherits role memberships: {names}")

            connection.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 100 VALID UNTIL 'infinity'"
                ).format(sql.Identifier(role_name), sql.Literal(_scram_verifier(password)))
            )
        else:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 100 VALID UNTIL 'infinity'"
                ).format(sql.Identifier(role_name), sql.Literal(_scram_verifier(password)))
            )

        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database_name), sql.Identifier(role_name)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role_name)))
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(role_name))
        )
        connection.execute(sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(role_name)))
        connection.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(
                sql.Identifier(owner_name), sql.Identifier(role_name)
            )
        )
        connection.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}").format(
                sql.Identifier(owner_name), sql.Identifier(role_name)
            )
        )
        connection.commit()

        role = connection.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls
            FROM pg_roles WHERE rolname = %s
            """,
            (role_name,),
        ).fetchone()
        if role != (False, False, False, False, False, False):
            raise RuntimeError(f"Runtime role {role_name!r} has unexpected privileged attributes: {role!r}")
        if connection.execute("SELECT has_schema_privilege(%s, 'public', 'CREATE')", (role_name,)).fetchone()[0]:
            raise RuntimeError(f"Runtime role {role_name!r} can create objects in the public schema")
        owns_objects = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_database
                WHERE datname = %s AND datdba = (SELECT oid FROM pg_roles WHERE rolname = %s)
            ) OR EXISTS (
                SELECT 1 FROM pg_namespace
                WHERE nspname = 'public' AND nspowner = (SELECT oid FROM pg_roles WHERE rolname = %s)
            ) OR EXISTS (
                SELECT 1 FROM pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relowner = (SELECT oid FROM pg_roles WHERE rolname = %s)
            )
            """,
            (database_name, role_name, role_name, role_name),
        ).fetchone()[0]
        if owns_objects:
            raise RuntimeError(f"Runtime role {role_name!r} must not own the database, schema or application objects")

    print(f"Provisioned least-privilege database role {role_name!r} for the API.")


if __name__ == "__main__":
    try:
        _provision()
    except Exception as error:
        print(f"Database role provisioning failed: {error}", file=sys.stderr)
        raise
