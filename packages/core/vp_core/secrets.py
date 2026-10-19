"""Encrypt tool credentials at rest (AES-256-GCM). The dashboard server encrypts; only the call worker decrypts,
so a credential never appears in a page, a log or a model prompt. Key: TOOL_SECRET_KEY in .env, 32 random bytes
in base64. Format: base64(iv[12] + ciphertext + tag[16]), the same layout Node's crypto module produces."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key() -> bytes:
    raw = os.environ.get("TOOL_SECRET_KEY")
    if not raw:
        raise RuntimeError("TOOL_SECRET_KEY is not set in .env")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("TOOL_SECRET_KEY must be 32 bytes, base64 encoded")
    return key


def encrypt(plain: str) -> str:
    iv = os.urandom(12)
    return base64.b64encode(iv + AESGCM(_key()).encrypt(iv, plain.encode(), None)).decode()


def decrypt(token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()


def new_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()
