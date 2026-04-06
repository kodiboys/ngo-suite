# FILE: tests/test_social.py
# MODULE: Social Media Tests
# Unit, Integration & Mock Tests für alle Plattformen

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from src.ports.social_base import (
    CreatePostRequest,
    PostStatus,
    SocialPlatform,
    SocialPost,
)
from src.ports.social_twitter import TwitterProvider
from src.services.social_service import SocialMediaService

# ==================== Unit Tests ====================


@pytest.mark.asyncio
async def test_twitter_post_creation():
    """Test Twitter Post Erstellung"""

    with patch("tweepy.API") as mock_tweepy:
        mock_api = Mock()
        mock_tweet = Mock()
        mock_tweet.id = 123456789
        mock_api.update_status.return_value = mock_tweet
        mock_tweepy.return_value = mock_api

        provider = TwitterProvider("id", "secret", "bearer")

        post = SocialPost(
            id=uuid4(),
            account_id=uuid4(),
            platform=SocialPlatform.TWITTER,
            text="Test tweet",
            hashtags=["test", "twitter"],
            status=PostStatus.PENDING,
        )

        result = await provider.post(post)

        assert result.status == PostStatus.PUBLISHED
        assert result.platform_post_id == "123456789"
        assert result.published_at is not None


@pytest.mark.asyncio
async def test_post_validation():
    """Test Post Validation (Längenlimits)"""

    # Twitter: Max 280 chars
    with pytest.raises(ValueError):
        request = CreatePostRequest(text="x" * 300, platform=SocialPlatform.TWITTER, hashtags=[])

    # Instagram: Max 2200 chars
    with pytest.raises(ValueError):
        request = CreatePostRequest(text="x" * 2300, platform=SocialPlatform.INSTAGRAM, hashtags=[])

    # Gültiger Post
    request = CreatePostRequest(
        text="Valid post", platform=SocialPlatform.LINKEDIN, hashtags=["valid"]
    )
    assert request.text == "Valid post"


@pytest.mark.asyncio
async def test_social_queue():
    """Test Social Media Queue"""
    import fakeredis.aioredis

    from src.ports.social_base import SocialMediaQueue

    redis_client = await fakeredis.aioredis.create_redis_pool()
    queue = SocialMediaQueue(redis_client)

    post_id = uuid4()

    # Enqueue
    await queue.enqueue(post_id, priority=1)

    # Dequeue
    dequeued = await queue.dequeue()
    assert dequeued == post_id

    # Queue sollte leer sein
    assert await queue.get_queue_length() == 0


# ==================== Integration Tests ====================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_social_workflow(db_session, redis_client):
    """Test vollständigen Social Media Workflow"""

    from src.core.events.event_bus import EventBus

    event_bus = EventBus(redis_client, db_session)
    service = SocialMediaService(db_session, redis_client, event_bus)

    # 1. Create Post
    request = CreatePostRequest(
        text="Integration test post",
        platform=SocialPlatform.TWITTER,
        hashtags=["integration", "test"],
    )

    post = await service.create_post(request, uuid4())
    assert post.id is not None
    assert post.status == PostStatus.DRAFT

    # 2. Queue Post
    await service.queue.enqueue(post.id, priority=1)

    # 3. Publish Post (Mocked)
    with patch.object(service.providers[SocialPlatform.TWITTER], "post") as mock_post:
        mock_post.return_value = post
        mock_post.return_value.status = PostStatus.PUBLISHED

        published = await service.publish_post(post.id)
        assert published.status == PostStatus.PUBLISHED

    # 4. Get Analytics
    with patch.object(service.providers[SocialPlatform.TWITTER], "get_post_stats") as mock_stats:
        mock_stats.return_value = {"like_count": 10, "retweet_count": 5, "impression_count": 1000}

        analytics = await service.get_post_analytics(post.id)
        assert analytics["likes"] == 10


# ==================== Property-Based Tests ====================

from hypothesis import given
from hypothesis import strategies as st


@given(
    text=st.text(min_size=1, max_size=280),
    hashtags=st.lists(st.text(min_size=1, max_size=20), max_size=5),
)
def test_tweet_formatting(text, hashtags):
    """Test: Tweet Formatierung mit Hashtags"""
    post = SocialPost(
        id=uuid4(),
        account_id=uuid4(),
        platform=SocialPlatform.TWITTER,
        text=text,
        hashtags=hashtags,
        status=PostStatus.DRAFT,
    )

    # Simuliere Formatierung
    formatted = text
    if hashtags:
        formatted += " " + " ".join([f"#{tag}" for tag in hashtags])

    assert len(formatted) <= 280 or text == formatted


# ==================== Performance Tests ====================


@pytest.mark.benchmark
def test_post_serialization(benchmark):
    """Benchmark: Post Serialisierung"""

    post = SocialPost(
        id=uuid4(),
        account_id=uuid4(),
        platform=SocialPlatform.TWITTER,
        text="Test post for benchmarking" * 10,
        hashtags=["benchmark", "test", "performance"],
        status=PostStatus.DRAFT,
    )

    def serialize():
        import json
        from dataclasses import asdict

        return json.dumps(asdict(post), default=str)

    result = benchmark(serialize)
    assert "benchmark" in result
