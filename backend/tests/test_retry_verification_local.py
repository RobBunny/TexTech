import contextlib
import copy
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pymongo.errors import DuplicateKeyError, ConnectionFailure
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain
from email_verification import hash_token
import retry_verification_local as retry

ENV = {"MONGODB_URI": "mongodb://localhost:27017", "SMTP_HOST": "smtp.invalid",
       "SMTP_FROM_ADDRESS": "sender@example.com"}
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
EMAIL = "buyer@example.com"
INDEX = {retry.INDEX_NAME: {"key": [(retry.TOKEN_FIELDS[0], 1)], "unique": True,
         "partialFilterExpression": {retry.TOKEN_FIELDS[0]: {"$type": "string"}}}}


class Collection:
    def __init__(self, account=None):
        self.account = copy.deepcopy(account if account is not None else {
            "_id": "original", "work_email": EMAIL, "email_verified": False,
            "password": "unchanged-hash", "profile": {"company": "unchanged"}})
        self.indexes = copy.deepcopy(INDEX)
        self.calls = []
        self.collisions = 0
        self.race = None
        self.write_concern = SimpleNamespace(acknowledged=True)

    async def index_information(self):
        return self.indexes

    async def find_one(self, query):
        return copy.deepcopy(self.account) if self.account and self.account["work_email"] == query["work_email"] else None

    async def update_one(self, query, update, *, upsert):
        self.calls.append((copy.deepcopy(query), copy.deepcopy(update), upsert))
        if self.collisions:
            self.collisions -= 1
            raise DuplicateKeyError("private provider detail", details={"keyPattern": {retry.TOKEN_FIELDS[0]: 1}})
        if self.race:
            self.account.update(self.race)
        for key, expected in query.items():
            if isinstance(expected, dict):
                if "$ne" in expected and self.account.get(key) == expected["$ne"]:
                    return SimpleNamespace(modified_count=0)
                if "$exists" in expected and (key in self.account) != expected["$exists"]:
                    return SimpleNamespace(modified_count=0)
                if "$eq" in expected and self.account.get(key) != expected["$eq"]:
                    return SimpleNamespace(modified_count=0)
            elif self.account.get(key) != expected:
                return SimpleNamespace(modified_count=0)
        self.account.update(update["$set"])
        return SimpleNamespace(modified_count=1)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.collection = Collection()
        self.sender = SimpleNamespace(send_verification=AsyncMock())

    async def send(self):
        return await retry.retry_existing_account(self.collection, EMAIL, self.sender, now=NOW)

    async def test_persists_only_hash_and_token_timestamps(self):
        original = copy.deepcopy(self.collection.account)
        self.assertEqual(await self.send(), "submitted")
        recipient, token = self.sender.send_verification.call_args.args
        self.assertEqual(recipient, EMAIL)
        self.assertEqual(self.collection.account[retry.TOKEN_FIELDS[0]], hash_token(token))
        self.assertEqual(self.collection.account[retry.TOKEN_FIELDS[1]], NOW + timedelta(minutes=30))
        self.assertEqual(self.collection.account[retry.TOKEN_FIELDS[2]], NOW)
        self.assertNotIn(token, repr(self.collection.account))
        for key, value in original.items():
            self.assertEqual(self.collection.account[key], value)
        query, update, upsert = self.collection.calls[0]
        self.assertFalse(upsert)
        self.assertEqual(set(update["$set"]), set(retry.TOKEN_FIELDS))
        self.assertEqual(query["_id"], original["_id"])
        self.assertEqual(query["email_verified"], {"$ne": True})
        for field in retry.TOKEN_FIELDS:
            self.assertEqual(query[field], {"$exists": False})

    async def test_missing_or_wrong_index_prevents_changes(self):
        for index in ({}, {**INDEX[retry.INDEX_NAME], "unique": False},
                      {**INDEX[retry.INDEX_NAME], "partialFilterExpression": {}},
                      {**INDEX[retry.INDEX_NAME], "key": [("other", 1)]},
                      {**INDEX[retry.INDEX_NAME], "buildUUID": "building"}):
            self.collection.indexes = {retry.INDEX_NAME: index}
            self.assertEqual(await self.send(), "failed")
        self.assertEqual(self.collection.calls, [])
        self.sender.send_verification.assert_not_awaited()

    async def test_no_existing_account_or_verified_account(self):
        self.collection.account["email_verified"] = True
        self.assertEqual(await self.send(), "failed")
        self.collection.account = None
        self.assertEqual(await self.send(), "failed")
        self.assertEqual(self.collection.calls, [])

    async def test_cooldown_boundary_and_naive_utc(self):
        for issued in (NOW - timedelta(seconds=59), NOW + timedelta(seconds=1),
                       (NOW - timedelta(seconds=59)).replace(tzinfo=None), "invalid", None):
            self.collection.account[retry.TOKEN_FIELDS[2]] = issued
            self.assertEqual(await self.send(), "failed")
        self.assertEqual(self.collection.calls, [])
        self.collection.account[retry.TOKEN_FIELDS[2]] = NOW - timedelta(seconds=60)
        self.assertEqual(await self.send(), "submitted")

    async def test_concurrent_verification_or_token_rotation_prevents_send(self):
        for race in ({"email_verified": True}, {retry.TOKEN_FIELDS[0]: "other-hash"},
                     {retry.TOKEN_FIELDS[1]: NOW}, {retry.TOKEN_FIELDS[2]: NOW}):
            self.collection = Collection()
            self.collection.race = race
            self.assertEqual(await self.send(), "failed")
        self.sender.send_verification.assert_not_awaited()

    async def test_present_null_metadata_is_distinguished_from_missing(self):
        self.collection.account[retry.TOKEN_FIELDS[0]] = None
        self.assertEqual(await self.send(), "submitted")
        self.assertEqual(self.collection.calls[0][0][retry.TOKEN_FIELDS[0]], {"$exists": True, "$eq": None})

    async def test_collision_retries_are_bounded(self):
        self.collection.collisions = 2
        self.assertEqual(await self.send(), "submitted")
        self.assertEqual(len(self.collection.calls), 3)
        hashes = [call[1]["$set"][retry.TOKEN_FIELDS[0]] for call in self.collection.calls]
        self.assertEqual(len(set(hashes)), 3)
        self.collection = Collection()
        self.collection.collisions = 3
        self.sender.send_verification.reset_mock()
        self.assertEqual(await self.send(), "failed")
        self.assertEqual(len(self.collection.calls), 3)
        self.sender.send_verification.assert_not_awaited()

    async def test_failure_and_uncertain_retain_new_token_without_retry(self):
        for error, expected in ((EmailDeliveryError("private"), "failed"),
                                (EmailSubmissionUncertain("private"), "uncertain"),
                                (RuntimeError("private"), "uncertain")):
            self.collection = Collection()
            self.sender.send_verification = AsyncMock(side_effect=error)
            self.assertEqual(await self.send(), expected)
            self.assertFalse(self.collection.account["email_verified"])
            self.assertIn(retry.TOKEN_FIELDS[0], self.collection.account)
            self.assertEqual(len(self.collection.calls), 1)
            self.sender.send_verification.assert_awaited_once()

    async def test_bad_config_prevents_any_database_operations(self):
        self.collection.index_information = AsyncMock()
        with patch.dict(os.environ, {"SMTP_HOST": ""}):
            with self.assertRaises(EmailDeliveryError):
                await self.send()
        self.collection.index_information.assert_not_awaited()

    async def test_unacknowledged_writes_are_rejected_before_changes(self):
        self.collection.write_concern.acknowledged = False
        self.assertEqual(await self.send(), "failed")
        self.assertEqual(self.collection.calls, [])
        self.sender.send_verification.assert_not_awaited()

    async def test_existing_metadata_is_matched_and_second_retry_is_cooled_down(self):
        old = {retry.TOKEN_FIELDS[0]: "old-hash",
               retry.TOKEN_FIELDS[1]: NOW - timedelta(minutes=1),
               retry.TOKEN_FIELDS[2]: NOW - timedelta(minutes=31)}
        self.collection.account.update(old)
        self.assertEqual(await self.send(), "submitted")
        query = self.collection.calls[0][0]
        for field, value in old.items():
            self.assertEqual(query[field], {"$exists": True, "$eq": value})
        self.assertEqual(await self.send(), "failed")
        self.sender.send_verification.assert_awaited_once()

    async def test_unrelated_duplicate_key_is_not_retried(self):
        self.collection.update_one = AsyncMock(side_effect=DuplicateKeyError(
            "private", details={"keyPattern": {"work_email": 1}}))
        self.assertEqual(await self.send(), "failed")
        self.collection.update_one.assert_awaited_once()
        self.sender.send_verification.assert_not_awaited()

    async def test_email_wording_is_relative_to_token_issuance(self):
        from email_delivery import SMTPEmailSender
        with patch("email_delivery.smtplib.SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            await SMTPEmailSender().send_verification(EMAIL, "A" * 43)
        content = smtp.send_message.call_args.args[0].get_content()
        self.assertIn("30 minutes after this verification link was issued", content)
        self.assertNotIn("after account creation", content)

    async def test_database_error_never_sends(self):
        self.collection.update_one = AsyncMock(side_effect=ConnectionFailure("private"))
        with self.assertRaises(ConnectionFailure):
            await self.send()
        self.sender.send_verification.assert_not_awaited()


class CLITests(unittest.TestCase):
    def test_check_is_silent_and_never_constructs_client_or_sender(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(retry, "AsyncMongoClient") as client, patch.object(retry, "SMTPEmailSender") as sender, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(retry.main(["--check"]), 0)
        self.assertEqual(output.getvalue(), "")
        client.assert_not_called()
        sender.assert_not_called()

    def test_invalid_config_has_only_generic_output(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(retry, "AsyncMongoClient") as client, contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(retry.main(["--check"]), 1)
        self.assertEqual(output.getvalue(), "failed\n")
        self.assertEqual(errors.getvalue(), "")
        client.assert_not_called()

    def test_no_unsafe_prompt_fallback(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(retry.sys.stdin, "isatty", return_value=False), patch.object(retry.getpass, "getpass") as prompt, patch.object(retry, "send_once") as send, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(retry.main(["--send"]), 1)
        prompt.assert_not_called()
        send.assert_not_called()
        self.assertEqual(output.getvalue(), "failed\n")

    def test_send_boundary_sanitizes_database_exception(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(retry.sys.stdin, "isatty", return_value=True), patch.object(retry.getpass, "getpass", return_value=EMAIL), patch.object(retry, "send_once", new=AsyncMock(side_effect=ConnectionFailure("secret"))), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(retry.main(["--send"]), 1)
        self.assertEqual(output.getvalue(), "failed\n")


if __name__ == "__main__":
    unittest.main()
