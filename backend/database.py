
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import AsyncMongoClient

load_dotenv(Path(__file__).with_name(".env"))

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "textech")

if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is missing from backend/.env")

client = AsyncMongoClient(MONGODB_URI)
db = client[DATABASE_NAME]

users_collection = db["users"]