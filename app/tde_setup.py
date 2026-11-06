"""Configure PostgreSQL TDE before schema migrations run.

This command is an idempotent, one-shot deployment step. The migration account
must be a PostgreSQL administrator because pg_tde key setup and table rewrites
require elevated privileges.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def _text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _database_url(value: str, database: str | None = None) -> str:
    parsed = make_url(value)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("TDE requires PostgreSQL")
    return parsed.set(drivername="postgresql", database=database or parsed.database).render_as_string(hide_password=False)


def _provider_settings() -> tuple[str, str]:
    provider_name = os.environ.get("TDE_PROVIDER_NAME", "sps-key-provider")
    provider_type = os.environ.get("TDE_PROVIDER", "file").lower()
    app_env = os.environ.get("APP_ENV", "development").lower()
    if not provider_name or provider_type not in {"file", "vault"}:
        raise RuntimeError("TDE_PROVIDER_NAME must be set and TDE_PROVIDER must be 'file' or 'vault'")
    if app_env == "production" and provider_type != "vault":
        raise RuntimeError("Production requires TDE_PROVIDER=vault; local key files are only for development and tests")
    if provider_type == "file":
        key_path = Path(os.environ.get("TDE_FILE_KEY_PATH", "/var/lib/postgresql/tde-keyring/pg_tde_keyring"))
        data_path = Path(os.environ.get("PGDATA", "/var/lib/postgresql/data"))
        if key_path.resolve().is_relative_to(data_path.resolve()):
            raise RuntimeError("TDE_FILE_KEY_PATH must be outside PGDATA so database-volume loss cannot destroy its keys")
    return provider_name, provider_type


def _ensure_provider(connection: psycopg.Connection, name: str, kind: str) -> None:
    providers = connection.execute("SELECT name, type FROM pg_tde_list_all_global_key_providers()").fetchall()
    existing = next((provider_type for provider_name, provider_type in providers if provider_name == name), None)
    if existing:
        if existing != kind:
            raise RuntimeError(f"Configured TDE provider {name!r} has type {existing!r}; expected {kind!r}")
        return

    if kind == "file":
        key_file = os.environ.get("TDE_FILE_KEY_PATH", "/var/lib/postgresql/tde-keyring/pg_tde_keyring")
        connection.execute("SELECT pg_tde_add_global_key_provider_file(%s, %s)", (name, key_file))
    elif kind == "vault":
        vault_url = os.environ["TDE_VAULT_URL"]
        mount = os.environ.get("TDE_VAULT_MOUNT", "tde/data/sps-dashboard")
        token_file = os.environ["TDE_VAULT_TOKEN_FILE"]
        ca_file = os.environ.get("TDE_VAULT_CA_FILE") or None
        connection.execute(
            "SELECT pg_tde_add_global_key_provider_vault_v2(%s, %s, %s, %s, %s)",
            (name, vault_url, mount, token_file, ca_file),
        )
    else:
        raise RuntimeError("TDE_PROVIDER must be 'file' or 'vault'")
    connection.commit()


def _ensure_key(connection: psycopg.Connection, key_name: str, provider_name: str, info_function: str, set_function: str) -> None:
    info = connection.execute(sql.SQL("SELECT key_name, provider_name FROM {}() LIMIT 1").format(sql.Identifier(info_function))).fetchone()
    if info and info[0] is not None:
        if info[0] != key_name or info[1] != provider_name:
            raise RuntimeError(f"TDE already uses key {info[0]!r} from provider {info[1]!r}; refusing implicit key rotation")
        return
    if info and info[1] is not None:
        raise RuntimeError("TDE key metadata is incomplete; refusing implicit key rotation")

    try:
        connection.execute("SELECT pg_tde_create_key_using_global_key_provider(%s, %s)", (key_name, provider_name))
        connection.commit()
    except psycopg.Error:
        connection.rollback()
        # The remote KMS write may have succeeded before a prior bootstrap was interrupted.
        # Setting the named key is the safe existence check; it fails if the key is unavailable.
    connection.execute(sql.SQL("SELECT {}(%s, %s)").format(sql.Identifier(set_function)), (key_name, provider_name))
    connection.commit()


def _setup_global_provider(admin_url: str) -> tuple[str, str]:
    with psycopg.connect(_database_url(admin_url, "postgres")) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pg_tde")
        connection.commit()
        provider_name, provider_type = _provider_settings()
        _ensure_provider(connection, provider_name, provider_type)
        connection.commit()
    return provider_name, provider_type


def _encrypt_application_tables(admin_url: str, database_name: str, provider_name: str) -> None:
    with psycopg.connect(_database_url(admin_url, database_name)) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pg_tde")
        connection.commit()

        _ensure_key(
            connection,
            os.environ.get("TDE_DEFAULT_KEY_NAME", "sps-default-key"),
            provider_name,
            "pg_tde_default_key_info",
            "pg_tde_set_default_key_using_global_key_provider",
        )
        verified = connection.execute("SELECT pg_tde_verify_default_key()").fetchone()
        if verified is not None and verified[0] is False:
            raise RuntimeError("pg_tde could not verify the application database principal key")

        tables = connection.execute(
            """
            SELECT namespace.nspname, relation.relname, relation.relkind, COALESCE(access_method.amname, '')
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_am AS access_method ON access_method.oid = relation.relam
            WHERE relation.relkind IN ('r', 'p', 'm')
              AND namespace.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'pg_tde')
              AND namespace.nspname NOT LIKE 'pg_temp_%'
            ORDER BY namespace.nspname, relation.relname
            """
        ).fetchall()
        for schema_name, table_name, relation_type, access_method in tables:
            schema_name = _text(schema_name)
            table_name = _text(table_name)
            relation_type = _text(relation_type)
            access_method = _text(access_method)
            qualified_name = sql.Identifier(schema_name, table_name).as_string(connection)
            encrypted = connection.execute("SELECT pg_tde_is_encrypted(%s)", (qualified_name,)).fetchone()[0]
            if encrypted is not True and not (relation_type == "p" and access_method == "tde_heap"):
                relation = sql.Identifier(schema_name, table_name)
                if relation_type == "m":
                    connection.execute(sql.SQL("ALTER MATERIALIZED VIEW {} SET ACCESS METHOD tde_heap").format(relation))
                else:
                    connection.execute(sql.SQL("ALTER TABLE {} SET ACCESS METHOD tde_heap").format(relation))
                connection.commit()

        database_ident = sql.Identifier(database_name)
        connection.execute(sql.SQL("ALTER DATABASE {} SET default_table_access_method = 'tde_heap'").format(database_ident))
        connection.execute(sql.SQL("ALTER DATABASE {} SET pg_tde.enforce_encryption = 'on'").format(database_ident))
        connection.commit()
        _verify_application_tables(connection)


def _ensure_server_key(admin_url: str, provider_name: str) -> None:
    with psycopg.connect(_database_url(admin_url, "postgres")) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pg_tde")
        connection.commit()
        _ensure_key(
            connection,
            os.environ.get("TDE_SERVER_KEY_NAME", "sps-wal-key"),
            provider_name,
            "pg_tde_server_key_info",
            "pg_tde_set_server_key_using_global_key_provider",
        )
        connection.execute("SELECT pg_tde_verify_server_key()")
        connection.commit()


def _enable_wal_encryption(admin_url: str) -> None:
    # ALTER SYSTEM is required because pg_tde.wal_encrypt is restart-only.
    # The Compose startup script restarts PostgreSQL after this preparation.
    with psycopg.connect(_database_url(admin_url, "postgres"), autocommit=True) as connection:
        setting = connection.execute("SHOW pg_tde.wal_encrypt").fetchone()[0].lower()
        if setting not in {"on", "true", "1"}:
            connection.execute("ALTER SYSTEM SET pg_tde.wal_encrypt = 'on'")


def _verify_application_tables(connection: psycopg.Connection) -> None:
    relations = connection.execute(
        """
        SELECT namespace.nspname, relation.relname
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE relation.relkind IN ('r', 'i', 'S', 'm', 't')
          AND namespace.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_tde', 'pg_toast')
          AND namespace.nspname NOT LIKE 'pg_temp_%'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
        ORDER BY namespace.nspname, relation.relname
        """
    ).fetchall()
    unencrypted = []
    for schema_name, relation_name in relations:
        schema_name = _text(schema_name)
        relation_name = _text(relation_name)
        qualified_name = sql.Identifier(schema_name, relation_name).as_string(connection)
        encrypted = connection.execute("SELECT pg_tde_is_encrypted(%s)", (qualified_name,)).fetchone()[0]
        if encrypted is not True:
            unencrypted.append(f"{schema_name}.{relation_name}")
    if unencrypted:
        raise RuntimeError(f"Unencrypted PostgreSQL relations remain: {', '.join(unencrypted[:10])}")


def _prepare() -> None:
    database_url = os.environ["DATABASE_URL"]
    admin_url = os.environ.get("DATABASE_ADMIN_URL", database_url)
    database_name = make_url(database_url).database
    if not database_name:
        raise RuntimeError("DATABASE_URL must identify the application database")
    provider_name, _ = _setup_global_provider(admin_url)
    _ensure_server_key(admin_url, provider_name)
    _encrypt_application_tables(admin_url, database_name, provider_name)
    _enable_wal_encryption(admin_url)
    print(f"PostgreSQL TDE prepared for {database_name}; restart PostgreSQL to enable WAL encryption if newly configured.")


def _verify() -> None:
    database_url = os.environ["DATABASE_URL"]
    admin_url = os.environ.get("DATABASE_ADMIN_URL", database_url)
    database_name = make_url(database_url).database
    if not database_name:
        raise RuntimeError("DATABASE_URL must identify the application database")
    with psycopg.connect(_database_url(admin_url, database_name)) as connection:
        connection.execute("SELECT pg_tde_verify_default_key()")
        connection.execute("SELECT pg_tde_verify_server_key()")
        row = connection.execute(
            "SELECT current_setting('default_table_access_method'), current_setting('pg_tde.enforce_encryption'), current_setting('pg_tde.wal_encrypt')"
        ).fetchone()
        settings = tuple(value.decode("utf-8") if isinstance(value, bytes) else value for value in row)
        enabled = {"on", "true", "1"}
        if settings[0] != "tde_heap" or settings[1].lower() not in enabled or settings[2].lower() not in enabled:
            raise RuntimeError(
                "PostgreSQL TDE settings are not fully enabled: "
                f"default_table_access_method={settings[0]!r}, "
                f"pg_tde.enforce_encryption={settings[1]!r}, pg_tde.wal_encrypt={settings[2]!r}"
            )
        _verify_application_tables(connection)
    print(f"PostgreSQL TDE verified for all stored user tables in {database_name}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or verify PostgreSQL transparent data encryption.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true", help="Provision keys and encrypt existing user tables.")
    modes.add_argument("--verify", action="store_true", help="Verify relation, enforcement, and WAL encryption.")
    args = parser.parse_args()
    if args.prepare:
        _prepare()
    else:
        _verify()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"TDE setup failed: {error}", file=sys.stderr)
        raise
