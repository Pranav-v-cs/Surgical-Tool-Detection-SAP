"""
run_server.py — Server entry point.
Starts the FastAPI app with uvicorn.
"""
import sys
import uvicorn

# ── 1. Import the existing FastAPI app ────────────────────────────────────────
from app.main import app

# ── 2. Print banner ───────────────────────────────────────────────────────────
print("=" * 56)
print("  Surgical Tools Detection -- Starting Server")
print("=" * 56)
print("  Dashboard  ->  http://localhost:8000")
print("  API docs   ->  http://localhost:8000/docs")
print("  Default users:")
print("    nurse1   / nurse123")
print("    surgeon1 / surgeon123")
print("    admin    / admin123")
print("=" * 56)

# ── 3. Start uvicorn ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
