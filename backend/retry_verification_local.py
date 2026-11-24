"""Explicit local-only retry. Configuration comes solely from process environment."""
import argparse
import asyncio
import getpass
import logging
import os
import sys
import warnings
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from email_delivery import SMTPConfig, SMTPEmailSender, EmailDeliveryError, EmailSubmissionUncertain
from email_verification import create_token_fields, RESEND_COOLDOWN

INDEX_NAME = "unique_email_verification_token_hash"
TOKEN_FIELDS = (
    "email_verification_token_hash",
    "email_verification_expires_at",
    "email_verification_issued_at",
)
MAX_TOKEN_ATTEMPTS = 3


def validate_configuration():
    """Static validation only: no client construction, DNS, or network calls."""
    SMTPConfig.from_environment()
    uri = os.environ.get("MONGODB_URI", "")
    database_name = os.environ.get("DATABASE_NAME", "textech")
    parsed = urlsplit(uri)
    if (parsed.scheme not in ("mongodb", "mongodb+srv") or not parsed.netloc
            or any(c in uri for c in "\r\n\x00")
            or not database_name or any(c in database_name for c in '/\\. "$\x00')):
        raise ValueError("Invalid configuration")
    return uri, database_name


async def retry_existing_account(collection, email, sender, *, now=None):
    """Replace only observed token metadata; never insert or modify account details."""
    validate_configuration()
    if not collection.write_concern.acknowledged:
        return "failed"
    indexes = await collection.index_information()
    index = indexes.get(INDEX_NAME, {})
    if (list(index.get("key", [])) != [(TOKEN_FIELDS[0], 1)]
            or index.get("unique") is not True
            or index.get("partialFilterExpression") != {TOKEN_FIELDS[0]: {"$type": "string"}}
            or "buildUUID" in index):
        return "failed"
    account = await collection.find_one({"work_email": email})
    if not account or account.get("email_verified") is True:
        return "failed"
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        return "failed"
    now = now.astimezone(timezone.utc)
    issued = account.get(TOKEN_FIELDS[2])
    if TOKEN_FIELDS[2] in account:
        if not isinstance(issued, datetime):
            return "failed"
        # MongoDB's default decoding is naive UTC; the real client uses tz_aware.
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        if now - issued < RESEND_COOLDOWN:
            return "failed"
    query = {"_id": account["_id"], "work_email": email, "email_verified": {"$ne": True}}
    for field in TOKEN_FIELDS:
        query[field] = ({"$exists": True, "$eq": account[field]}
                        if field in account else {"$exists": False})
    for attempt in range(MAX_TOKEN_ATTEMPTS):
        token, fields = create_token_fields(now=now)
        try:
            result = await collection.update_one(query, {"$set": fields}, upsert=False)
        except DuplicateKeyError as error:
            if (error.details or {}).get("keyPattern") != {TOKEN_FIELDS[0]: 1}:
                return "failed"
            continue
        if result.modified_count != 1:
            return "failed"
        try:
            await sender.send_verification(email, token)
        except EmailSubmissionUncertain:
            return "uncertain"
        except EmailDeliveryError:
            return "failed"
        except Exception:
            # An unexpected sender failure cannot prove non-submission.
            return "uncertain"
        return "submitted"
    return "failed"


async def send_once(email):
    uri, database_name = validate_configuration()
    client = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000,
                              connectTimeoutMS=5000)
    try:
        return await retry_existing_account(client[database_name]["users"], email, SMTPEmailSender())
    finally:
        try:
            await client.close()
        except Exception:
            pass  # Cleanup cannot change a confirmed submission outcome.


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local verification-email retry; never loads .env")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Static config check; silent success, exit 0")
    modes.add_argument("--send", action="store_true", help="Explicitly send once to an existing unverified account")
    args = parser.parse_args(argv)
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            validate_configuration()
            if args.check:
                return 0
            if not sys.stdin.isatty():
                raise ValueError("Hidden interactive input required")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                email = getpass.getpass("Account email (hidden): ").strip().lower()
            if not email or "@" not in email or any(c in email for c in "\r\n\x00"):
                raise ValueError("Invalid account input")
            outcome = asyncio.run(send_once(email))
        except KeyboardInterrupt:
            # Interrupted submission may already have reached SMTP.
            outcome = "uncertain" if args.send else "failed"
        except Exception:
            # This CLI boundary intentionally suppresses all exception text/tracebacks.
            outcome = "failed"
        print(outcome)
        return {"submitted": 0, "failed": 1, "uncertain": 2}[outcome]
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
