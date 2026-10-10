"""Initial local reconciliation schema; never touches unrelated tables."""

from alembic import op

from backend.app import models  # noqa: F401 - registers mapped tables
from backend.app.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    raise RuntimeError(
        "Destructive downgrade is intentionally disabled. Back up data and use a reviewed migration."
    )
