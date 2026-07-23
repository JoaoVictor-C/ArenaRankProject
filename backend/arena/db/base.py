"""Declarative base + shared SQLAlchemy type/metadata conventions.

All ORM models inherit from :class:`Base`. We pin an explicit naming
convention so Alembic autogenerate produces deterministic, human-readable
constraint/index names (critical once partitioned DDL is hand-written and we
need autogenerate to *not* fight the baked-in raw DDL).

Nothing here is user-facing; English docs are fine. JSON column keys exposed
to the UI are camelCased in the Pydantic/serialization layer, never here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.types import TypeDecorator

# Deterministic constraint naming so migrations diff cleanly.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Project-wide declarative base."""

    metadata = metadata

    type_annotation_map = {
        # Map bare ``datetime`` annotations to timestamptz everywhere.
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


class TZDateTime(TypeDecorator[datetime]):  # pragma: no cover - thin alias
    """Convenience alias for an explicit timestamptz column type.

    Models generally rely on the ``datetime`` annotation map above; this is
    exported for the rare place that needs the type object directly (e.g.
    partition-key columns built in raw DDL contexts).
    """

    impl = TIMESTAMP(timezone=True)
    cache_ok = True


# Reusable column factories -------------------------------------------------


def uuid_pk() -> Any:
    """UUID primary key, generated client-side by the ORM (``gen_random_uuid()``
    kept as the server-side fallback for raw-SQL / non-ORM inserts).

    The Python-side ``default`` is a throughput lever, not cosmetics: with a
    *server*-generated random PK the ORM has no sentinel to correlate
    ``INSERT ... RETURNING`` rows back to input objects, so SQLAlchemy's
    ``insertmanyvalues`` batching is disabled and a multi-row flush degrades to
    one round-trip *per row*. Generating the uuid in-process means the PK is
    known before insert, so same-table inserts batch into a single statement
    (e.g. 16 ``match_participants`` => 1 round-trip instead of 16)."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def uuid_col(**kwargs: Any) -> Any:
    """A plain ``uuid`` column (FK targets, nullable refs, etc.)."""
    return mapped_column(UUID(as_uuid=True), **kwargs)
