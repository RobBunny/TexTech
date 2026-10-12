import os
import smtplib
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from email_delivery import EmailSubmissionUncertain, EmailDeliveryError, SMTPConfig, SMTPEmailSender, verification_link

ENV = {"SMTP_HOST": "smtp.invalid", "SMTP_PORT": "587", "SMTP_USERNAME": "example-user", "SMTP_PASSWORD": "test-secret", "SMTP_FROM_ADDRESS": "sender@example.com", "SMTP_FROM_NAME": "TexTech", "SMTP_TLS_MODE": "starttls"}
TOKEN = "A" * 43


class ConfigTests(unittest.TestCase):
    def test_default_frontend_and_fragment(self):
        with patch.dict(os.environ, ENV, clear=True):
            config = SMTPConfig.from_environment()
        self.assertEqual(config.frontend_url, "http://localhost:5173")
        link = urlsplit(verification_link(config.frontend_url, TOKEN))
        self.assertEqual(link.query, "")
        self.assertEqual(link.fragment, "verify-email=" + TOKEN)
        self.assertNotIn("test-secret", repr(config))

    def test_bad_config_is_safe(self):
        for extra in ({"SMTP_PORT": "secret-bad-port"}, {"SMTP_TLS_MODE": "bad"}, {"SMTP_HOST": ""}, {"FRONTEND_BASE_URL": "https://user:secret@example.com"}, {"FRONTEND_BASE_URL": "https://example.com/?query=1"}, {"SMTP_FROM_NAME": "bad\nheader"}):
            with patch.dict(os.environ, {**ENV, **extra}, clear=True):
                with self.assertRaises(EmailDeliveryError) as caught:
                    SMTPConfig.from_environment()
                self.assertNotIn("secret", str(caught.exception))


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_tls_modes_message_and_submission(self):
        for mode in ("starttls", "ssl", "none"):
            with patch.dict(os.environ, {**ENV, "SMTP_TLS_MODE": mode}, clear=True), patch("email_delivery.smtplib.SMTP") as plain, patch("email_delivery.smtplib.SMTP_SSL") as secure:
                factory = secure if mode == "ssl" else plain
                smtp = factory.return_value.__enter__.return_value
                smtp.send_message.return_value = {}
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
                message = smtp.send_message.call_args.args[0]
                self.assertEqual(message["To"], "buyer@example.com")
                self.assertIn("http://localhost:5173/#verify-email=" + TOKEN, message.get_content())
                smtp.login.assert_called_once_with("example-user", "test-secret")
                self.assertEqual(smtp.starttls.call_count, int(mode == "starttls"))
                factory.assert_called_once()
                self.assertEqual(factory.call_args.kwargs["timeout"], 10)
                (plain if mode == "ssl" else secure).assert_not_called()

    async def test_recipient_refusal_is_failure(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
            factory.return_value.__enter__.return_value.send_message.return_value = {"buyer@example.com": (550, b"private reply")}
            with self.assertRaises(EmailDeliveryError) as caught:
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assertNotIn("private reply", str(caught.exception))
            self.assertNotIn(TOKEN, str(caught.exception))

    async def test_provider_failure_is_sanitized(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP", side_effect=smtplib.SMTPException("test-secret " + TOKEN)):
            with self.assertRaises(EmailDeliveryError) as caught:
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assertNotIn("test-secret", str(caught.exception))
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    async def test_missing_configuration_never_connects(self):
        with patch.dict(os.environ, {}, clear=True), patch("email_delivery.smtplib.SMTP") as plain, patch("email_delivery.smtplib.SMTP_SSL") as secure:
            with self.assertRaises(EmailDeliveryError):
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            plain.assert_not_called()
            secure.assert_not_called()

    async def test_acceptance_survives_quit_failure(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            factory.return_value.__exit__.side_effect = smtplib.SMTPResponseException(500, b"private QUIT failure")
            await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            smtp.send_message.assert_called_once()
            factory.return_value.__exit__.assert_called_once()

    async def test_lost_acceptance_confirmation_is_uncertain(self):
        for error in (smtplib.SMTPServerDisconnected("private " + TOKEN), TimeoutError("private " + TOKEN)):
            with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
                smtp = factory.return_value.__enter__.return_value
                smtp.send_message.side_effect = error
                with self.assertRaises(EmailSubmissionUncertain) as caught:
                    await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertNotIn("private", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    async def test_explicit_rejection_remains_failure_despite_quit_error(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.side_effect = smtplib.SMTPDataError(550, b"private rejection")
            factory.return_value.__exit__.side_effect = TimeoutError("private cleanup")
            with self.assertRaises(EmailDeliveryError) as caught:
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assertNotIsInstance(caught.exception, EmailSubmissionUncertain)
            self.assertNotIn("private", str(caught.exception))

    async def test_connection_failure_before_send_is_confirmed_failure(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP", side_effect=ConnectionError("private")):
            with self.assertRaises(EmailDeliveryError) as caught:
                await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assertNotIsInstance(caught.exception, EmailSubmissionUncertain)


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def assert_safe_record(self, record, stage, exception_name, outcome, code=None):
        self.assertEqual(record.getMessage(), f"stage={stage} exception={exception_name} smtp_code={code} outcome={outcome}")
        self.assertFalse(record.exc_info)
        self.assertIsNone(record.stack_info)
        for secret in (TOKEN, "test-secret", "buyer@example.com", "sender@example.com", "smtp.invalid", "private"):
            self.assertNotIn(secret, record.getMessage())
        self.assertTrue(all(not isinstance(arg, BaseException) for arg in record.args))

    async def test_configuration_failure_logs_no_values(self):
        with patch.dict(os.environ, {**ENV, "SMTP_PORT": "private test-secret"}, clear=True):
            with self.assertLogs("email_delivery", level="WARNING") as logs:
                with self.assertRaises(EmailDeliveryError):
                    await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
        self.assertEqual(len(logs.records), 1)
        self.assert_safe_record(logs.records[0], "configuration", "ValueError", "failed")

    async def test_connection_tls_and_authentication_diagnostics(self):
        for stage, error in (("connection", ConnectionError("private")), ("tls", smtplib.SMTPResponseException(454, b"private")), ("authentication", smtplib.SMTPAuthenticationError(535, b"private test-secret"))):
            with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
                smtp = factory.return_value.__enter__.return_value
                if stage == "connection":
                    factory.side_effect = error
                elif stage == "tls":
                    smtp.starttls.side_effect = error
                else:
                    smtp.login.side_effect = error
                with self.assertLogs("email_delivery", level="WARNING") as logs:
                    with self.assertRaises(EmailDeliveryError):
                        await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
                self.assertEqual(len(logs.records), 1)
                self.assert_safe_record(logs.records[0], stage, type(error).__name__, "failed", getattr(error, "smtp_code", None))

    async def test_uncertain_submission_logs_original_exception(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
            factory.return_value.__enter__.return_value.send_message.side_effect = smtplib.SMTPServerDisconnected("private " + TOKEN)
            factory.return_value.__exit__.side_effect = TimeoutError("private cleanup")
            with self.assertLogs("email_delivery", level="WARNING") as logs:
                with self.assertRaises(EmailSubmissionUncertain):
                    await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assertEqual(len(logs.records), 1)
            self.assert_safe_record(logs.records[0], "submission", "SMTPServerDisconnected", "uncertain")

    async def test_confirmed_rejections_log_numeric_code_only(self):
        for raised in (False, True):
            with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
                smtp = factory.return_value.__enter__.return_value
                if raised:
                    smtp.send_message.side_effect = smtplib.SMTPDataError(550, b"private " + TOKEN.encode())
                    factory.return_value.__exit__.side_effect = TimeoutError("private cleanup")
                else:
                    smtp.send_message.return_value = {"buyer@example.com": (550, b"private")}
                with self.assertLogs("email_delivery", level="WARNING") as logs:
                    with self.assertRaises(EmailDeliveryError) as caught:
                        await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
                self.assertNotIsInstance(caught.exception, EmailSubmissionUncertain)
                self.assertEqual(len(logs.records), 1)
                self.assert_safe_record(logs.records[0], "submission", "SMTPDataError" if raised else "SMTPRecipientsRefused", "failed", 550)

    async def test_acceptance_and_cleanup_failure_emit_no_failure_log(self):
        for cleanup_fails in (False, True):
            with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
                factory.return_value.__enter__.return_value.send_message.return_value = {}
                if cleanup_fails:
                    factory.return_value.__exit__.side_effect = smtplib.SMTPResponseException(500, b"private")
                with self.assertNoLogs("email_delivery", level="WARNING"):
                    await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)

    async def test_non_numeric_provider_status_is_not_logged(self):
        with patch.dict(os.environ, ENV, clear=True), patch("email_delivery.smtplib.SMTP") as factory:
            factory.return_value.__enter__.return_value.send_message.side_effect = smtplib.SMTPDataError("private test-secret", b"private")
            with self.assertLogs("email_delivery", level="WARNING") as logs:
                with self.assertRaises(EmailDeliveryError):
                    await SMTPEmailSender().send_verification("buyer@example.com", TOKEN)
            self.assert_safe_record(logs.records[0], "submission", "SMTPDataError", "failed")
