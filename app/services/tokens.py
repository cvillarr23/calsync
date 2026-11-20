"""Encrypting Google refresh tokens at rest with the instance's Fernet key."""

from cryptography.fernet import Fernet

from app.settings import Settings


def encrypt_token(settings: Settings, token: str) -> str:
    return _fernet(settings).encrypt(token.encode()).decode()


def decrypt_token(settings: Settings, token_enc: str) -> str:
    return _fernet(settings).decrypt(token_enc.encode()).decode()


def _fernet(settings: Settings) -> Fernet:
    return Fernet(settings.token_enc_key.get_secret_value())
