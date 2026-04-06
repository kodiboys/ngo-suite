# FILE: src/services/social_service.py
# MODULE: Social Media Orchestration Service
# Koordiniert Posts über alle Plattformen mit Scheduling, Queue, Analytics

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import AuditLog
from src.core.events.event_bus import Event, EventBus
from src.ports.social_base import (
    CreatePostRequest,
    MediaAttachment,
    PostStatus,
    SocialMediaAccount,
    SocialMediaQueue,
    SocialPlatform,
    SocialPost,
)
from src.ports.social_facebook import FacebookProvider
from src.ports.social_linkedin import LinkedInProvider
from src.ports.social_twitter import TwitterProvider

logger = logging.getLogger(__name__)


class SocialMediaService:
    """
    Social Media Orchestration Service
    Features:
    - Multi-Platform Publishing
    - Scheduling mit Timezone-Unterstützung
    - Automatische Retries mit Backoff
    - Engagement Analytics
    - Campaign Tracking
    - DSGVO-konformes Logging
    """

    def __init__(self, session_factory, redis_client, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus
        self.queue = SocialMediaQueue(redis_client)

        # Provider initialisieren
        self.providers = {
            SocialPlatform.TWITTER: TwitterProvider(
                client_id="YOUR_TWITTER_CLIENT_ID",
                client_secret="YOUR_TWITTER_CLIENT_SECRET",
                bearer_token="YOUR_BEARER_TOKEN",
            ),
            SocialPlatform.FACEBOOK: FacebookProvider(
                app_id="YOUR_FACEBOOK_APP_ID", app_secret="YOUR_FACEBOOK_APP_SECRET"
            ),
            SocialPlatform.INSTAGRAM: FacebookProvider(
                app_id="YOUR_FACEBOOK_APP_ID", app_secret="YOUR_FACEBOOK_APP_SECRET"
            ),
            SocialPlatform.LINKEDIN: LinkedInProvider(
                client_id="YOUR_LINKEDIN_CLIENT_ID", client_secret="YOUR_LINKEDIN_CLIENT_SECRET"
            ),
        }

    async def create_post(self, request: CreatePostRequest, user_id: UUID) -> SocialPost:
        """
        Erstellt neuen Social Media Post
        Optional mit Scheduling
        """
        async with self.session_factory() as session:
            # Hole Account für Plattform
            account = await self._get_account(session, request.platform, user_id)

            if not account:
                raise HTTPException(
                    status_code=404, detail=f"No account connected for {request.platform.value}"
                )

            # Erstelle Post
            post = SocialPost(
                id=uuid4(),
                account_id=account.id,
                platform=request.platform,
                text=request.text,
                hashtags=request.hashtags,
                mentions=request.mentions,
                link_preview=request.link_preview,
                scheduled_at=request.scheduled_at,
                campaign_id=request.campaign_id,
                project_id=request.project_id,
                created_by=user_id,
                status=PostStatus.PENDING if request.scheduled_at else PostStatus.DRAFT,
            )

            # Verarbeite Medien (falls vorhanden)
            if request.media_urls:
                for url in request.media_urls:
                    media = MediaAttachment(type="image", url=url)
                    post.media.append(media)

            # Speichere in DB
            await self._save_post(session, post)

            # Bei sofortiger Veröffentlichung in Queue
            if not request.scheduled_at:
                await self.queue.enqueue(post.id, priority=1)

            # Audit Log
            audit = AuditLog(
                user_id=user_id,
                action="SOCIAL_POST_CREATED",
                entity_type="social_post",
                entity_id=post.id,
                new_values={
                    "platform": post.platform.value,
                    "text_preview": post.text[:100],
                    "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
                },
                ip_address="api",
                retention_until=datetime.now(UTC) + timedelta(days=365),
            )
            session.add(audit)
            await session.commit()

            # Publish Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=post.id,
                    aggregate_type="SocialPost",
                    event_type="SocialPostCreated",
                    data={
                        "platform": post.platform.value,
                        "hashtags": post.hashtags,
                        "project_id": str(post.project_id) if post.project_id else None,
                    },
                    user_id=user_id,
                    metadata={},
                )
            )

            return post

    async def publish_post(self, post_id: UUID) -> SocialPost:
        """
        Veröffentlicht einen Post (wird von Worker aufgerufen)
        Mit automatischem Retry bei Fehlern
        """
        async with self.session_factory() as session:
            # Lade Post
            stmt = select(SocialPost).where(SocialPost.id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one()

            if post.status == PostStatus.PUBLISHED:
                logger.info(f"Post {post_id} already published")
                return post

            # Lade Account
            stmt = select(SocialMediaAccount).where(SocialMediaAccount.id == post.account_id)
            result = await session.execute(stmt)
            account = result.scalar_one()

            # Hole Provider
            provider = self.providers.get(post.platform)
            if not provider:
                raise ValueError(f"No provider for platform {post.platform}")

            try:
                # Stelle sicher, dass Token gültig ist
                if account.token_expires_at and account.token_expires_at <= datetime.now(
                    UTC
                ):
                    account = await provider.refresh_token(account)
                    await self._update_account(session, account)

                # Authentifiziere
                await provider.authenticate(account)

                # Veröffentliche
                post = await provider.post(post)

                # Update in DB
                await self._update_post(session, post)

                # Audit Log
                audit = AuditLog(
                    user_id=post.created_by,
                    action="SOCIAL_POST_PUBLISHED",
                    entity_type="social_post",
                    entity_id=post.id,
                    new_values={"platform_post_id": post.platform_post_id},
                    ip_address="system",
                    retention_until=datetime.now(UTC) + timedelta(days=365),
                )
                session.add(audit)
                await session.commit()

                # Publish Event
                await self.event_bus.publish(
                    Event(
                        aggregate_id=post.id,
                        aggregate_type="SocialPost",
                        event_type="SocialPostPublished",
                        data={
                            "platform_post_id": post.platform_post_id,
                            "published_at": post.published_at.isoformat(),
                        },
                        user_id=post.created_by,
                        metadata={},
                    )
                )

                logger.info(f"Post {post_id} published successfully on {post.platform.value}")

            except Exception as e:
                logger.error(f"Failed to publish post {post_id}: {e}")
                post.status = PostStatus.FAILED
                post.error_message = str(e)
                post.retry_count += 1
                await self._update_post(session, post)

                # Bei Retry-Versuch erneut in Queue
                if post.retry_count < 3:
                    await self.queue.enqueue(post_id, priority=5 + post.retry_count)
                else:
                    await self.queue.mark_failed(post_id, str(e))

            return post

    async def delete_post(self, post_id: UUID, user_id: UUID) -> bool:
        """Löscht einen veröffentlichten Post von der Plattform"""
        async with self.session_factory() as session:
            stmt = select(SocialPost).where(SocialPost.id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one()

            if not post.platform_post_id:
                raise HTTPException(status_code=400, detail="Post not published yet")

            # Hole Provider
            provider = self.providers.get(post.platform)
            if not provider:
                raise ValueError(f"No provider for platform {post.platform}")

            # Lade Account
            stmt = select(SocialMediaAccount).where(SocialMediaAccount.id == post.account_id)
            result = await session.execute(stmt)
            account = result.scalar_one()

            try:
                await provider.authenticate(account)
                success = await provider.delete_post(post.platform_post_id, account)

                if success:
                    post.status = PostStatus.DELETED
                    await self._update_post(session, post)
                    # Audit Log
                    audit = AuditLog(
                        user_id=user_id,
                        action="SOCIAL_POST_DELETED",
                        entity_type="social_post",
                        entity_id=post.id,
                        old_values={"platform_post_id": post.platform_post_id},
                        ip_address="api",
                        retention_until=datetime.now(UTC) + timedelta(days=365),
                    )
                    session.add(audit)
                    await session.commit()

                return success

            except Exception as e:
                logger.error(f"Failed to delete post: {e}")
                raise

    async def get_post_analytics(self, post_id: UUID) -> dict[str, any]:
        """Holt Engagement-Analytics für einen Post"""
        async with self.session_factory() as session:
            stmt = select(SocialPost).where(SocialPost.id == post_id)
            result = await session.execute(stmt)
            post = result.scalar_one()

            if not post.platform_post_id:
                return {}

            # Hole Provider
            provider = self.providers.get(post.platform)
            if not provider:
                return {}

            # Lade Account
            stmt = select(SocialMediaAccount).where(SocialMediaAccount.id == post.account_id)
            result = await session.execute(stmt)
            account = result.scalar_one()

            try:
                await provider.authenticate(account)
                stats = await provider.get_post_stats(post.platform_post_id, account)

                # Update Post mit Stats
                post.like_count = stats.get("like_count", 0)
                post.share_count = stats.get("share_count", 0)
                post.comment_count = stats.get("comment_count", 0)
                post.impression_count = stats.get("impression_count", 0)

                # Berechne Engagement Rate
                if post.impression_count > 0:
                    total_engagement = post.like_count + post.share_count + post.comment_count
                    post.engagement_rate = (total_engagement / post.impression_count) * 100

                await self._update_post(session, post)

                return {
                    "likes": post.like_count,
                    "shares": post.share_count,
                    "comments": post.comment_count,
                    "impressions": post.impression_count,
                    "engagement_rate": round(post.engagement_rate, 2),
                }

            except Exception as e:
                logger.error(f"Failed to get analytics: {e}")
                return {}

    async def connect_account(
        self, platform: SocialPlatform, access_token: str, refresh_token: str | None, user_id: UUID
    ) -> SocialMediaAccount:
        """Verbindet ein Social Media Konto mit der Plattform"""
        async with self.session_factory() as session:
            # Prüfe ob bereits verbunden
            stmt = select(SocialMediaAccount).where(
                SocialMediaAccount.platform == platform, SocialMediaAccount.created_by == user_id
            )
            result = await session.execute(stmt)

            existing = result.scalar_one_or_none()
            if existing:
                # Update bestehendes Konto
                existing.access_token = access_token
                existing.refresh_token = refresh_token
                existing.updated_at = datetime.now(UTC)
                account = existing
            else:
                # Neues Konto
                account = SocialMediaAccount(
                    id=uuid4(),
                    platform=platform,
                    platform_user_id="",  # Wird nach Auth geholt
                    platform_username="",
                    access_token=access_token,
                    refresh_token=refresh_token,
                    created_by=user_id,
                )
                session.add(account)
            # Versuche Authentifizierung um Username zu holen
            provider = self.providers.get(platform)
            if provider:
                try:
                    await provider.authenticate(account)
                    # In Production: Hole User Info
                    account.platform_username = "connected_user"
                except Exception as e:
                    logger.warning(f"Could not fetch username: {e}")

            await session.commit()
            await session.refresh(account)

            return account

    async def get_campaign_report(self, campaign_id: UUID) -> dict[str, any]:
        """Bericht für eine Social Media Kampagne"""
        async with self.session_factory() as session:
            stmt = select(SocialPost).where(SocialPost.campaign_id == campaign_id)
            result = await session.execute(stmt)
            posts = result.scalars().all()

            total_impressions = sum(p.impression_count for p in posts)
            total_engagement = sum(p.like_count + p.share_count + p.comment_count for p in posts)

            return {
                "campaign_id": str(campaign_id),
                "total_posts": len(posts),
                "published_posts": len([p for p in posts if p.status == PostStatus.PUBLISHED]),
                "total_impressions": total_impressions,
                "total_engagement": total_engagement,
                "average_engagement_rate": (
                    (total_engagement / total_impressions * 100) if total_impressions > 0 else 0
                ),
                "posts_by_platform": {
                    platform.value: len([p for p in posts if p.platform == platform])
                    for platform in SocialPlatform
                },
            }

    # ==================== Helper Methods ====================
    async def _get_account(
        self, session: AsyncSession, platform: SocialPlatform, user_id: UUID
    ) -> SocialMediaAccount | None:
        """Holt Social Media Account für User"""
        stmt = select(SocialMediaAccount).where(
            SocialMediaAccount.platform == platform,
            SocialMediaAccount.created_by == user_id,
            SocialMediaAccount.is_active,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _save_post(self, session: AsyncSession, post: SocialPost):
        """Speichert Post in DB"""
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(SocialPost).values(
            id=post.id,
            account_id=post.account_id,
            platform=post.platform.value,
            text=post.text,
            hashtags=post.hashtags,
            mentions=post.mentions,
            link_preview=post.link_preview,
            scheduled_at=post.scheduled_at,
            campaign_id=post.campaign_id,
            project_id=post.project_id,
            created_by=post.created_by,
            status=post.status.value,
            created_at=post.created_at,
        )
        await session.execute(stmt)
        await session.commit()

    async def _update_post(self, session: AsyncSession, post: SocialPost):
        """Updated Post in DB"""
        stmt = (
            update(SocialPost)
            .where(SocialPost.id == post.id)
            .values(
                platform_post_id=post.platform_post_id,
                status=post.status.value,
                published_at=post.published_at,
                like_count=post.like_count,
                share_count=post.share_count,
                comment_count=post.comment_count,
                impression_count=post.impression_count,
                engagement_rate=post.engagement_rate,
                error_message=post.error_message,
                retry_count=post.retry_count,
                updated_at=datetime.now(UTC),
            )
        )
        await session.execute(stmt)
        await session.commit()

    async def _update_account(self, session: AsyncSession, account: SocialMediaAccount):
        """Updated Account in DB"""
        stmt = (
            update(SocialMediaAccount)
            .where(SocialMediaAccount.id == account.id)
            .values(
                access_token=account.access_token,
                refresh_token=account.refresh_token,
                token_expires_at=account.token_expires_at,
                updated_at=datetime.now(UTC),
            )
        )
        await session.execute(stmt)
        await session.commit()


# ==================== Background Worker ====================


class SocialMediaWorker:
    """
    Background Worker für Social Media Posts
    Läuft als separater Celery Task oder asyncio Task
    """

    def __init__(self, social_service: SocialMediaService):
        self.service = social_service
        self.running = True

    async def run(self):
        """Main Worker Loop"""
        logger.info("Social Media Worker started")

        while self.running:
            try:
                # Hole nächsten Post aus Queue
                post_id = await self.service.queue.dequeue()

                if post_id:
                    # Veröffentliche Post
                    await self.service.publish_post(post_id)

                # Warte kurz (Rate Limiting)
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self.running = False
