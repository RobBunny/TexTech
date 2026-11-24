"""Offline-safe email verification primitives; no connections at import time."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from pymongo.asynchronous.collection import AsyncCollection

TOKEN_LIFETIME = timedelta(minutes=30)
RESEND_COOLDOWN = timedelta(seconds=60)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def hash_token(token: str) -> str:
    """Hash a random token, never a password."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _utc(now):
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    return now.astimezone(timezone.utc)


def create_token_fields(*, now=None, lifetime=TOKEN_LIFETIME):
    """Return the delivery secret separately from fields safe to persist."""
    if lifetime <= timedelta(0):
        raise ValueError("Token lifetime must be positive")
    now = _utc(now)
    token = secrets.token_urlsafe(32)
    return token, {
        "email_verification_token_hash": hash_token(token),
        "email_verification_expires_at": now + lifetime,
        "email_verification_issued_at": now,
    }


async def verify_email(collection: AsyncCollection, token: str, *, now=None) -> bool:
    """Consume the token and verify its user in one atomic MongoDB update.

    False covers invalid, expired, used, and already-verified tokens alike.
    Database failures propagate to the caller. No accounts are inserted/deleted.
    """
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        return False
    now = _utc(now)
    result = await collection.update_one(
        {
            "email_verified": {"$ne": True},
            "email_verification_token_hash": hash_token(token),
            "email_verification_expires_at": {"$gt": now},
        },
        {
            "$set": {"email_verified": True, "email_verified_at": now},
            "$unset": {
                "email_verification_token_hash": "",
                "email_verification_expires_at": "",
                "email_verification_issued_at": "",
            },
        },
        upsert=False,
    )
    return result.modified_count == 1
