"""Configurable SMTP delivery. Importing this module never opens a connection."""
import asyncio
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit, urlunsplit


logger = logging.getLogger(__name__)


def _log_failure(stage, error, outcome, status_code=None):
    # Never pass the exception object/text, provider replies, or traceback to logging.
    if status_code is None:
        status_code = getattr(error, "smtp_code", None)
    if type(status_code) is not int or not 100 <= status_code <= 599:
        status_code = None
    logger.warning(
        "stage=%s exception=%s smtp_code=%s outcome=%s",
        stage, type(error).__name__, status_code, outcome,
        exc_info=False, stack_info=False,
    )


class EmailDeliveryError(Exception):
    """Safe delivery error without provider details or secrets."""


class EmailSubmissionUncertain(EmailDeliveryError):
    """The server may have accepted the message; confirmation was lost."""


@dataclass(frozen=True, repr=False)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    sender_address: str
    sender_name: str
    tls_mode: str
    frontend_url: str

    @classmethod
    def from_environment(cls):
        try:
            config = cls(
                host=os.environ.get("SMTP_HOST", ""),
                port=int(os.environ.get("SMTP_PORT", "587")),
                username=os.environ.get("SMTP_USERNAME", ""),
                password=os.environ.get("SMTP_PASSWORD", ""),
                sender_address=os.environ.get("SMTP_FROM_ADDRESS", ""),
                sender_name=os.environ.get("SMTP_FROM_NAME", "TexTech"),
                tls_mode=os.environ.get("SMTP_TLS_MODE", "starttls").lower(),
                frontend_url=os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173"),
            )
            url = urlsplit(config.frontend_url)
            if (not config.host or not config.sender_address
                    or not 1 <= config.port <= 65535
                    or config.tls_mode not in ("starttls", "ssl", "none")
                    or bool(config.username) != bool(config.password)
                    or url.scheme not in ("http", "https") or not url.hostname
                    or url.username or url.password or url.query or url.fragment
                    or any(c in config.sender_address + config.sender_name + config.host + config.frontend_url for c in "\r\n")):
                raise ValueError("Invalid configuration")
            return config
        except (ValueError, TypeError) as error:
            _log_failure("configuration", error, "failed")
            raise EmailDeliveryError("Email delivery configuration is invalid or missing") from None


def verification_link(frontend_url, token):
    url = urlsplit(frontend_url)
    return urlunsplit((url.scheme, url.netloc, url.path or "/", "", "verify-email=" + token))


def password_reset_link(frontend_url, token):
    url = urlsplit(frontend_url)
    return urlunsplit((url.scheme, url.netloc, url.path or "/", "", "reset-password=" + token))


class SMTPEmailSender:
    async def send_verification(self, recipient, token):
        try:
            config = SMTPConfig.from_environment()
            await asyncio.to_thread(self._send, config, recipient, token)
        except EmailSubmissionUncertain:
            raise EmailSubmissionUncertain("Verification email submission could not be confirmed") from None
        except EmailDeliveryError:
            raise EmailDeliveryError("Verification email could not be submitted") from None
        except Exception as error:
            _log_failure("dispatch", error, "failed")
            # Do not propagate SMTP replies, configuration values, or message bodies.
            raise EmailDeliveryError("Verification email could not be submitted") from None

    async def send_password_reset(self, recipient, token):
        try:
            config = SMTPConfig.from_environment()
            await asyncio.to_thread(self._send, config, recipient, token, purpose="password_reset")
        except EmailSubmissionUncertain:
            raise EmailSubmissionUncertain("Password reset email submission could not be confirmed") from None
        except EmailDeliveryError:
            raise EmailDeliveryError("Password reset email could not be submitted") from None
        except Exception as error:
            _log_failure("dispatch", error, "failed")
            raise EmailDeliveryError("Password reset email could not be submitted") from None

    @staticmethod
    def _send(config, recipient, token, *, purpose="verification"):
        stage = "message"
        outcome = "failed"
        primary_error = None
        primary_stage = None
        refusal_code = None
        try:
            message = EmailMessage()
            message["From"] = formataddr((config.sender_name, config.sender_address))
            message["To"] = recipient
            if purpose == "password_reset":
                message["Subject"] = "Reset your TexTech password"
                message.set_content(
                    "Choose a new password using this link:\n"
                    + password_reset_link(config.frontend_url, token)
                    + "\n\nThis link expires 30 minutes after it was issued."
                    + "\nIf you did not request this, you can ignore this email."
                )
            else:
                message["Subject"] = "Verify your TexTech email"
                message.set_content(
                    "Confirm your email address using this link:\n"
                    + verification_link(config.frontend_url, token)
                    + "\n\nThis link expires 30 minutes after this verification link was issued."
                )
            stage = "tls"
            context = ssl.create_default_context()
            stage = "connection"
            if config.tls_mode == "ssl":
                connection = smtplib.SMTP_SSL(config.host, config.port, timeout=10, context=context)
            else:
                connection = smtplib.SMTP(config.host, config.port, timeout=10)
            with connection as smtp:
                try:
                    if config.tls_mode == "starttls":
                        stage = "tls"
                        smtp.ehlo()
                        smtp.starttls(context=context)
                        smtp.ehlo()
                    if config.username:
                        stage = "authentication"
                        smtp.login(config.username, config.password)
                    stage = "submission"
                    outcome = "uncertain"
                    try:
                        refused = smtp.send_message(message)
                    except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused):
                        outcome = "failed"
                        raise
                    outcome = "failed" if refused else "submitted"
                    if refused:
                        primary_error = smtplib.SMTPRecipientsRefused(refused)
                        primary_stage = "submission"
                        refusal_code = next(iter(refused.values()))[0]
                    stage = "cleanup"
                except Exception as error:
                    # Preserve the actual failure if __exit__/QUIT replaces it.
                    primary_error = error
                    primary_stage = stage
                    raise
        except Exception as error:
            if outcome == "submitted":
                return  # Cleanup cannot undo confirmed acceptance; no failure log.
            diagnostic_error = primary_error if primary_error is not None else error
            if isinstance(diagnostic_error, smtplib.SMTPRecipientsRefused) and refusal_code is None:
                refusal_code = next(iter(diagnostic_error.recipients.values()), (None,))[0]
            _log_failure(primary_stage or stage, diagnostic_error, outcome, refusal_code)
            if outcome == "uncertain":
                raise EmailSubmissionUncertain("Verification email submission could not be confirmed") from None
            raise EmailDeliveryError("Verification email could not be submitted") from None
        if outcome == "failed":
            _log_failure("submission", primary_error, "failed", refusal_code)
            raise EmailDeliveryError("Verification email could not be submitted") from None
