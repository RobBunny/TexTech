"""HTTP tests through an in-process ASGI harness; no sockets or real database."""
import asyncio
import base64
import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from bson import ObjectId
from pymongo.errors import ConnectionFailure, OperationFailure
from email_verification import create_token_fields
from test_signup_email_verification import load_main
from test_email_verification import AtomicCollectionFake


async def request(app, path, payload=None, *, method="POST", raw=None, headers=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    events = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(event):
        events.append(event)

    request_headers = [(b"content-type", b"application/json")]
    request_headers.extend(
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    )
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "headers": request_headers,
             "client": ("127.0.0.1", 1), "server": ("offline", 80)}
    await app(scope, receive, send)
    status = next(e["status"] for e in events if e["type"] == "http.response.start")
    content = b"".join(e.get("body", b"") for e in events if e["type"] == "http.response.body")
    return status, json.loads(content)


class VerificationRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main()
        self.now = datetime.now(timezone.utc)
        self.token, self.fields = create_token_fields(now=self.now)
        self.collection = AtomicCollectionFake({"_id": "user", "email_verified": False, **self.fields})
        self.collection.find_one = AsyncMock(side_effect=AssertionError("No preliminary read"))
        self.module.users_collection = self.collection

    async def test_success_consumes_token_without_read(self):
        status, body = await request(self.module.app, "/api/auth/verify-email", {"token": self.token})
        self.assertEqual((status, body), (200, {"message": "Email verified successfully"}))
        self.assertTrue(self.collection.document["email_verified"])
        self.assertTrue(all(k not in self.collection.document for k in self.fields))
        self.collection.find_one.assert_not_awaited()

    async def test_invalid_expired_and_already_verified_share_response(self):
        for override, token in (({}, "A" * 43),
                                ({"email_verification_expires_at": self.now - timedelta(seconds=1)}, self.token),
                                ({"email_verified": True}, self.token)):
            self.collection.document = {"email_verified": False, **self.fields, **override}
            before = copy.deepcopy(self.collection.document)
            self.assertEqual(await request(self.module.app, "/api/auth/verify-email", {"token": token}),
                             (400, {"detail": "Invalid or expired verification token"}))
            self.assertEqual(self.collection.document, before)

    async def test_reuse_is_invalid(self):
        self.assertEqual((await request(self.module.app, "/api/auth/verify-email", {"token": self.token}))[0], 200)
        self.assertEqual(await request(self.module.app, "/api/auth/verify-email", {"token": self.token}),
                         (400, {"detail": "Invalid or expired verification token"}))

    async def test_malformed_requests_never_echo_input(self):
        self.module.users_collection = SimpleNamespace(update_one=AsyncMock())
        for payload in (None, [], {}, {"token": None}, {"token": 123}, {"token": "secret-malformed"}, {"token": "é" * 43}):
            self.assertEqual(await request(self.module.app, "/api/auth/verify-email", payload),
                             (400, {"detail": "Invalid or expired verification token"}))
        self.assertEqual((await request(self.module.app, "/api/auth/verify-email", raw=b'{"token":"secret"'))[0], 400)
        self.module.users_collection.update_one.assert_not_awaited()

    async def test_get_does_not_consume_token(self):
        before = copy.deepcopy(self.collection.document)
        self.assertEqual((await request(self.module.app, "/api/auth/verify-email", {"token": self.token}, method="GET"))[0], 405)
        self.assertEqual(self.collection.document, before)

    async def test_database_failures_are_sanitized(self):
        for error in (ConnectionFailure("secret " + self.token), OperationFailure("secret " + self.token)):
            self.module.users_collection = SimpleNamespace(update_one=AsyncMock(side_effect=error))
            self.assertEqual(await request(self.module.app, "/api/auth/verify-email", {"token": self.token}),
                             (503, {"detail": "Email verification temporarily unavailable"}))

    async def test_programming_error_is_not_misclassified(self):
        self.module.users_collection = SimpleNamespace(update_one=AsyncMock(side_effect=TypeError("bug")))
        with self.assertRaisesRegex(TypeError, "bug"):
            await request(self.module.app, "/api/auth/verify-email", {"token": self.token})

    async def test_concurrent_requests_have_one_success(self):
        results = await asyncio.gather(*(request(self.module.app, "/api/auth/verify-email", {"token": self.token}) for _ in range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 400])


class AdminPortfolioAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        admin_emails = patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.com"})
        admin_emails.start()
        self.addCleanup(admin_emails.stop)
        self.module = load_main()
        self.password = "admin-password"
        self.module.users_collection.find_one = AsyncMock(return_value={
            "work_email": "admin@example.com",
            "account_type": "admin_authority",
            "email_verified": True,
            "password_hash": self.module.password_hash.hash(self.password),
        })
        cursor = SimpleNamespace(sort=Mock(), to_list=AsyncMock(return_value=[]))
        cursor.sort.return_value = cursor
        self.module.portfolios_collection = SimpleNamespace(find=Mock(return_value=cursor))
        registration_cursor = SimpleNamespace(sort=Mock(), to_list=AsyncMock(return_value=[]))
        registration_cursor.sort.return_value = registration_cursor
        self.module.users_collection.find = Mock(return_value=registration_cursor)
        token = base64.b64encode(f"admin@example.com:{self.password}".encode()).decode()
        self.headers = {"authorization": f"Basic {token}"}

    async def test_verified_admin_can_open_directory(self):
        self.assertEqual(
            await request(
                self.module.app,
                "/api/admin/portfolios",
                method="GET",
                headers=self.headers,
            ),
            (200, []),
        )

    async def test_non_admin_account_is_rejected(self):
        self.module.users_collection.find_one.return_value["account_type"] = "buying_house"
        self.assertEqual(
            await request(
                self.module.app,
                "/api/admin/portfolios",
                method="GET",
                headers=self.headers,
            ),
            (401, {"detail": "Incorrect admin credentials"}),
        )

    async def test_unverified_admin_account_is_rejected(self):
        self.module.users_collection.find_one.return_value["email_verified"] = False
        self.assertEqual(
            await request(
                self.module.app,
                "/api/admin/portfolios",
                method="GET",
                headers=self.headers,
            ),
            (401, {"detail": "Incorrect admin credentials"}),
        )

    async def test_admin_can_list_verified_registrations_waiting_for_approval(self):
        created_at = datetime.now(timezone.utc)
        self.module.users_collection.find.return_value.to_list.return_value = [{
            "_id": ObjectId(),
            "full_name": "Buyer",
            "work_email": "buyer@example.com",
            "phone": "12345678",
            "organization": "Buyer Company",
            "account_type": "foreign_buyer",
            "created_at": created_at,
        }]

        status, registrations = await request(
            self.module.app,
            "/api/admin/registrations",
            method="GET",
            headers=self.headers,
        )

        self.assertEqual(status, 200)
        self.assertEqual(registrations[0]["work_email"], "buyer@example.com")
        self.assertEqual(registrations[0]["created_at"], created_at.isoformat())
        self.assertNotIn("password_hash", registrations[0])

    async def test_admin_can_approve_a_verified_registration(self):
        user_id = ObjectId()
        self.module.users_collection.find_one_and_update = AsyncMock(
            return_value={"_id": user_id, "approval_status": "approved"}
        )

        self.assertEqual(
            await request(
                self.module.app,
                f"/api/admin/registrations/{user_id}/approve",
                headers=self.headers,
            ),
            (200, {"message": "Registration approved", "user_id": str(user_id)}),
        )


class LoginEnforcementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main()
        self.payload = {"work_email": "buyer@example.com", "password": "long-password", "account_type": "foreign_buyer"}
        self.user = {"_id": "user", "full_name": "Buyer", "organization": "Company", "account_type": "foreign_buyer",
                     "password_hash": self.module.password_hash.hash("long-password"), "email_verified": True,
                     "approval_status": "approved"}
        self.module.users_collection.find_one.return_value = self.user

    async def test_verified_login_preserves_response(self):
        self.assertEqual(await request(self.module.app, "/api/auth/login", self.payload),
                         (200, {"user_id": "user", "full_name": "Buyer", "account_type": "foreign_buyer", "organization": "Company"}))

    async def test_false_missing_and_non_boolean_flags_are_blocked_without_mutation(self):
        for flag in (False, None, 1, "true", "missing"):
            self.user["email_verified"] = flag
            if flag == "missing":
                self.user.pop("email_verified")
            before = copy.deepcopy(self.user)
            self.assertEqual(await request(self.module.app, "/api/auth/login", self.payload),
                             (403, {"detail": "Email verification required before login"}))
            self.assertEqual(self.user, before)

    async def test_verified_but_pending_registration_cannot_log_in(self):
        self.user["approval_status"] = "pending"
        self.assertEqual(
            await request(self.module.app, "/api/auth/login", self.payload),
            (403, {"detail": "Admin approval required before login"}),
        )

    async def test_bad_credentials_do_not_disclose_verification_status(self):
        self.user["email_verified"] = False
        for overrides in ({"password": "wrong"}, {"account_type": "buying_house"}):
            self.assertEqual(await request(self.module.app, "/api/auth/login", {**self.payload, **overrides}),
                             (401, {"detail": "Invalid email, password, or account type"}))
        self.module.users_collection.find_one.return_value = None
        self.assertEqual((await request(self.module.app, "/api/auth/login", self.payload))[0], 401)

    async def test_database_failures_are_sanitized(self):
        for error in (ConnectionFailure("secret"), OperationFailure("secret")):
            self.module.users_collection.find_one.side_effect = error
            self.assertEqual(await request(self.module.app, "/api/auth/login", self.payload),
                             (503, {"detail": "Login temporarily unavailable"}))

    async def test_programming_error_is_not_misclassified(self):
        self.module.users_collection.find_one.side_effect = TypeError("bug")
        with self.assertRaisesRegex(TypeError, "bug"):
            await request(self.module.app, "/api/auth/login", self.payload)
