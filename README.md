# Surgical Tools Detection

A FastAPI dashboard for real-time surgical-instrument detection with YOLOv8,
camera input, WebSocket updates, authentication, and SQLite/PostgreSQL storage.

## Setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python run_server.py
```

Open <http://localhost:8000>. API documentation is available at
<http://localhost:8000/docs>.

The application creates `data/sap.db` when `DATABASE_URL` is not set. To use
PostgreSQL, see [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) and set the
variables shown in `.env.example` in your shell or deployment environment.

## Local assets

Datasets, training runs, database files, and model binaries are intentionally
excluded from regular Git because they make clones impractically large. They
remain in the local project directory. The application searches for a trained
`best.pt` in the locations listed in `app/inference.py`.

To train:

```bash
python convert_xml_to_yolo.py
python train.py
```

If model or dataset versioning is required, use Git LFS or an external artifact
store rather than committing large binaries to ordinary Git history.

## Development warning

The server seeds demonstration users on an empty database and prints their
credentials at startup. Replace those accounts and set a strong `SECRET_KEY`
before exposing the application outside a trusted development environment.
