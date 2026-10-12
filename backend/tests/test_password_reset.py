"""Stateful offline models of MongoDB operations, not live integration tests."""
import asyncio
import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError, ConnectionFailure
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain
from email_verification import hash_token
from password_reset import create_reset_token_fields, issue_password_reset, reset_password, TOKEN_FIELDS

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
EMAIL = "buyer@example.com"


class ResetCollectionFake:
    def __init__(self, document=None):
        self.document = copy.deepcopy(document)
        self.lock = asyncio.Lock()
        self.calls = []
        self.collisions = 0

    def matches(self, query):
        doc = self.document
        if doc is None:
            return False
        for key, expected in query.items():
            if key == "$or":
                if not any(self.matches(part) for part in expected):
                    return False
            elif isinstance(expected, dict):
                for operator, value in expected.items():
                    if operator == "$exists":
                        if (key in doc) != value:
                            return False
                    elif operator in ("$lte", "$gt"):
                        actual = doc.get(key)
                        if not isinstance(actual, datetime):
                            return False
                        if actual.tzinfo is None:
                            actual = actual.replace(tzinfo=timezone.utc)
                        if operator == "$lte" and not actual <= value:
                            return False
                        if operator == "$gt" and not actual > value:
                            return False
                    else:
                        raise AssertionError("Unsupported fake operator")
            elif doc.get(key) != expected:
                return False
        return True

    async def find_one_and_update(self, query, update, *, projection, upsert):
        assert upsert is False
        async with self.lock:
            self.calls.append((copy.deepcopy(query), copy.deepcopy(update)))
            if not self.matches(query):
                return None
            if self.collisions:
                self.collisions -= 1
                raise DuplicateKeyError("private", details={"keyPattern": {"password_reset_token_hash": 1}})
            previous = {key: self.document[key] for key in projection if key in self.document}
            self.document.update(update["$set"])
            return previous

    async def update_one(self, query, update, *, upsert):
        assert upsert is False
        async with self.lock:
            self.calls.append((copy.deepcopy(query), copy.deepcopy(update)))
            matches = self.matches(query)
            if matches:
                self.document.update(update["$set"])
                for key in update["$unset"]:
                    self.document.pop(key, None)
            return SimpleNamespace(modified_count=int(matches))


class ResetTokenTests(unittest.TestCase):
    def test_secure_generator_and_known_hash_vector(self):
        with patch("email_verification.secrets.token_urlsafe", return_value="abc") as generator:
            token, fields = create_reset_token_fields(now=NOW)
        generator.assert_called_once_with(32)
        self.assertTrue(fields["password_reset_token_hash"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertTrue(token not in fields.values())

    def test_random_token_hash_and_30_minute_expiry(self):
        first, fields = create_reset_token_fields(now=NOW)
        second, _ = create_reset_token_fields(now=NOW)
        self.assertTrue(first != second)
        self.assertEqual(len(first), 43)
        self.assertEqual(set(fields), set(TOKEN_FIELDS))
        self.assertTrue(fields["password_reset_token_hash"] == hash_token(first))
        self.assertEqual(fields["password_reset_issued_at"], NOW)
        self.assertEqual(fields["password_reset_expires_at"], NOW + timedelta(minutes=30))

    def test_timezone_normalization_and_naive_rejection(self):
        _, fields = create_reset_token_fields(now=NOW.astimezone(timezone(timedelta(hours=6))))
        self.assertEqual(fields["password_reset_issued_at"], NOW)
        with self.assertRaises(ValueError):
            create_reset_token_fields(now=NOW.replace(tzinfo=None))


class ResetLogicTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sender = SimpleNamespace(send_password_reset=AsyncMock())
        self.collection = ResetCollectionFake({"_id": "user", "work_email": EMAIL,
            "password_hash": "old-hash", "email_verified": False,
            "email_verification_token_hash": "verification-hash", "organization": "Company"})

    async def test_issue_preserves_all_account_fields_and_only_stores_hash(self):
        original = copy.deepcopy(self.collection.document)
        self.assertTrue(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        token = self.sender.send_password_reset.call_args.args[1]
        doc = self.collection.document
        self.assertTrue(token not in doc.values())
        self.assertTrue(doc["password_reset_token_hash"] == hash_token(token))
        for key, value in original.items():
            self.assertEqual(doc[key], value)

    async def test_unknown_account_never_inserted_or_sent(self):
        self.collection.document = None
        self.assertFalse(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        self.assertIsNone(self.collection.document)
        self.sender.send_password_reset.assert_not_awaited()

    async def test_cooldown_boundary_invalid_metadata_and_future_time(self):
        for issued in (NOW - timedelta(seconds=59), NOW + timedelta(seconds=1), None, "invalid"):
            self.collection.document["password_reset_issued_at"] = issued
            self.assertFalse(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        self.sender.send_password_reset.assert_not_awaited()
        self.collection.document["password_reset_issued_at"] = NOW - timedelta(seconds=60)
        self.assertTrue(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))

    async def test_concurrent_issuance_has_one_winner(self):
        outcomes = await asyncio.gather(*(issue_password_reset(self.collection, EMAIL, self.sender, now=NOW) for _ in range(2)))
        self.assertEqual(outcomes.count(True), 1)
        self.sender.send_password_reset.assert_awaited_once()

    async def test_collisions_bounded_and_unrelated_duplicate_propagates(self):
        self.collection.collisions = 2
        self.assertTrue(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        self.assertEqual(len(self.collection.calls), 3)
        self.collection.document.pop("password_reset_issued_at")
        self.collection.collisions = 3
        self.sender.send_password_reset.reset_mock()
        self.assertFalse(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        self.sender.send_password_reset.assert_not_awaited()
        self.collection.find_one_and_update = AsyncMock(side_effect=DuplicateKeyError("private", details={"keyPattern": {"other": 1}}))
        with self.assertRaises(DuplicateKeyError):
            await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW)
        self.collection.find_one_and_update.assert_awaited_once()

    async def test_replacement_invalidates_old_link_even_when_delivery_fails(self):
        for error in (EmailDeliveryError("private"), EmailSubmissionUncertain("private")):
            old_token, old_fields = create_reset_token_fields(now=NOW - timedelta(minutes=2))
            self.collection.document.update(old_fields)
            self.sender.send_password_reset = AsyncMock(side_effect=error)
            with self.assertRaises(type(error)):
                await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW)
            self.assertTrue(self.collection.document["password_reset_token_hash"] != old_fields["password_reset_token_hash"])
            self.assertFalse(await reset_password(self.collection, old_token, "new-hash", now=NOW))
            self.assertEqual(self.collection.document["password_hash"], "old-hash")
            self.assertFalse(self.collection.document["email_verified"])
            self.sender.send_password_reset.assert_awaited_once()

    async def test_expiry_boundary_wrong_and_reused_tokens(self):
        token, fields = create_reset_token_fields(now=NOW)
        self.collection.document.update(fields)
        self.assertFalse(await reset_password(self.collection, "B" * 43, "new-hash", now=NOW))
        self.assertFalse(await reset_password(self.collection, token, "new-hash", now=NOW + timedelta(minutes=30)))
        self.assertTrue(await reset_password(self.collection, token, "new-hash", now=NOW + timedelta(minutes=30) - timedelta(microseconds=1)))
        self.assertFalse(await reset_password(self.collection, token, "other-hash", now=NOW))
        self.assertEqual(self.collection.document["password_hash"], "new-hash")
        self.assertFalse(any(key in self.collection.document for key in TOKEN_FIELDS[:2]))
        self.assertFalse(self.collection.document["email_verified"])
        self.assertEqual(self.collection.document["email_verification_token_hash"], "verification-hash")

    async def test_concurrent_reset_has_one_winner(self):
        token, fields = create_reset_token_fields(now=NOW)
        self.collection.document.update(fields)
        outcomes = await asyncio.gather(*(reset_password(self.collection, token, "new-hash", now=NOW) for _ in range(2)))
        self.assertEqual(outcomes.count(True), 1)

    async def test_malformed_tokens_skip_database_and_naive_time_is_rejected(self):
        self.collection.update_one = AsyncMock()
        for token in (None, "", "bad", "A" * 42, "!" * 43):
            self.assertFalse(await reset_password(self.collection, token, "new-hash", now=NOW))
        self.collection.update_one.assert_not_awaited()
        with self.assertRaises(ValueError):
            await reset_password(self.collection, "A" * 43, "new-hash", now=NOW.replace(tzinfo=None))

    async def test_database_errors_propagate_and_do_not_send(self):
        self.collection.find_one_and_update = AsyncMock(side_effect=ConnectionFailure("private"))
        with self.assertRaises(ConnectionFailure):
            await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW)
        self.sender.send_password_reset.assert_not_awaited()
        self.collection.update_one = AsyncMock(side_effect=ConnectionFailure("private"))
        with self.assertRaises(ConnectionFailure):
            await reset_password(self.collection, "A" * 43, "new-hash", now=NOW)


    async def test_successful_reset_retains_issuance_cooldown(self):
        self.assertTrue(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW))
        token = self.sender.send_password_reset.call_args.args[1]
        self.assertTrue(await reset_password(self.collection, token, "new-hash", now=NOW))
        self.assertEqual(self.collection.document["password_reset_issued_at"], NOW)
        self.assertFalse(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW + timedelta(seconds=59)))
        self.sender.send_password_reset.assert_awaited_once()
        self.assertTrue(await issue_password_reset(self.collection, EMAIL, self.sender, now=NOW + timedelta(seconds=60)))
