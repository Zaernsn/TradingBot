import base64
from hashlib import sha256
from cryptography.fernet import Fernet
from app.core.config import settings


def _get_fernet() -> Fernet:
    key = settings.KRAKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    if not key:
        raise ValueError("KRAKEN_ENCRYPTION_KEY or SECRET_KEY must be configured")
    hashed = sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(hashed))


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def mask_key(key: str) -> str:
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]
