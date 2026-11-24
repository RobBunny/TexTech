import copy
import importlib.util
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from pymongo.errors import DuplicateKeyError
from email_verification import hash_token
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain


def load_main():
    # Never import database.py: it loads .env and constructs a real client.
    database = ModuleType("database")
    database.client = SimpleNamespace(admin=SimpleNamespace(command=AsyncMock()), close=AsyncMock())
    database.users_collection = SimpleNamespace(create_index=AsyncMock(), insert_one=AsyncMock(), find_one=AsyncMock())
    spec = importlib.util.spec_from_file_location("offline_signup_main", Path(__file__).parents[1] / "main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database}):
        spec.loader.exec_module(module)
    return module


class FakeSender:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    async def send_verification(self, recipient, token):
        self.messages.append((recipient, token))
        if self.fail:
            raise EmailDeliveryError("sensitive SMTP reply " + token)


class StatefulCollectionFake:
    def __init__(self, documents):
        self.documents = copy.deepcopy(documents)
        self.insert_attempts = 0

    async def insert_one(self, document):
        self.insert_attempts += 1
        if any(d["work_email"] == document["work_email"] for d in self.documents):
            raise DuplicateKeyError("duplicate", details={"keyPattern": {"work_email": 1}})
        self.documents.append(copy.deepcopy(document))
        return SimpleNamespace(inserted_id="new-user")

    async def find_one(self, query):
        return next((copy.deepcopy(d) for d in self.documents if d["work_email"] == query["work_email"]), None)


class SignupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = load_main()
        self.app.email_sender = FakeSender()
        self.data = self.app.SignupData(full_name=" Buyer ", work_email="Buyer@example.com", phone="12345678", account_type="foreign_buyer", organization=" Company ", password="long-password")
        self.documents = []

        async def insert(document):
            self.documents.append(copy.deepcopy(document))
            return SimpleNamespace(inserted_id="new-user")
        self.app.users_collection.insert_one.side_effect = insert

    async def test_signup_persists_hash_on_new_user_and_preserves_response(self):
        response = await self.app.register(self.data)
        recipient, token = self.app.email_sender.messages[0]
        doc = self.documents[0]
        self.assertEqual(recipient, "buyer@example.com")
        self.assertEqual(doc["work_email"], recipient)
        self.assertEqual(doc["full_name"], "Buyer")
        self.assertEqual(doc["organization"], "Company")
        self.assertFalse(doc["email_verified"])
        self.assertNotIn(token, doc.values())
        self.assertEqual(doc["email_verification_token_hash"], hash_token(token))
        self.assertEqual(doc["email_verification_expires_at"] - doc["email_verification_issued_at"], timedelta(minutes=30))
        self.assertTrue(self.app.password_hash.verify(self.data.password, doc["password_hash"]))
        self.assertEqual(response["message"], "Registration successful")
        self.assertEqual(response["user_id"], "new-user")
        self.assertTrue(response["email_verification_required"])
        self.assertEqual(response["verification_email_status"], "submitted")
        self.assertNotIn(token, str(response))
        self.app.users_collection.find_one.assert_not_awaited()
        route = next(r for r in self.app.app.routes if getattr(r, "path", None) == "/api/auth/register")
        self.assertEqual(route.status_code, 201)

    async def test_failure_retains_created_account_without_exposing_error(self):
        self.app.email_sender = FakeSender(fail=True)
        response = await self.app.register(self.data)
        self.assertEqual(len(self.documents), 1)
        self.assertFalse(self.documents[0]["email_verified"])
        self.assertEqual(response["message"], "Registration successful")
        self.assertEqual(response["verification_email_status"], "failed")
        self.assertIn("not available yet", response["verification_email_message"])
        self.assertNotIn(self.app.email_sender.messages[0][1], str(response))
        self.assertNotIn("sensitive SMTP", str(response))

    async def test_duplicate_email_does_not_update_existing_account_or_send(self):
        existing = {
            "_id": "original", "full_name": "Original User", "work_email": "buyer@example.com",
            "phone": "99999999", "account_type": "textile_supplier", "organization": "Old Company",
            "password_hash": "old-hash", "email_verified": True, "phone_verified": False,
            "email_verification_token_hash": "old-token-hash", "custom": {"tags": ["preserve"]},
        }
        collection = StatefulCollectionFake([existing])
        before = copy.deepcopy(collection.documents)
        self.app.users_collection = collection
        with self.assertRaises(self.app.HTTPException) as caught:
            await self.app.register(self.data)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(collection.documents, before)
        self.assertEqual(self.app.email_sender.messages, [])
        self.assertEqual(collection.insert_attempts, 1)

    async def test_duplicate_without_key_metadata_checks_existing_email(self):
        self.app.users_collection.insert_one.side_effect = DuplicateKeyError("secret")
        self.app.users_collection.find_one.return_value = {"_id": "existing"}
        with self.assertRaises(self.app.HTTPException) as caught:
            await self.app.register(self.data)
        self.assertEqual(caught.exception.status_code, 409)
        self.app.users_collection.find_one.assert_awaited_once_with({"work_email": "buyer@example.com"})
        self.assertEqual(self.app.email_sender.messages, [])

    async def test_token_collision_retries_new_token(self):
        seen = []
        async def insert(document):
            seen.append(copy.deepcopy(document))
            if len(seen) == 1:
                document["_id"] = "failed-id"
                raise DuplicateKeyError("secret", details={"keyPattern": {"email_verification_token_hash": 1}})
            return SimpleNamespace(inserted_id="new-user")
        self.app.users_collection.insert_one.side_effect = insert
        response = await self.app.register(self.data)
        self.assertEqual(response["verification_email_status"], "submitted")
        self.assertNotEqual(seen[0]["email_verification_token_hash"], seen[1]["email_verification_token_hash"])
        self.assertNotIn("_id", seen[1])
        self.assertEqual(hash_token(self.app.email_sender.messages[0][1]), seen[1]["email_verification_token_hash"])

    async def test_collision_retries_are_bounded(self):
        self.app.users_collection.insert_one.side_effect = DuplicateKeyError("secret", details={"keyPattern": {"email_verification_token_hash": 1}})
        with self.assertRaises(self.app.HTTPException) as caught:
            await self.app.register(self.data)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.app.users_collection.insert_one.await_count, 3)
        self.assertEqual(self.app.email_sender.messages, [])

    async def test_insert_failure_never_sends_email(self):
        self.app.users_collection.insert_one.side_effect = RuntimeError("offline DB failure")
        with self.assertRaises(RuntimeError):
            await self.app.register(self.data)
        self.assertEqual(self.app.email_sender.messages, [])

    async def test_startup_declares_partial_unique_index(self):
        async with self.app.lifespan(self.app.app):
            pass
        self.app.users_collection.create_index.assert_any_await("work_email", unique=True)
        self.app.users_collection.create_index.assert_any_await(
            "email_verification_token_hash", name=self.app.TOKEN_INDEX_NAME, unique=True,
            partialFilterExpression={"email_verification_token_hash": {"$type": "string"}},
        )
        self.app.client.close.assert_awaited_once()

    async def test_index_failure_aborts_startup_safely(self):
        self.app.users_collection.create_index.side_effect = [None, RuntimeError("secret provider data")]
        with self.assertRaisesRegex(RuntimeError, "uniqueness index initialization failed") as caught:
            async with self.app.lifespan(self.app.app):
                self.fail("Startup must not complete")
        self.assertNotIn("secret provider data", str(caught.exception))
        self.app.client.close.assert_awaited_once()

    async def test_uncertain_delivery_retains_unverified_account(self):
        self.app.email_sender = SimpleNamespace(send_verification=AsyncMock(side_effect=EmailSubmissionUncertain("private reply")))
        response = await self.app.register(self.data)
        self.assertEqual(response["verification_email_status"], "uncertain")
        self.assertEqual(response["message"], "Registration successful")
        self.assertTrue(response["email_verification_required"])
        self.assertFalse(self.documents[0]["email_verified"])
        self.assertIn("may still arrive", response["verification_email_message"])
        self.assertNotIn("private reply", str(response))

    async def test_unexpected_sender_error_is_not_claimed_as_confirmed_failure(self):
        self.app.email_sender = SimpleNamespace(send_verification=AsyncMock(side_effect=RuntimeError("private reply")))
        response = await self.app.register(self.data)
        self.assertEqual(response["verification_email_status"], "uncertain")
        self.assertFalse(self.documents[0]["email_verified"])
        self.assertNotIn("private reply", str(response))
