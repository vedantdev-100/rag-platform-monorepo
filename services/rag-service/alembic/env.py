import asyncio
import os
import sys
from logging.config import fileConfig

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models import chunk, document  # noqa: F401 — only this service's models
from sqlalchemy import text

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "rag"

    if type_ == "table":
        return parent_names.get("schema_name") == "rag"

    return True

settings = get_settings()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="rag",   # alembic_version lives inside this service's own schema
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:

    connection.execute(text("SET search_path TO rag;"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="rag",
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

# import asyncio
# import os
# import sys
# from logging.config import fileConfig

# from sqlalchemy import text

# # Ensure the project root (containing the `app` package) is importable
# # regardless of the working directory `alembic` is invoked from.
# sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from alembic import context
# from sqlalchemy.ext.asyncio import create_async_engine

# from app.core.config import get_settings
# from app.db.base import Base

# # Import every model module so autogenerate can see them.
# from app.models import chunk, document  # noqa: F401

# config = context.config
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)

# target_metadata = Base.metadata
# print("REGISTERED TABLES:", target_metadata.tables.keys())
# settings = get_settings()


# def run_migrations_offline() -> None:
#     context.configure(
#         url=settings.DATABASE_URL,
#         target_metadata=target_metadata,
#         literal_binds=True,
#         dialect_opts={"paramstyle": "named"},
#     )
#     with context.begin_transaction():
#         context.run_migrations()


# # def do_run_migrations(connection) -> None:
# #     context.configure(connection=connection, target_metadata=target_metadata)
# #     with context.begin_transaction():
# #         context.run_migrations()

# def do_run_migrations(connection) -> None:
#     # Set the search path so alembic knows to create tables inside the 'rag' schema
#     # connection.execute(text('CREATE SCHEMA IF NOT EXISTS rag;'))
#     # connection.commit()
    
#     context.configure(
#         connection=connection, 
#         target_metadata=target_metadata,
#         version_table_schema='rag' # Keeps alembic's migration tracking table inside the auth schema too!
#     )
#     with context.begin_transaction():
#         context.run_migrations()


# # async def run_migrations_online() -> None:
# #     connectable = create_async_engine(settings.DATABASE_URL)
# #     async with connectable.connect() as connection:
# #         await connection.run_sync(do_run_migrations)
# #     await connectable.dispose()

# async def run_migrations_online() -> None:
#     # Pass search_path via asyncpg server_settings connect_args
#     connectable = create_async_engine(
#         settings.DATABASE_URL,
#         connect_args={"server_settings": {"search_path": "rag"}}
#     )
#     async with connectable.connect() as connection:
#         await connection.run_sync(do_run_migrations)
#     await connectable.dispose()


# if context.is_offline_mode():
#     run_migrations_offline()
# else:
#     asyncio.run(run_migrations_online())
