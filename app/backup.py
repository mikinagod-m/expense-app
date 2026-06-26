"""CLI entry: python -m app.backup"""
from .backup_utils import run_backup
from .config import settings


def main() -> None:
    result = run_backup(
        database_url=settings.database_url,
        receipts_dir=settings.receipts_dir,
        backup_dir=settings.backup_dir,
        retention_days=settings.backup_retention_days,
    )
    print(f"Backup saved to {result['destination']}")
    if result["warnings"]:
        for warning in result["warnings"]:
            print(f"Warning: {warning}")
    if result["removed_backups"]:
        print(f"Pruned old backups: {', '.join(result['removed_backups'])}")


if __name__ == "__main__":
    main()
