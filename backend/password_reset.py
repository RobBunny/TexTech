"""Password-reset primitives; no environment loading or connections on import."""
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError
from email_verification import create_token_fields, hash_token, TOKEN_PATTERN

TOKEN_LIFETIME = timedelta(minutes=30)
ISSUANCE_COOLDOWN = timedelta(seconds=60)
TOKEN_INDEX_NAME = "unique_password_reset_token_hash"
TOKEN_FIELDS = ("password_reset_token_hash", "password_reset_expires_at", "password_reset_issued_at")


def create_reset_token_fields(*, now=None):
    token, verification_fields = create_token_fields(now=now, lifetime=TOKEN_LIFETIME)
    return token, dict(zip(TOKEN_FIELDS, (
        verification_fields["email_verification_token_hash"],
        verification_fields["email_verification_expires_at"],
        verification_fields["email_verification_issued_at"],
    )))


async def issue_password_reset(collection, email, sender, *, now=None):
    """Issue to one existing account atomically; cooldown also covers delivery failures."""
    for attempt in range(3):
        token, fields = create_reset_token_fields(now=now)
        issued = fields["password_reset_issued_at"]
        try:
            account = await collection.find_one_and_update(
                {"work_email": email, "$or": [
                    {"password_reset_issued_at": {"$exists": False}},
                    {"password_reset_issued_at": {"$lte": issued - ISSUANCE_COOLDOWN}},
                ]},
                {"$set": fields}, projection={"work_email": 1}, upsert=False,
            )
        except DuplicateKeyError as error:
            if (error.details or {}).get("keyPattern") != {"password_reset_token_hash": 1}:
                raise
            continue
        if account is None:
            return False
        # No automatic retry or rollback: the old link is now invalid.
        await sender.send_password_reset(account["work_email"], token)
        return True
    return False


async def reset_password(collection, token, new_password_hash, *, now=None):
    """Change the password and consume its token in a single conditional write."""
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    now = now.astimezone(timezone.utc)
    result = await collection.update_one(
        {"password_reset_token_hash": hash_token(token),
         "password_reset_expires_at": {"$gt": now}},
        # Retain issuance time so successful consumption cannot bypass cooldown.
        {"$set": {"password_hash": new_password_hash},
         "$unset": {field: "" for field in TOKEN_FIELDS[:2]}}, upsert=False,
    )
    return result.modified_count == 1
