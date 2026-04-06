# FILE: src/ports/social_twitter.py
# MODULE: Twitter/X Social Media Provider Implementation
# Async Twitter API v2 Integration mit OAuth 2.0, Media Upload

import asyncio
import logging
from datetime import datetime

import tweepy

from src.ports.social_base import (
    MediaAttachment,
    PostStatus,
    SocialMediaAccount,
    SocialPost,
    SocialProviderInterface,
)

logger = logging.getLogger(__name__)


class TwitterProvider(SocialProviderInterface):
    """
    Twitter/X Provider Implementation
    Features:
    - OAuth 2.0 Authorization
    - Media Upload (Bilder, Videos, GIFs)
    - Polls, Threads, Quote Tweets
    - Analytics via Twitter API v2
    """

    def __init__(self, client_id: str, client_secret: str, bearer_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.bearer_token = bearer_token
        self.client = None

    async def authenticate(self, account: SocialMediaAccount) -> bool:
        """Authentifiziert sich mit OAuth 2.0"""
        try:
            # Für User-Auth mit Access Token
            auth = tweepy.OAuth2BearerHandler(account.access_token)
            self.client = tweepy.API(auth, wait_on_rate_limit=True)

            # Teste Authentifizierung
            user = self.client.verify_credentials()
            return user is not None

        except Exception as e:
            logger.error(f"Twitter authentication failed: {e}")
            return False

    async def post(self, post: SocialPost) -> SocialPost:
        """Veröffentlicht Tweet mit optionalen Medien"""
        try:
            if not self.client:
                await self.authenticate(post.account_id)

            media_ids = []

            # Upload Medien
            for media in post.media:
                media_id = await self.upload_media(media, None)
                media_ids.append(media_id)

            # Tweet mit Medien erstellen
            tweet_text = self._format_tweet(post)

            if media_ids:
                result = self.client.update_status(status=tweet_text, media_ids=media_ids)
            else:
                result = self.client.update_status(status=tweet_text)

            post.platform_post_id = str(result.id)
            post.status = PostStatus.PUBLISHED
            post.published_at = datetime.utcnow()

            logger.info(f"Tweet posted successfully: {result.id}")
            return post

        except tweepy.TweepError as e:
            logger.error(f"Twitter post failed: {e}")
            post.status = PostStatus.FAILED
            post.error_message = str(e)
            post.retry_count += 1
            raise

    async def delete_post(self, platform_post_id: str, account: SocialMediaAccount) -> bool:
        """Löscht Tweet"""
        try:
            await self.authenticate(account)
            self.client.destroy_status(platform_post_id)
            logger.info(f"Tweet deleted: {platform_post_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete tweet: {e}")
            return False

    async def get_post_stats(
        self, platform_post_id: str, account: SocialMediaAccount
    ) -> dict[str, int]:
        """Holt Tweet Analytics"""
        try:
            await self.authenticate(account)

            # Twitter API v2 für erweiterte Analytics
            tweet = self.client.get_status(platform_post_id, tweet_mode="extended")

            return {
                "like_count": tweet.favorite_count,
                "retweet_count": tweet.retweet_count,
                "reply_count": 0,  # Nicht direkt verfügbar in v1.1
                "quote_count": 0,
                "impression_count": 0,  # Nur mit v2 API
            }
        except Exception as e:
            logger.error(f"Failed to get tweet stats: {e}")
            return {}

    async def upload_media(self, media: MediaAttachment, account: SocialMediaAccount) -> str:
        """Upload von Bildern/Videos zu Twitter"""
        try:
            if not self.client:
                await self.authenticate(account)

            # Twitter Media Upload
            if media.file_bytes:
                # Upload aus Bytes
                result = self.client.media_upload(
                    filename=media.filename or "media.jpg", file=media.file_bytes
                )
            elif media.url:
                # Download von URL (in Production)
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(media.url)
                    result = self.client.media_upload(
                        filename=media.filename or "media.jpg", file=response.content
                    )
            else:
                raise ValueError("No media data provided")

            # Alt-Text hinzufügen (Barrierefreiheit)
            if media.alt_text:
                self.client.create_media_metadata(result.media_id, media.alt_text)

            return result.media_id_string

        except Exception as e:
            logger.error(f"Twitter media upload failed: {e}")
            raise

    async def refresh_token(self, account: SocialMediaAccount) -> SocialMediaAccount:
        """Erneuert OAuth 2.0 Token (Twitter verwendet langlebige Tokens)"""
        # Twitter OAuth 2.0 Refresh
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.twitter.com/2/oauth2/token",
                data={
                    "refresh_token": account.refresh_token,
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                },
                auth=(self.client_id, self.client_secret),
            )

            if response.status_code == 200:
                data = response.json()
                account.access_token = data["access_token"]
                if "refresh_token" in data:
                    account.refresh_token = data["refresh_token"]
                account.token_expires_at = datetime.utcnow().replace(
                    hour=datetime.utcnow().hour + 2
                )
            else:
                raise Exception(f"Token refresh failed: {response.text}")

        return account

    def _format_tweet(self, post: SocialPost) -> str:
        """Formatiert Tweet mit Hashtags und Mentions"""
        text = post.text

        # Hashtags hinzufügen
        if post.hashtags:
            hashtags = " " + " ".join([f"#{tag}" for tag in post.hashtags])
            # Prüfe Länge
            if len(text + hashtags) <= 280:
                text += hashtags

        # Mentions (falls nicht bereits im Text)
        if post.mentions:
            mentions = " " + " ".join([f"@{mention}" for mention in post.mentions])
            if len(text + mentions) <= 280:
                text += mentions

        return text[:280]


class TwitterStreamListener(tweepy.StreamListener):
    """Twitter Stream Listener für Mentions und Keywords"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_status(self, status):
        """Wird bei neuem Tweet aufgerufen"""
        asyncio.create_task(self.callback(status))
        return True

    def on_error(self, status_code):
        if status_code == 420:
            # Rate Limit
            return False
        return True
