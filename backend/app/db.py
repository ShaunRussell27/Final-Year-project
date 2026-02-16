import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _make_db_url() -> str:
    """
    Railway typically provides DATABASE_URL like:
    postgres://user:pass@host:port/db

    psycopg2 expects postgresql://
    Also, many managed Postgres require SSL; Railway generally works without
    extra config, but adding sslmode=require is safe.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Local dev fallback (create your own local postgres or use Railway dev env)
        return "postgresql://postgres:postgres@localhost:5432/postgres"

    url = url.replace("postgres://", "postgresql://", 1)
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url

DATABASE_URL = _make_db_url()

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
