# PostgreSQL migration

## 1. Install the PostgreSQL driver

```powershell
python -m pip install -r requirements_app.txt
```

## 2. Create a PostgreSQL database

Example connection string:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://sap_user:sap_password@localhost:5432/sap"
```

The app still falls back to `sqlite:///./data/sap.db` when `DATABASE_URL` is not set.

If PostgreSQL says `permission denied for schema public`, open SQL Shell as the
`postgres` admin user and run:

```sql
\c sap
ALTER DATABASE sap OWNER TO sap_user;
GRANT USAGE, CREATE ON SCHEMA public TO sap_user;
```

## 3. Create tables and migrate existing SQLite data

```powershell
python scripts/migrate_sqlite_to_postgres.py
```

The migration imports the normal app models, creates the PostgreSQL tables, then copies missing rows by primary key. It is safe to rerun; rows already present in PostgreSQL are skipped.

- `users`
- `surgery_sessions`
- `saved_tool_inventory`
- `detection_events`
- `reconciliation_results`
- `audit_log`

## 4. Run the app on PostgreSQL

Keep `DATABASE_URL` set in the same terminal, then start:

```powershell
python run_server.py
```
