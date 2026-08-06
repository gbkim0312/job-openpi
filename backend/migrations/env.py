import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from job_collector.persistence import Base

config = context.config
target_metadata = Base.metadata

# Compose injects DATABASE_URL through env_file.  Alembic must use the same
# connection string as the API instead of the placeholder in alembic.ini.
if database_url := os.getenv("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section)
    section["sqlalchemy.url"] = section["sqlalchemy.url"].replace("+asyncpg", "+psycopg")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
