import asyncio
import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from email_verification import create_token_fields, hash_token, verify_email

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


class AtomicCollectionFake:
    """Models the update contract; this is not a MongoDB integration test."""
    def __init__(self, document):
        self.document = copy.deepcopy(document)
        self.lock = asyncio.Lock()

    async def update_one(self, query, update, *, upsert):
        assert upsert is False
        async with self.lock:
            doc = self.document
            matches = (
                doc.get("email_verified") is not True
                and doc.get("email_verification_token_hash") == query["email_verification_token_hash"]
                and doc.get("email_verification_expires_at", NOW) > query["email_verification_expires_at"]["$gt"]
            )
            if matches:
                doc.update(update["$set"])
                for key in update["$unset"]:
                    doc.pop(key, None)
            return SimpleNamespace(modified_count=int(matches))


class TokenTests(unittest.TestCase):
    def test_known_sha256_vector(self):
        self.assertEqual(
            hash_token("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_random_secret_hash_and_default_expiry(self):
        token, fields = create_token_fields(now=NOW)
        other, _ = create_token_fields(now=NOW)
        self.assertNotEqual(token, other)
        self.assertEqual(len(token), 43)
        self.assertEqual(fields["email_verification_token_hash"], hash_token(token))
        self.assertNotIn(token, fields.values())
        self.assertEqual(fields["email_verification_expires_at"], NOW + timedelta(minutes=30))
        self.assertEqual(fields["email_verification_issued_at"], NOW)

    def test_invalid_configuration(self):
        for lifetime in (timedelta(0), timedelta(seconds=-1)):
            with self.assertRaises(ValueError):
                create_token_fields(now=NOW, lifetime=lifetime)
        with self.assertRaises(ValueError):
            create_token_fields(now=datetime(2026, 10, 9))

    def test_timezone_and_custom_lifetime(self):
        _, fields = create_token_fields(now=NOW.astimezone(timezone(timedelta(hours=6))), lifetime=timedelta(minutes=5))
        self.assertEqual(fields["email_verification_issued_at"].tzinfo, timezone.utc)
        self.assertEqual(fields["email_verification_expires_at"], NOW + timedelta(minutes=5))


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_update_contract(self):
        token, fields = create_token_fields(now=NOW)
        collection = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)))
        self.assertTrue(await verify_email(collection, token, now=NOW))
        collection.update_one.assert_awaited_once_with(
            {"email_verified": {"$ne": True}, "email_verification_token_hash": fields["email_verification_token_hash"], "email_verification_expires_at": {"$gt": NOW}},
            {"$set": {"email_verified": True, "email_verified_at": NOW}, "$unset": {key: "" for key in fields}},
            upsert=False,
        )

    async def test_false_missing_status_and_reuse(self):
        for status in ({}, {"email_verified": False}):
            token, fields = create_token_fields(now=NOW)
            collection = AtomicCollectionFake({"_id": "user", "password_hash": "unchanged", **status, **fields})
            self.assertTrue(await verify_email(collection, token, now=NOW))
            self.assertEqual(collection.document, {"_id": "user", "password_hash": "unchanged", "email_verified": True, "email_verified_at": NOW})
            self.assertFalse(await verify_email(collection, token, now=NOW))

    async def test_expiry_wrong_token_and_verified_account(self):
        token, fields = create_token_fields(now=NOW)
        for moment, status, submitted in (
            (NOW + timedelta(minutes=30), False, token),
            (NOW + timedelta(minutes=31), False, token),
            (NOW, True, token),
            (NOW, False, "A" * 43),
        ):
            collection = AtomicCollectionFake({"email_verified": status, **fields})
            before = copy.deepcopy(collection.document)
            self.assertFalse(await verify_email(collection, submitted, now=moment))
            self.assertEqual(collection.document, before)

    async def test_malformed_tokens_skip_database(self):
        collection = SimpleNamespace(update_one=AsyncMock())
        for token in (None, "", "short", "é" * 43, "A" * 44, "A" * 42 + "\n"):
            self.assertFalse(await verify_email(collection, token, now=NOW))
        collection.update_one.assert_not_awaited()

    async def test_concurrent_attempts_have_one_winner(self):
        token, fields = create_token_fields(now=NOW)
        collection = AtomicCollectionFake({"email_verified": False, **fields})
        results = await asyncio.gather(*(verify_email(collection, token, now=NOW) for _ in range(2)))
        self.assertEqual(sorted(results), [False, True])

    async def test_database_error_propagates(self):
        token, _ = create_token_fields(now=NOW)
        collection = SimpleNamespace(update_one=AsyncMock(side_effect=RuntimeError("database unavailable")))
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            await verify_email(collection, token, now=NOW)


if __name__ == "__main__":
    unittest.main()
