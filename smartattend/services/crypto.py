"""Encryption at rest for biometric embeddings and photos (Fernet = AES-128-CBC + HMAC)."""
import hashlib
import os
from cryptography.fernet import Fernet, InvalidToken
import config


def _key() -> bytes:
    if config.ENCRYPTION_KEY:
        return config.ENCRYPTION_KEY.encode()
    if config.KEY_FILE.exists():
        return config.KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    config.KEY_FILE.write_bytes(key)
    try:
        os.chmod(config.KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_key())


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as e:
        raise ValueError("Cannot decrypt: wrong or missing SMARTATTEND_KEY") from e


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
