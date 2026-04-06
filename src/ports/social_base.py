# FILE: src/ports/social_base.py
# MODULE: Social Media Base Classes & Adapter Pattern
# Enterprise Social Media Integration mit Rate-Limiting, Queue, Media Support

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, validator

# ==================== Enums ====================


class SocialPlatform(str, Enum):
    """Unterstützte Social Media Plattformen"""

    TWITTER = "twitter"
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"
    INSTAGRAM = "instagram"
    MASTODON = "mastodon"
    BLUESKY = "bluesky"


class PostStatus(str, Enum):
    """Status eines Social Media Posts"""

    DRAFT = "draft"
    PENDING = "pending"  # In der Warteschlange
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    DELETED = "deleted"


class MediaType(str, Enum):
    """Medientypen für Posts"""

    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"
    CAROUSEL = "carousel"


# ==================== Data Models ====================


@dataclass
class SocialMediaAccount:
    """Social Media Account eines Benutzers"""

    id: UUID
    platform: SocialPlatform
    platform_user_id: str  # Twitter User ID, Facebook Page ID, etc.
    platform_username: str
    access_token: str  # Verschlüsselt in DB
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    is_active: bool = True
    last_post_at: datetime | None = None
    rate_limit_remaining: int = 0
    rate_limit_reset: datetime | None = None

    # Platform-spezifische Metadaten
    metadata: dict[str, Any] = field(default_factory=dict)

    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MediaAttachment:
    """Medienanhang für Posts"""

    type: MediaType
    url: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None
    mime_type: str | None = None
    alt_text: str | None = None  # Barrierefreiheit
    width: int | None = None
    height: int | None = None


@dataclass
class SocialPost:
    """Social Media Post"""

    id: UUID
    account_id: UUID
    platform: SocialPlatform
    platform_post_id: str | None = None  # ID auf der Plattform

    # Content
    text: str
    media: list[MediaAttachment] = field(default_factory=list)
    link_preview: str | None = None
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)

    # Scheduling
    status: PostStatus = PostStatus.DRAFT
    scheduled_at: datetime | None = None
    published_at: datetime | None = None

    # Analytics
    like_count: int = 0
    share_count: int = 0
    comment_count: int = 0
    impression_count: int = 0
    engagement_rate: float = 0.0

    # Campaign Tracking
    campaign_id: UUID | None = None
    project_id: UUID | None = None
    donation_id: UUID | None = None  # Verknüpfung mit Spende

    # Compliance
    requires_approval: bool = False
    approved_by: UUID | None = None
    approved_at: datetime | None = None

    # Audit
    created_by: UUID
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # Fehlerbehandlung
    error_message: str | None = None
    retry_count: int = 0


class CreatePostRequest(BaseModel):
    """API Request für neuen Post"""

    text: str = Field(..., min_length=1, max_length=2800, description="Post-Text")
    platform: SocialPlatform
    scheduled_at: datetime | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list, description="Bild/Video URLs")
    link_preview: str | None = None
    campaign_id: UUID | None = None
    project_id: UUID | None = None

    @validator("text")
    def validate_text_length(cls, v, values):
        platform = values.get("platform")
        if platform == SocialPlatform.TWITTER and len(v) > 280:
            raise ValueError(f"Twitter posts max 280 characters, got {len(v)}")
        if platform == SocialPlatform.INSTAGRAM and len(v) > 2200:
            raise ValueError(f"Instagram posts max 2200 characters, got {len(v)}")
        return v

    @validator("hashtags")
    def validate_hashtags(cls, v):
        if len(v) > 30:
            raise ValueError("Maximum 30 hashtags")
        return [tag.lower().replace("#", "") for tag in v]


class PostResponse(BaseModel):
    """API Response für Post"""

    id: UUID
    platform: SocialPlatform
    text: str
    status: PostStatus
    platform_post_id: str | None
    published_at: datetime | None
    scheduled_at: datetime | None
    engagement: dict[str, int]

    class Config:
        use_enum_values = True


# ==================== Abstract Provider Interface ====================


class SocialProviderInterface(ABC):
    """Abstract Interface für alle Social Media Provider"""

    @abstractmethod
    async def authenticate(self, account: SocialMediaAccount) -> bool:
        """Authentifiziert sich bei der Plattform"""
        pass

    @abstractmethod
    async def post(self, post: SocialPost) -> SocialPost:
        """Veröffentlicht einen Post"""
        pass

    @abstractmethod
    async def delete_post(self, platform_post_id: str, account: SocialMediaAccount) -> bool:
        """Löscht einen Post"""
        pass

    @abstractmethod
    async def get_post_stats(
        self, platform_post_id: str, account: SocialMediaAccount
    ) -> dict[str, int]:
        """Holt Engagement-Statistiken"""
        pass

    @abstractmethod
    async def upload_media(self, media: MediaAttachment, account: SocialMediaAccount) -> str:
        """Upload von Medien (Bild/Video) zur Plattform"""
        pass

    @abstractmethod
    async def refresh_token(self, account: SocialMediaAccount) -> SocialMediaAccount:
        """Erneuert Access Token"""
        pass


# ==================== Social Media Queue ====================


class SocialMediaQueue:
    """
    Warteschlange für Social Media Posts mit:
    - Rate-Limiting pro Plattform
    - Retry mit Exponential Backoff
    - Priority Queue für dringende Posts
    - Dead Letter Queue für fehlgeschlagene Posts
    """

    def __init__(self, redis_client):
        self.redis = redis_client
        self.queue_key = "social:post_queue"
        self.dead_letter_key = "social:dead_letter"

    async def enqueue(self, post_id: UUID, priority: int = 5):
        """
        Fügt Post zur Warteschlange hinzu
        priority: 1 (höchste) bis 10 (niedrigste)
        """

        # Redis Sorted Set mit priority als Score
        await self.redis.zadd(self.queue_key, {str(post_id): priority})

    async def dequeue(self) -> UUID | None:
        """Holt nächsten Post aus der Warteschlange"""
        result = await self.redis.zpopmin(self.queue_key, 1)
        if result:
            return UUID(result[0][0].decode())
        return None

    async def mark_failed(self, post_id: UUID, error: str):
        """Verschiebt fehlgeschlagenen Post zur Dead Letter Queue"""
        import json
        from datetime import datetime

        await self.redis.lpush(
            self.dead_letter_key,
            json.dumps(
                {
                    "post_id": str(post_id),
                    "error": error,
                    "failed_at": datetime.utcnow().isoformat(),
                }
            ),
        )

    async def get_queue_length(self) -> int:
        """Länge der Warteschlange"""
        return await self.redis.zcard(self.queue_key)
