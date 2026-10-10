from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import settings

settings.storage.mkdir(parents=True, exist_ok=True)
db_url = settings.database_url
if db_url.startswith("sqlite:///./"):
    from backend.app.core.config import ROOT

    db_url = "sqlite:///" + str(ROOT / db_url.removeprefix("sqlite:///./")).replace("\\", "/")
engine = create_engine(
    db_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30} if db_url.startswith("sqlite") else {},
)
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


if db_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def configure_sqlite(conn, _):
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
