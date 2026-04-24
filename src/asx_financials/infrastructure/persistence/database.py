from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(
    database_url: str,
    *,
    pool_size: int = 2,
    max_overflow: int = 0,
    pool_timeout_seconds: int = 30,
    pool_recycle_seconds: int = 1800,
    connect_timeout_seconds: int = 10,
) -> sessionmaker[Session]:
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
        pool_recycle=pool_recycle_seconds,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
