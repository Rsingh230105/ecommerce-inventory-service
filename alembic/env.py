from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy import pool

from alembic import context

from app.database import Base, DATABASE_URL
from app import models


# ------------------------------------------------------------
# Alembic Config object
# ------------------------------------------------------------

config = context.config


# ------------------------------------------------------------
# Python logging configuration
# ------------------------------------------------------------

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ------------------------------------------------------------
# Metadata for Alembic autogenerate
# ------------------------------------------------------------

target_metadata = Base.metadata


# ------------------------------------------------------------
# Inventory-specific Alembic version table
# ------------------------------------------------------------
# Product  -> alembic_version
# Order    -> order_alembic_version
# Inventory -> inventory_alembic_version
#
# This prevents migration-history conflicts because all
# microservices use the same PostgreSQL database.
# ------------------------------------------------------------

INVENTORY_VERSION_TABLE = "inventory_alembic_version"


# ------------------------------------------------------------
# Offline migrations
# ------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = DATABASE_URL.render_as_string(hide_password=True)

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=INVENTORY_VERSION_TABLE,
    )

    with context.begin_transaction():
        context.run_migrations()


# ------------------------------------------------------------
# Online migrations
# ------------------------------------------------------------

def run_migrations_online() -> None:
    """Run migrations in online mode."""

    # Create SQLAlchemy engine directly from the URL object.
    #
    # This avoids Alembic ConfigParser interpolation issues
    # when the database password contains special characters
    # such as %, $, |, etc.
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=INVENTORY_VERSION_TABLE,
        )

        with context.begin_transaction():
            context.run_migrations()


# ------------------------------------------------------------
# Run migration mode
# ------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()