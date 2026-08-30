from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from resoiltwin.config import get_settings
from resoiltwin.db import Base
import resoiltwin.models  # noqa: F401  garante que os modelos sao registados

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
#
# `disable_existing_loggers=False` e nao a omissao do template do Alembic. Com
# a omissao (True), esta linha DESLIGA todos os loggers que ja existam --
# `resoiltwin.weather.ipma`, `resoiltwin.weather.ingest`, `resoiltwin.eo.*` --
# e nao ha nada a assinalar: os `logger.warning` continuam a ser chamados e nao
# sai nenhum. Qualquer processo que corra migracoes antes de ingerir ficava sem
# os avisos todos, incluindo os das leituras descartadas, que sao a unica
# forma de ver na hora que a origem mudou de convencao. Descoberto a 30/08/2026
# por um teste de log que passava sozinho e caia dentro da suite inteira.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# a url vem de get_settings(), nunca do alembic.ini: um so lugar para a
# configuracao de ligacao, sem segredos no ficheiro versionado. O chamador pode
# injectar outra em config.attributes["sqlalchemy_url"] -- e o que a suite de
# testes faz para construir a base resoiltwin_test pelas migracoes em vez de
# por Base.metadata.create_all.
config.set_main_option(
    "sqlalchemy.url",
    config.attributes.get("sqlalchemy_url") or get_settings().database_url,
)

# metadata dos modelos, para o autogenerate comparar contra a base real
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


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
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
