import os

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Load local .env when running locally.
# In ECS, environment variables supplied by the task definition
# are already available and are not overwritten by default.
load_dotenv()


# ------------------------------------------------------------
# Database configuration
# ------------------------------------------------------------

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")


# ------------------------------------------------------------
# Validate required database environment variables
# ------------------------------------------------------------

required_variables = {
    "DB_USER": DB_USER,
    "DB_PASSWORD": DB_PASSWORD,
    "DB_HOST": DB_HOST,
    "DB_PORT": DB_PORT,
    "DB_NAME": DB_NAME,
}

missing_variables = [
    name for name, value in required_variables.items()
    if not value
]

if missing_variables:
    raise RuntimeError(
        f"Missing database environment variables: {', '.join(missing_variables)}"
    )


# ------------------------------------------------------------
# Build database URL safely
# ------------------------------------------------------------
# URL.create() handles special characters in credentials
# correctly instead of manually constructing the URL string.

DATABASE_URL = URL.create(
    drivername="postgresql+pg8000",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)



# ------------------------------------------------------------
# SQLAlchemy Engine
# ------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# ------------------------------------------------------------
# Database Session
# ------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


# ------------------------------------------------------------
# SQLAlchemy Base
# ------------------------------------------------------------

class Base(DeclarativeBase):
    pass