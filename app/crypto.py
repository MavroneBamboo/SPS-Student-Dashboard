import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_PREFIX = "spsenc:v1:"


@lru_cache(maxsize=8)
def _build_keyring(active_key: str, previous_keys: str) -> tuple[str, list[tuple[str, Fernet]]]:
    active_key = active_key.strip()
    if not active_key:
        raise ValueError("The active application encryption key is required")
    raw_keys = [active_key, *previous_keys.split(",")]
    keys: list[tuple[str, Fernet]] = []
    seen: set[str] = set()
    for raw_key in raw_keys:
        raw_key = raw_key.strip()
        if not raw_key:
            continue
        try:
            fernet = Fernet(raw_key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("Application encryption key configuration is invalid") from exc
        key_id = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
        if key_id in seen:
            raise ValueError("Application encryption key configuration contains a duplicate key")
        seen.add(key_id)
        keys.append((key_id, fernet))
    if not keys:
        raise ValueError("At least one application encryption key must be configured")
    return keys[0][0], keys


def _keyring() -> tuple[str, list[tuple[str, Fernet]]]:
    settings = get_settings()
    return _build_keyring(settings.app_encryption_key, settings.app_encryption_previous_keys)


def _encrypt(value: bytes) -> bytes:
    active_id, keys = _keyring()
    token = keys[0][1].encrypt(value).decode("ascii")
    return f"{_PREFIX}{active_id}:{token}".encode("ascii")


def _decrypt(value: bytes) -> bytes:
    active_id, keys = _keyring()
    try:
        encoded = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Unable to decrypt sensitive value") from exc

    if encoded.startswith("spsenc:"):
        marker, version, key_id, token = encoded.split(":", 3) if encoded.count(":") >= 3 else ("", "", "", "")
        if marker != "spsenc" or version != "v1" or not token:
            raise ValueError("Unable to decrypt sensitive value")
        fernet = next((candidate for candidate_id, candidate in keys if candidate_id == key_id), None)
        if fernet is None:
            raise ValueError("Unable to decrypt sensitive value")
        try:
            return fernet.decrypt(token.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ValueError("Unable to decrypt sensitive value") from exc

    # Values written before key identifiers were introduced contain a raw Fernet token.
    for _, fernet in keys:
        try:
            return fernet.decrypt(value)
        except InvalidToken:
            continue
    raise ValueError("Unable to decrypt sensitive value")


def is_current_encryption(value: str | bytes | None) -> bool:
    if value is None:
        return True
    active_id, _ = _keyring()
    try:
        encoded = value.decode("ascii") if isinstance(value, bytes) else value
    except UnicodeDecodeError:
        return False
    return encoded.startswith(f"{_PREFIX}{active_id}:")


def encrypt_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    return _encrypt(value.encode()).decode("ascii")


def decrypt_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _decrypt(value.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Unable to decrypt sensitive value") from exc


def encrypt_sensitive_bytes(value: bytes) -> bytes:
    return _encrypt(value)


def decrypt_sensitive_bytes(value: bytes) -> bytes:
    try:
        return _decrypt(value)
    except ValueError as exc:
        raise ValueError("Unable to decrypt sensitive value") from exc
