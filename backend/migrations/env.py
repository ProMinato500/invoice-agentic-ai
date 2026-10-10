from alembic import context

from backend.app import models  # noqa: F401 - registers mapped tables
from backend.app.db import Base, engine

config = context.config


def run():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=engine.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


run()
