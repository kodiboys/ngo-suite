# FILE: scripts/warmup_cache.py
# MODULE: Cache Warmup Script

import asyncio
from datetime import datetime, timezone

import redis.asyncio as redis

from src.core.config import settings


async def warmup_cache():
    """Pre-warm important cache keys"""
    redis_client = await redis.from_url(settings.REDIS_URL)
    
    print(f"Cache warmup started at {datetime.now(timezone.utc).isoformat()}")
    
    # Add cache warmup logic here
    # e.g., preload projects, donations, etc.
    
    await redis_client.set("cache:warmup:last_run", datetime.now(timezone.utc).isoformat())
    print("Cache warmup completed")
    
    await redis_client.close()


if __name__ == "__main__":
    asyncio.run(warmup_cache())