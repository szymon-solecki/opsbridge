"""Declarative metadata for the approved OpsBridge V1 database schema.

The append-only rule for delivery_events and immutability/cycle prevention for
files.replaces_file are not enforced by ORM metadata. PostgreSQL trigger or
permission protections remain pending for the first Alembic migration.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
