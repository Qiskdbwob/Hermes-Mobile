"""Cron job: Check for updates"""

import asyncio
import subprocess
import sys


async def main():
    print("Checking for updates...")

    # Check pip for package updates
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            import json

            outdated = json.loads(result.stdout)
            if outdated:
                print(f"Found {len(outdated)} outdated packages:")
                for pkg in outdated[:10]:
                    print(f"  {pkg['name']}: {pkg['version']} -> {pkg['latest_version']}")
            else:
                print("All packages up to date")
    except Exception as e:
        print(f"Error checking updates: {e}")


if __name__ == "__main__":
    asyncio.run(main())
