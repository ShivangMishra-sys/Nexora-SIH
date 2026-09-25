"""
UrbanFlow — Database Connection
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_SYNC_URL
from app.db.models import Base

logger = logging.getLogger("urbanflow.database")

engine_sync = create_engine(DATABASE_SYNC_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine_sync, autoflush=False, autocommit=False)


def create_tables():
    """Create all tables (idempotent)."""
    try:
        Base.metadata.create_all(bind=engine_sync)
        logger.info("Database tables created/verified.")
    except Exception as e:
        logger.warning(f"Could not create tables: {e} — proceeding without DB persistence")


def get_db():
    """Dependency for FastAPI route handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
