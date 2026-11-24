
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError
from pwdlib import PasswordHash
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure

from database import client, users_collection
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain, SMTPEmailSender, _log_failure
from email_verification import create_token_fields, verify_email, TOKEN_PATTERN
from password_reset import issue_password_reset, reset_password, TOKEN_INDEX_NAME as RESET_TOKEN_INDEX_NAME


password_hash = PasswordHash.recommended()
email_sender = SMTPEmailSender()
TOKEN_INDEX_NAME = "unique_email_verification_token_hash"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await client.admin.command("ping")
        await users_collection.create_index("work_email", unique=True)
        try:
            await users_collection.create_index(
                "email_verification_token_hash",
                name=TOKEN_INDEX_NAME,
                unique=True,
                partialFilterExpression={"email_verification_token_hash": {"$type": "string"}},
            )
        except Exception:
            raise RuntimeError(
                "Verification token uniqueness index initialization failed; API startup aborted"
            ) from None
        try:
            await users_collection.create_index(
                "password_reset_token_hash", name=RESET_TOKEN_INDEX_NAME, unique=True,
                partialFilterExpression={"password_reset_token_hash": {"$type": "string"}},
            )
        except Exception:
            raise RuntimeError("Password reset token uniqueness index initialization failed; API startup aborted") from None
        yield
    finally:
        await client.close()


app = FastAPI(title="TexTech API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignupData(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    work_email: EmailStr
    phone: str = Field(min_length=6, max_length=20)
    account_type: Literal[
        "foreign_buyer",
        "buying_house",
        "textile_supplier",
        "admin_authority",
    ]
    organization: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8, max_length=128)


class LoginData(BaseModel):
    work_email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    account_type: Literal[
        "foreign_buyer",
        "buying_house",
        "textile_supplier",
        "admin_authority",
    ]


@app.get("/")
async def home():
    return {"message": "Welcome to TexTech API"}


@app.get("/health")
async def health():
    await client.admin.command("ping")
    return {"status": "ok", "database": "connected"}


@app.post("/api/auth/register", status_code=201)
async def register(data: SignupData):
    email = str(data.work_email).lower()

    user = {
        "full_name": data.full_name.strip(),
        "work_email": email,
        "phone": data.phone.strip(),
        "account_type": data.account_type,
        "organization": data.organization.strip(),
        "password_hash": password_hash.hash(data.password),
        "email_verified": False,
        "phone_verified": False,
    }

    for attempt in range(3):
        token, fields = create_token_fields()
        user.update(fields)
        try:
            result = await users_collection.insert_one(user)
            break
        except DuplicateKeyError as error:
            # Inspect structured key metadata, never expose provider error text.
            key_pattern = (error.details or {}).get("keyPattern", {})
            if key_pattern == {"email_verification_token_hash": 1}:
                if attempt < 2:
                    # insert_one may have assigned an _id before the rejected write.
                    user.pop("_id", None)
                    continue
                raise HTTPException(status_code=503, detail="Registration temporarily unavailable") from None
            if "work_email" in key_pattern or await users_collection.find_one({"work_email": email}):
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists",
                ) from None
            raise HTTPException(status_code=503, detail="Registration temporarily unavailable") from None

    delivery_status = "submitted"
    delivery_message = "Verification email submitted. Check your inbox."
    try:
        await email_sender.send_verification(email, token)
    except EmailSubmissionUncertain:
        delivery_status = "uncertain"
        delivery_message = (
            "Your account was created, but email submission could not be confirmed. "
            "The email may still arrive; check your inbox. Do not register again. "
            "A resend feature is not available yet."
        )
    except EmailDeliveryError:
        delivery_status = "failed"
        delivery_message = (
            "Your account was created, but the verification email could not be submitted. "
            "Do not register again. A resend feature is not available yet; "
            "you will need to request a new link once it is available."
        )

    except Exception:
        delivery_status = "uncertain"
        delivery_message = (
            "Your account was created, but email submission could not be confirmed. "
            "The email may still arrive; check your inbox. Do not register again. "
            "A resend feature is not available yet."
        )

    return {
        "message": "Registration successful",
        "user_id": str(result.inserted_id),
        "email_verification_required": True,
        "verification_email_status": delivery_status,
        "verification_email_message": delivery_message,
    }


@app.post("/api/auth/verify-email")
async def verify_email_endpoint(request: Request):
    # Parse manually so validation errors never echo a secret token.
    invalid_detail = "Invalid or expired verification token"
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail=invalid_detail) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
        raise HTTPException(status_code=400, detail=invalid_detail)
    try:
        verified = await verify_email(users_collection, payload["token"])
    except (ConnectionFailure, OperationFailure):
        raise HTTPException(
            status_code=503, detail="Email verification temporarily unavailable"
        ) from None
    if not verified:
        raise HTTPException(status_code=400, detail=invalid_detail)
    return {"message": "Email verified successfully"}


@app.post("/api/auth/login")
async def login(data: LoginData):
    email = str(data.work_email).lower()
    try:
        user = await users_collection.find_one({"work_email": email})
    except (ConnectionFailure, OperationFailure):
        raise HTTPException(status_code=503, detail="Login temporarily unavailable") from None

    if (
        user is None
        or user["account_type"] != data.account_type
        or not password_hash.verify(data.password, user["password_hash"])
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email, password, or account type"
        )

    if user.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="Email verification required before login")

    return {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "account_type": user["account_type"],
        "organization": user["organization"],
    }

RESET_REQUEST_MESSAGE = "If an account exists for this email, a password-reset link may arrive. Check your inbox and spam folder."


async def send_password_reset_background(email):
    try:
        await issue_password_reset(users_collection, email, email_sender)
    except EmailSubmissionUncertain:
        pass  # SMTP adapter already emits sanitized diagnostics.
    except EmailDeliveryError:
        pass
    except (ConnectionFailure, OperationFailure) as error:
        _log_failure("reset_database", error, "failed")
    except Exception as error:
        # Background failures must never emit raw exception text or a traceback.
        _log_failure("reset_background", error, "failed")


async def read_reset_payload(request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid request") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid request")
    return payload


@app.post("/api/auth/forgot-password", status_code=202)
async def forgot_password(request: Request, background_tasks: BackgroundTasks):
    payload = await read_reset_payload(request)
    try:
        email = str(TypeAdapter(EmailStr).validate_python(payload.get("work_email"))).lower()
    except ValidationError:
        raise HTTPException(status_code=422, detail="Enter a valid work email address") from None
    # Schedule the same task for every valid input; no account lookup or SMTP wait
    # occurs before this generic response is returned.
    background_tasks.add_task(send_password_reset_background, email)
    return {"message": RESET_REQUEST_MESSAGE}


@app.post("/api/auth/reset-password")
async def reset_password_endpoint(request: Request):
    payload = await read_reset_payload(request)
    token = payload.get("token")
    invalid_detail = "Invalid or expired password reset token"
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        raise HTTPException(status_code=400, detail=invalid_detail)
    new_password = payload.get("new_password")
    if not isinstance(new_password, str) or not 8 <= len(new_password) <= 128:
        raise HTTPException(status_code=422, detail="Password must contain 8 to 128 characters")
    # Keep password hashing errors outside the database-failure boundary.
    new_hash = password_hash.hash(new_password)
    try:
        changed = await reset_password(users_collection, token, new_hash)
    except (ConnectionFailure, OperationFailure):
        raise HTTPException(status_code=503, detail="Password reset temporarily unavailable") from None
    if not changed:
        raise HTTPException(status_code=400, detail=invalid_detail)
    return {"message": "Password reset successfully. Log in with your new password; email verification is still required."}
