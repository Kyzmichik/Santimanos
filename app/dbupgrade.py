"""Легке оновлення схеми SQLite: додає нові колонки до вже створених таблиць.

Це тимчасове рішення для SQLite. Перед переходом на PostgreSQL підключіть Flask-Migrate.
"""
from sqlalchemy import inspect, text

from . import db

NEW_COLUMNS = {
    "users": [
        # для акаунтів, створених до MVP-3, пошту вважаємо підтвердженою
        ("email_confirmed", "BOOLEAN NOT NULL DEFAULT 1"),
        ("is_blocked", "BOOLEAN NOT NULL DEFAULT 0"),
        ("is_verified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("notify_email", "BOOLEAN NOT NULL DEFAULT 1"),
        ("notify_new_requests", "VARCHAR(10) NOT NULL DEFAULT 'instant'"),
        ("last_digest_at", "DATETIME"),
    ],
    "job_requests": [("invited_master_id", "INTEGER")],
    "categories": [("hint", "TEXT")],
}


def upgrade_schema():
    insp = inspect(db.engine)
    for table, columns in NEW_COLUMNS.items():
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in columns:
            if name not in existing:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    db.session.commit()
