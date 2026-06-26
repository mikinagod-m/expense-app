"""Database and receipt backup helpers."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path


def sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    raw = database_url.removeprefix("sqlite:///")
    if raw.startswith("./"):
        raw = raw[2:]
    return Path(raw)


def prune_old_backups(backup_root: Path, retention_days: int) -> list[str]:
    if retention_days < 1 or not backup_root.is_dir():
        return []
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=retention_days)
    removed: list[str] = []
    for entry in sorted(backup_root.iterdir()):
        if not entry.is_dir():
            continue
        mtime = dt.datetime.fromtimestamp(entry.stat().st_mtime, dt.UTC)
        if mtime < cutoff:
            shutil.rmtree(entry)
            removed.append(entry.name)
    return removed


def run_backup(
    *,
    database_url: str,
    receipts_dir: str,
    backup_dir: str,
    retention_days: int = 14,
) -> dict:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = Path(backup_dir)
    destination = backup_root / timestamp
    destination.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    warnings: list[str] = []
    db_path = sqlite_path_from_url(database_url)

    if db_path is None:
        warnings.append("DATABASE_URL is not SQLite; copy the database with pg_dump or your host backup tool.")
        (destination / "POSTGRES_BACKUP_README.txt").write_text(
            "This deployment uses a non-SQLite DATABASE_URL.\n"
            "Use pg_dump or your database provider's backup tooling for the database file.\n"
            "Receipt files are still copied into receipts/ when present.\n",
            encoding="utf-8",
        )
    elif not db_path.is_file():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    else:
        target_db = destination / db_path.name
        shutil.copy2(db_path, target_db)
        copied_files.append(target_db.name)

    receipts_path = Path(receipts_dir)
    if receipts_path.is_dir():
        shutil.copytree(receipts_path, destination / "receipts")
        copied_files.append("receipts/")
    else:
        warnings.append(f"Receipts directory not found: {receipts_path}")

    manifest = {
        "timestamp": timestamp,
        "database_url": database_url,
        "receipts_dir": receipts_dir,
        "copied": copied_files,
        "warnings": warnings,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    removed = prune_old_backups(backup_root, retention_days)
    return {
        "ok": True,
        "destination": str(destination),
        "copied": copied_files,
        "warnings": warnings,
        "removed_backups": removed,
    }
