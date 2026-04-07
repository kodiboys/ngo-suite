# FILE: scripts/backup.py
# MODULE: Backup Script

import asyncio
from datetime import datetime, timezone

from src.core.config import settings
from src.services.backup_service import WasabiBackupService
import redis.asyncio as redis


async def main():
    """Run backup"""
    redis_client = await redis.from_url(settings.REDIS_URL)
    
    backup_service = WasabiBackupService(
        access_key=settings.WASABI_ACCESS_KEY,
        secret_key=settings.WASABI_SECRET_KEY.get_secret_value() if settings.WASABI_SECRET_KEY else "",
        bucket_name=settings.WASABI_BUCKET_NAME,
        endpoint_url=settings.WASABI_ENDPOINT,
    )
    
    await backup_service.create_full_backup(
        database_url=settings.DATABASE_URL,
        backup_type="daily",
    )
    
    print(f"Backup completed at {datetime.now(timezone.utc).isoformat()}")
    await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())