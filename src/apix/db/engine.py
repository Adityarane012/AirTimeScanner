from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apix.settings import settings

# connect_timeout: on a network that silently drops the database port, psycopg
# would otherwise wait out the OS TCP timeout for every resolved address.
# The collector treats an unreachable database as a normal condition (see
# apix.ops.spool), so it should find out quickly.
engine = create_engine(
    settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10}
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_session() -> Session:
    return SessionLocal()
