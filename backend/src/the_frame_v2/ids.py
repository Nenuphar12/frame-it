"""Identifier and time helpers."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

# Crockford base32 without ambiguous characters (I, L, O, U).
_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id() -> str:
    """UUIDv7 string: time-ordered and merge-friendly for imports."""
    return str(uuid.uuid7())


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    """256-bit URL-safe secret."""
    return secrets.token_urlsafe(32)


def new_human_code(length: int = 10) -> str:
    """Human-typable code, grouped in blocks of 5 (e.g. `7K3QF-M2XRA`)."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    return "-".join(raw[i : i + 5] for i in range(0, length, 5))


def normalize_human_code(code: str) -> str:
    cleaned = code.upper().replace("-", "").replace(" ", "")
    cleaned = cleaned.replace("O", "0").replace("I", "1").replace("L", "1")
    return "-".join(cleaned[i : i + 5] for i in range(0, len(cleaned), 5))
