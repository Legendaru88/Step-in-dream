from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from sqlalchemy.engine import make_url
from app.config import get_settings

def main():
    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise SystemExit("This helper requires a file-backed SQLite database")
    source = Path(url.database).resolve()
    if not source.is_file(): raise SystemExit("Database does not exist: run migrations first")
    folder = Path("backups"); folder.mkdir(exist_ok=True)
    target = folder / ("goals-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".db")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    print(str(target))
if __name__ == "__main__": main()
