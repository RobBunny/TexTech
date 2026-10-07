
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from pymongo.errors import DuplicateKeyError

from database import client, users_collection


password_hash = PasswordHash.recommended()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.admin.command("ping")
    await users_collection.create_index("work_email", unique=True)
    yield
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

    try:
        result = await users_collection.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists"
        )

    return {
        "message": "Registration successful",
        "user_id": str(result.inserted_id),
        "email_verification_required": True
    }


@app.post("/api/auth/login")
async def login(data: LoginData):
    email = str(data.work_email).lower()
    user = await users_collection.find_one({"work_email": email})

    if (
        user is None
        or user["account_type"] != data.account_type
        or not password_hash.verify(data.password, user["password_hash"])
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email, password, or account type"
        )

    return {
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "account_type": user["account_type"],
        "organization": user["organization"],
    }