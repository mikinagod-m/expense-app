"""Lightweight schema patches for existing SQLite/Postgres databases."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def upgrade_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "is_admin" not in columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0")
            )
            conn.execute(text("UPDATE users SET is_admin = 1 WHERE is_finance = 1"))

        if "is_sales_team" not in columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_sales_team BOOLEAN NOT NULL DEFAULT 0")
            )

        admin_count = conn.execute(
            text("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        ).scalar_one()
        if admin_count == 0:
            conn.execute(
                text(
                    "UPDATE users SET is_admin = 1 "
                    "WHERE id = (SELECT id FROM users ORDER BY id LIMIT 1)"
                )
            )

    if "claims" in inspector.get_table_names():
        claim_columns = {c["name"] for c in inspector.get_columns("claims")}
        with engine.begin() as conn:
            if "wfh_days" not in claim_columns:
                conn.execute(
                    text("ALTER TABLE claims ADD COLUMN wfh_days INTEGER NOT NULL DEFAULT 0")
                )
            if "wfh_rate" not in claim_columns:
                conn.execute(
                    text("ALTER TABLE claims ADD COLUMN wfh_rate FLOAT NOT NULL DEFAULT 0")
                )
