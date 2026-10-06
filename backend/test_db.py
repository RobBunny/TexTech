
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import AsyncMongoClient

load_dotenv(Path(__file__).with_name(".env"))

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "textech")


async def test_connection():
    if not MONGODB_URI:
        print("ERROR: MONGODB_URI is missing from .env")
        return

    client = AsyncMongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=5000
    )

    try:
        await client.admin.command("ping")
        print("SUCCESS: MongoDB connected!")
        print("Database name:", DATABASE_NAME)
    except Exception as e:
        print("ERROR: MongoDB connection failed.")
        print(type(e).__name__, str(e))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_connection())