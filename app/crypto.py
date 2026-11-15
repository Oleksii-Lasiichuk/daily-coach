"""Encrypt users' third-party keys at rest (Fernet = AES-128-CBC + HMAC)."""

import hashlib
import hmac

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().app_encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def last4(secret: str) -> str:
    return secret[-4:]


def derived_key(label: str) -> str:
    """A separate key for another purpose (e.g. the session cookie), from the same secret."""
    key = get_settings().app_encryption_key.encode()
    return hmac.new(key, label.encode(), hashlib.sha256).hexdigest()
