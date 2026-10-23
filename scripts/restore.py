import argparse
from pathlib import Path
import sqlite3
from sqlalchemy.engine import make_url
from app.config import get_settings
from scripts.backup import main as backup_current

def main():
    parser = argparse.ArgumentParser(description="Stop API and bot before restoring SQLite")
    parser.add_argument("backup"); parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes: raise SystemExit("Stop API/bot, then repeat with --yes to replace current data")
    source = Path(args.backup).resolve()
    if not source.is_file(): raise SystemExit("Backup file not found")
    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise SystemExit("File-backed SQLite required")
    target = Path(url.database).resolve()
    if source == target: raise SystemExit("Backup and destination must differ")
    with sqlite3.connect(source.as_uri()+"?mode=ro", uri=True) as src:
        if src.execute("PRAGMA quick_check").fetchone()[0] != "ok": raise SystemExit("Invalid backup")
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "goals", "steps", "dialog_logs", "alembic_version"}.issubset(tables):
            raise SystemExit("Not a Step to Dream database")
        if target.exists(): backup_current()
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as dst: src.backup(dst)
    print("Database restored. Start the application again.")
if __name__ == "__main__": main()
