import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# MySQL on AWS RDS in production, e.g.
#   mysql+pymysql://lms_app:<password>@lms.xxxx.ap-south-1.rds.amazonaws.com:3306/lms
# SQLite works for local tests.
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://lms:lms@localhost:3306/lms")

_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
else:
    _kwargs.update(pool_size=10, max_overflow=20, pool_recycle=1800)

engine = create_engine(DATABASE_URL, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns(eng=engine):
    """create_all() only creates new tables. Add any column the models have gained since the
    table was first created, so existing data is kept. Only ever adds nullable columns."""
    from sqlalchemy import inspect, text
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    ctype = col.type.compile(dialect=eng.dialect)
                    conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN `{col.name}` {ctype}"))
