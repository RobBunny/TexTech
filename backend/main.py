
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure

from database import client, users_collection
from email_delivery import EmailDeliveryError, EmailSubmissionUncertain, SMTPEmailSender
from email_verification import create_token_fields, verify_email


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