# FILE: migrations/env.py
# MODULE: Alembic Environment Configuration

import asyncio
from logging.config import fileConfig
import os
import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import context

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import your models' metadata
from src.core.entities.base import Base
from src.core.config import settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set database URL from environment or settings
database_url = os.getenv("DATABASE_URL", settings.database_url)
config.set_main_option("sqlalchemy.url", database_url)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_name=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # For sync migrations (Alembic default)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_name=True,
        )

        with context.begin_transaction():
            context.run_migrations()


def run_async_migrations() -> None:
    """Run migrations in async mode (for asyncpg)."""
    async def run():
        async_engine = create_async_engine(
            database_url.replace("postgresql://", "postgresql+asyncpg://"),
            poolclass=pool.NullPool
        )
        
        async with async_engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
        
        await async_engine.dispose()
    
    def do_run_migrations(connection):
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_name=True,
        )
        
        with context.begin_transaction():
            context.run_migrations()
    
    asyncio.run(run())


# Check if async mode is requested
if context.is_offline_mode():
    run_migrations_offline()
else:
    # Use async migrations for asyncpg
    if "asyncpg" in database_url:
        run_async_migrations()
    else:
        run_migrations_online()
