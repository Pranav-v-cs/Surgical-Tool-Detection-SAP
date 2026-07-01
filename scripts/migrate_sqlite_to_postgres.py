import os
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "data/sap.db"))
DATABASE_URL = os.getenv("DATABASE_URL")

TABLE_ORDER = [
    "users",
    "surgery_sessions",
    "saved_tool_inventory",
    "detection_events",
    "reconciliation_results",
    "audit_log",
]

JSON_COLUMNS = {
    "detection_events": {"tools_detected"},
    "reconciliation_results": {"missing_tools", "present_tools", "current_tools"},
}


def require_database_url():
    if not DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to your PostgreSQL connection string first.")
    if DATABASE_URL.startswith("sqlite"):
        raise SystemExit("DATABASE_URL must point to PostgreSQL, not SQLite.")


def sqlite_rows(connection, table_name):
    cursor = connection.execute(f'SELECT * FROM "{table_name}"')
    columns = [description[0] for description in cursor.description]
    rows = []
    for row in cursor.fetchall():
        item = dict(zip(columns, row))
        for column in JSON_COLUMNS.get(table_name, set()):
            if isinstance(item.get(column), str):
                item[column] = json.loads(item[column])
        rows.append(item)
    return rows


def reset_sequence(connection, table):
    primary_keys = list(table.primary_key.columns)
    if len(primary_keys) != 1:
        return

    pk_name = primary_keys[0].name
    connection.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence(:table_name, :pk_name),
                COALESCE((SELECT MAX(id) FROM "%s"), 0) + 1,
                false
            )
            """
            % table.name
        ),
        {"table_name": table.name, "pk_name": pk_name},
    )


def insert_missing_rows(connection, table, rows):
    primary_keys = [column.name for column in table.primary_key.columns]
    statement = insert(table).values(rows)
    if primary_keys:
        statement = statement.on_conflict_do_nothing(index_elements=primary_keys)
    result = connection.execute(statement)
    return result.rowcount or 0


def sqlite_tables(connection):
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {row[0] for row in rows}


def main():
    require_database_url()

    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite database not found: {SQLITE_PATH}")

    from app.database import Base, engine as app_engine
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=app_engine)

    sqlite_connection = sqlite3.connect(SQLITE_PATH)
    try:
        source_tables = sqlite_tables(sqlite_connection)
        postgres_engine = create_engine(DATABASE_URL, future=True)

        with postgres_engine.begin() as connection:
            for table_name in TABLE_ORDER:
                if table_name not in source_tables:
                    print(f"{table_name}: skipped, missing in SQLite")
                    continue

                table = Base.metadata.tables[table_name]
                rows = sqlite_rows(sqlite_connection, table_name)
                if not rows:
                    print(f"{table_name}: 0 rows")
                    continue

                copied = insert_missing_rows(connection, table, rows)
                reset_sequence(connection, table)
                skipped = len(rows) - copied
                message = f"{table_name}: copied {copied} rows"
                if skipped:
                    message += f", skipped {skipped} existing rows"
                print(message)
    finally:
        sqlite_connection.close()


if __name__ == "__main__":
    main()
