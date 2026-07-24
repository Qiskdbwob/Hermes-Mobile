"""Cron job: Backup data to cloud storage"""

import asyncio
import shutil
from datetime import datetime

from hermes_mobile.config.settings import get_settings


async def main():
    settings = get_settings()
    data_dir = settings.get_data_dir()

    # Create backup directory
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"hermes_backup_{timestamp}"

    try:
        # Copy data directory (excluding backups)
        shutil.copytree(
            data_dir,
            backup_path,
            ignore=shutil.ignore_patterns("backups", "*.log", "__pycache__"),
        )
        print(f"Backup created at: {backup_path}")

        # Keep only last 7 backups
        backups = sorted(backup_dir.glob("hermes_backup_*"))
        for old_backup in backups[:-7]:
            shutil.rmtree(old_backup)
            print(f"Removed old backup: {old_backup}")

    except Exception as e:
        print(f"Backup failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
