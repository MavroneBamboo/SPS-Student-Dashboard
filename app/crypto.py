from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().app_encryption_key.encode())


def encrypt_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt sensitive value") from exc


def encrypt_sensitive_bytes(value: bytes) -> bytes:
    return _fernet().encrypt(value)


def decrypt_sensitive_bytes(value: bytes) -> bytes:
    try:
        return _fernet().decrypt(value)
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt sensitive value") from exc
