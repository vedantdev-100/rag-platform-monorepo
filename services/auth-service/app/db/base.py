"""
Declarative base shared by all ORM models. Alembic's env.py imports this
(and every model module) so `alembic revision --autogenerate` can detect
schema changes across the whole app, not just auth.
"""
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(schema="auth")