import os
import uuid
from pathlib import Path

from sqlalchemy import Boolean, Column, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if not DATABASE_URL.startswith("postgresql"):
    raise RuntimeError("DATABASE_URL must point to a PostgreSQL database")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DashboardEffect(Base):
    __tablename__ = "dashboard_effects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(40), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    plan = Column(String(20), nullable=False, default="free", server_default="free")
    filter_1 = Column(Text, nullable=True)
    filter_2 = Column(Text, nullable=True)

    def to_payload(self):
        return {
            "class_id": self.id,
            "name": self.name,
            "states": ["global"],
        }

DEFAULT_CREDITS = 10
DEFAULT_PLAN = "pro"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(120), nullable=False)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    credits = Column(Integer, nullable=False, default=DEFAULT_CREDITS, server_default=str(DEFAULT_CREDITS))
    plan = Column(String(20), nullable=False, default=DEFAULT_PLAN, server_default=DEFAULT_PLAN)


class SignupSecurity(Base):
    __tablename__ = "signup_security"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_address = Column(String(45), nullable=False, index=True)
    device_id = Column(String(128), nullable=False, index=True)
    success = Column(Boolean, nullable=False, default=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    run_migrations()

    with SessionLocal() as db:
        seed_dashboard_effects(db)


def seed_dashboard_effects(db):
    defaults = [
        ("Rage", "Volt Rush", "free", "eq=contrast=1.25:saturation=1.7:gamma=1.12", "hue=s=1.35"),
        ("Rage", "Bone Breaker", "pro", "eq=contrast=1.35:saturation=1.9:gamma=1.15", "curves=vintage"),
        ("Cinematic", "Night Fade", "free", "eq=contrast=1.1:saturation=1.15:gamma=1.08", "colorbalance=rs=0.12:gs=0.0:bs=0.08"),
        ("Cinematic", "Amber Frame", "pro", "eq=contrast=1.18:saturation=1.25:gamma=1.1", "colorbalance=rs=0.18:gs=0.04:bs=-0.08"),
        ("Phonk", "Midnight Bass", "free", "eq=contrast=1.3:saturation=1.55:gamma=1.08", "hue=s=1.3"),
        ("Phonk", "Dark Velocity", "pro", "eq=contrast=1.4:saturation=1.8:gamma=1.12", "colorbalance=rs=0.08:gs=-0.02:bs=0.16"),
        ("Snap", "Flash Pop", "free", "eq=contrast=1.18:saturation=1.45:gamma=1.06", "hue=s=1.2"),
        ("Snap", "Impact Frame", "pro", "eq=contrast=1.35:saturation=1.7:gamma=1.1", "unsharp=5:5:0.8:5:5:0.0"),
        ("Cinematic", "Platinum Grade", "proplus", "eq=contrast=1.45:saturation=1.35:gamma=1.08", "colorbalance=rs=0.2:gs=0.08:bs=-0.04"),
        ("Phonk", "Neon Run", "proplus", "eq=contrast=1.5:saturation=1.9:gamma=1.12", "hue=s=1.55"),
        ("Rage", "Overdrive", "proplus", "eq=contrast=1.55:saturation=2.0:gamma=1.15", "unsharp=5:5:1.0:5:5:0.0"),
        ("Snap", "Hypercut", "proplus", "eq=contrast=1.5:saturation=1.85:gamma=1.1", "hue=s=1.5"),
    ]

    for category, name, plan, filter_1, filter_2 in defaults:
        exists = db.query(DashboardEffect).filter_by(category=category, name=name).first()
        if not exists:
            db.add(DashboardEffect(category=category, name=name, plan=plan, filter_1=filter_1, filter_2=filter_2))
    db.commit()


def run_migrations():
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        applied_versions = {
            row.version
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }

        for migration_file in migration_files:
            version = migration_file.name
            if version in applied_versions:
                continue

            migration_sql = migration_file.read_text(encoding="utf-8")
            for statement in migration_sql.split(";"):
                statement = statement.strip()
                if statement:
                    connection.exec_driver_sql(statement)

            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
