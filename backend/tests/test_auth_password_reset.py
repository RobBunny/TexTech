"""Offline endpoint tests: fake collections/SMTP and an in-process ASGI harness."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks
from pymongo.errors import ConnectionFailure, OperationFailure
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain
from password_reset import create_reset_token_fields
from test_signup_email_verification import load_main
from test_auth_email_verification import request
from test_password_reset import ResetCollectionFake

EMAIL = "buyer@example.com"
PASSWORD = "offline-new-password"


class ResetRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main()
        self.now = datetime.now(timezone.utc)
        self.token, fields = create_reset_token_fields(now=self.now)
        self.original = {"_id": "user", "work_email": EMAIL, "full_name": "Buyer",
            "account_type": "foreign_buyer", "organization": "Company",
            "password_hash": self.module.password_hash.hash("offline-old-password"),
            "email_verified": False, "email_verification_token_hash": "verification-hash", **fields}
        self.collection = ResetCollectionFake(self.original)
        self.module.users_collection = self.collection

    async def reset(self, token=None, password=PASSWORD):
        return await request(self.module.app, "/api/auth/reset-password",
            {"token": self.token if token is None else token, "new_password": password})

    async def test_success_hashes_password_preserves_complete_unrelated_state(self):
        for verified in (True, False, "missing"):
            original = copy.deepcopy(self.original)
            if verified == "missing":
                original.pop("email_verified")
            else:
                original["email_verified"] = verified
            self.collection.document = copy.deepcopy(original)
            status, body = await self.reset()
            self.assertEqual(status, 200)
            self.assertTrue(self.module.password_hash.verify(PASSWORD, self.collection.document["password_hash"]))
            self.assertFalse(self.module.password_hash.verify("offline-old-password", self.collection.document["password_hash"]))
            for key, value in original.items():
                if key != "password_hash" and not key.startswith("password_reset_"):
                    self.assertEqual(self.collection.document[key], value)
            self.assertEqual("email_verified" in self.collection.document, "email_verified" in original)
            self.assertNotIn("password_reset_token_hash", self.collection.document)
            self.assertNotIn("password_reset_expires_at", self.collection.document)
            self.assertEqual(self.collection.document["password_reset_issued_at"], original["password_reset_issued_at"])
            self.assertNotIn(PASSWORD, str(body))
            self.assertNotIn(self.token, str(body))

    async def test_invalid_expired_and_reused_tokens_share_safe_response(self):
        invalid_status, invalid_body = await self.reset(token="A" * 43)
        self.collection.document["password_reset_expires_at"] = self.now - timedelta(seconds=1)
        expired_status, expired_body = await self.reset()
        self.collection.document = copy.deepcopy(self.original)
        self.assertEqual((await self.reset())[0], 200)
        reused_status, reused_body = await self.reset()
        self.assertEqual((invalid_status, expired_status, reused_status), (400, 400, 400))
        self.assertEqual(invalid_body, expired_body)
        self.assertEqual(invalid_body, reused_body)

    async def test_malformed_and_password_validation_never_echo_inputs(self):
        for payload in (None, [], {}, {"token": "private-invalid", "new_password": PASSWORD},
                        {"token": self.token, "new_password": "short"},
                        {"token": self.token, "new_password": "x" * 129},
                        {"token": self.token, "new_password": 123}):
            status, body = await request(self.module.app, "/api/auth/reset-password", payload)
            self.assertIn(status, (400, 422))
            self.assertNotIn(self.token, str(body))
            self.assertNotIn(PASSWORD, str(body))
            self.assertNotIn("private-invalid", str(body))
        self.assertEqual(self.collection.calls, [])
        status, _ = await request(self.module.app, "/api/auth/reset-password", raw=b"bad json")
        self.assertEqual(status, 400)

    async def test_password_length_boundaries(self):
        for length in (8, 128):
            self.collection.document = copy.deepcopy(self.original)
            self.assertEqual((await self.reset(password="x" * length))[0], 200)

    async def test_database_errors_sanitized_and_token_can_retry(self):
        for error in (ConnectionFailure("private database reply"), OperationFailure("private database reply")):
            with patch.object(self.collection, "update_one", new=AsyncMock(side_effect=error)):
                status, body = await self.reset()
            self.assertEqual(status, 503)
            self.assertNotIn("private", str(body))
            self.assertTrue(self.collection.document["password_reset_token_hash"] == self.original["password_reset_token_hash"])
        self.assertEqual((await self.reset())[0], 200)

    async def test_programming_or_hashing_errors_are_not_database_503(self):
        with patch.object(self.module.password_hash, "hash", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                await self.reset()
        with patch.object(self.collection, "update_one", new=AsyncMock(side_effect=RuntimeError("synthetic"))):
            with self.assertRaises(RuntimeError):
                await self.reset()

    async def test_get_does_not_consume_or_change_password(self):
        self.assertEqual((await request(self.module.app, "/api/auth/reset-password", method="GET"))[0], 405)
        self.assertEqual(self.collection.calls, [])

    async def test_reset_does_not_bypass_login_verification(self):
        self.assertEqual((await self.reset())[0], 200)
        self.collection.find_one = AsyncMock(return_value=self.collection.document)
        payload = {"work_email": EMAIL, "password": PASSWORD, "account_type": "foreign_buyer"}
        self.assertEqual((await request(self.module.app, "/api/auth/login", payload))[0], 403)
        self.collection.document["email_verified"] = True
        self.assertEqual((await request(self.module.app, "/api/auth/login", payload))[0], 200)
        payload["password"] = "offline-old-password"
        self.assertEqual((await request(self.module.app, "/api/auth/login", payload))[0], 401)


class ResetRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main()
        self.sender = SimpleNamespace(send_password_reset=AsyncMock())
        self.module.email_sender = self.sender
        self.collection = ResetCollectionFake({"_id": "user", "work_email": EMAIL, "password_hash": "unchanged", "email_verified": False})
        self.module.users_collection = self.collection

    async def test_generic_202_for_registered_unknown_cooldown_and_delivery_outcomes(self):
        expected = {"message": self.module.RESET_REQUEST_MESSAGE}
        for scenario in ("known", "unknown", "cooldown", "failed", "uncertain"):
            self.collection.document = {"_id": "user", "work_email": EMAIL, "password_hash": "unchanged", "email_verified": False}
            self.sender.send_password_reset = AsyncMock()
            if scenario == "unknown":
                self.collection.document = None
            elif scenario == "cooldown":
                self.collection.document["password_reset_issued_at"] = datetime.now(timezone.utc)
            elif scenario == "failed":
                self.sender.send_password_reset.side_effect = EmailDeliveryError("private")
            elif scenario == "uncertain":
                self.sender.send_password_reset.side_effect = EmailSubmissionUncertain("private")
            status, body = await request(self.module.app, "/api/auth/forgot-password", {"work_email": EMAIL.upper()})
            self.assertEqual(status, 202)
            self.assertEqual(body, expected)
            if scenario in ("unknown", "cooldown"):
                self.sender.send_password_reset.assert_not_awaited()
            else:
                self.sender.send_password_reset.assert_awaited_once()
                self.assertFalse(self.collection.document["email_verified"])

    async def test_task_scheduled_without_database_lookup_or_email_submission(self):
        fake_request = SimpleNamespace(json=AsyncMock(return_value={"work_email": EMAIL}))
        tasks = BackgroundTasks()
        body = await self.module.forgot_password(fake_request, tasks)
        self.assertEqual(body, {"message": self.module.RESET_REQUEST_MESSAGE})
        self.assertEqual(self.collection.calls, [])
        self.sender.send_password_reset.assert_not_awaited()
        self.assertEqual(len(tasks.tasks), 1)
        await tasks()
        self.sender.send_password_reset.assert_awaited_once()

    async def test_background_failures_keep_generic_response_and_sanitized_logs(self):
        for error in (ConnectionFailure("private"), OperationFailure("private"), RuntimeError("private")):
            with patch.object(self.collection, "find_one_and_update", new=AsyncMock(side_effect=error)), self.assertLogs("email_delivery", level="WARNING") as logs:
                status, body = await request(self.module.app, "/api/auth/forgot-password", {"work_email": EMAIL})
            self.assertEqual(status, 202)
            self.assertEqual(body, {"message": self.module.RESET_REQUEST_MESSAGE})
            output = " ".join(logs.output)
            self.assertNotIn("private", output)
            self.assertNotIn(EMAIL, output)
            self.assertFalse(any(record.exc_info for record in logs.records))
        self.sender.send_password_reset.assert_not_awaited()

    async def test_invalid_request_never_schedules_database_operations(self):
        for payload in ([], {}, {"work_email": "private-invalid"}, {"work_email": 123}):
            status, body = await request(self.module.app, "/api/auth/forgot-password", payload)
            self.assertIn(status, (400, 422))
            self.assertNotIn("private-invalid", str(body))
        self.assertEqual(self.collection.calls, [])

    async def test_startup_declares_reset_unique_index_and_failure_aborts_safely(self):
        module = load_main()
        async with module.lifespan(module.app):
            pass
        module.users_collection.create_index.assert_any_await(
            "password_reset_token_hash", name=module.RESET_TOKEN_INDEX_NAME, unique=True,
            partialFilterExpression={"password_reset_token_hash": {"$type": "string"}})
        module = load_main()
        module.users_collection.create_index.side_effect = [None, None, OperationFailure("private")]
        with self.assertRaises(RuntimeError) as error:
            async with module.lifespan(module.app):
                self.fail("Startup must abort")
        self.assertNotIn("private", str(error.exception))
        module.client.close.assert_awaited_once()
