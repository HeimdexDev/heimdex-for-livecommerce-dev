import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
from app.modules.orgs.models import Org
from app.modules.users.models import User
from app.modules.libraries.models import Library
from app.modules.profiles.models import LibraryProfile
from app.modules.drive.models import DriveConnection, DriveFile, DriveSecret
from app.modules.people.models import DriveNicknameRegistry, PeopleClusterLabel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return os.environ.get(
        "DATABASE_URL_SYNC",
        "postgresql://heimdex:heimdex_dev_password@localhost:5432/heimdex",
    )


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # ``transaction_per_migration=True``: each revision runs in its
        # own transaction (committed between revisions) instead of one
        # mega-transaction wrapping everything. Required for migrations
        # that ``ALTER TYPE … ADD VALUE`` and downstream migrations
        # that USE the new value — Postgres rejects same-transaction
        # use of newly-added enum values (UnsafeNewEnumValueUsage).
        # The previous staging outage (PRs #114-123 stuck on rev 051
        # for 17h) was caused by this default. See migrations 052/053.
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_num_width=128,
            # See offline path for the rationale on transaction_per_migration.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
