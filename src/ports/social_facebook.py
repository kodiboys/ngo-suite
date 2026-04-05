# FILE: src/ports/social_facebook.py
# MODULE: Facebook & Instagram Social Media Provider Implementation
# Meta Graph API Integration für Pages, Groups, Instagram Business

import json
import logging
from datetime import datetime
from typing import Any

import facebook
import httpx

from src.ports.social_base import (
    MediaAttachment,
    MediaType,
    PostStatus,
    SocialMediaAccount,
    SocialPlatform,
    SocialPost,
    SocialProviderInterface,
)

logger = logging.getLogger(__name__)

class FacebookProvider(SocialProviderInterface):
    """
    Facebook & Instagram Provider (Meta Graph API)
    Features:
    - Post auf Facebook Page
    - Post auf Instagram Business Account
    - Carousel Posts
    - Story Posts
    - Analytics via Graph API
    """

    def __init__(self, app_id: str, app_secret: str, api_version: str = "v18.0"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_version = api_version
        self.graph = None
        self.page_access_token = None

    async def authenticate(self, account: SocialMediaAccount) -> bool:
        """Authentifiziert sich mit Facebook Page Access Token"""
        try:
            self.graph = facebook.GraphAPI(access_token=account.access_token, version=self.api_version)

            # Teste Zugriff
            profile = self.graph.get_object('me')
            return 'id' in profile

        except Exception as e:
            logger.error(f"Facebook authentication failed: {e}")
            return False

    async def post(self, post: SocialPost) -> SocialPost:
        """Veröffentlicht Post auf Facebook Page oder Instagram"""
        try:
            if not self.graph:
                await self.authenticate(post.account_id)

            # Plattform-spezifische Posts
            if post.platform == SocialPlatform.FACEBOOK:
                result = await self._post_to_facebook(post)
            elif post.platform == SocialPlatform.INSTAGRAM:
                result = await self._post_to_instagram(post)
            else:
                raise ValueError(f"Unsupported platform: {post.platform}")

            post.platform_post_id = result['id']
            post.status = PostStatus.PUBLISHED
            post.published_at = datetime.utcnow()

            return post

        except Exception as e:
            logger.error(f"Facebook post failed: {e}")
            post.status = PostStatus.FAILED
            post.error_message = str(e)
            raise

    async def _post_to_facebook(self, post: SocialPost) -> dict[str, Any]:
        """Post auf Facebook Page"""
        # Formatiere Post
        message = self._format_facebook_post(post)

        # Hole Page ID aus Account Metadata
        page_id = post.account_id.metadata.get('page_id')

        if not page_id:
            # Hole Pages des Users
            pages = self.graph.get_object('me/accounts')
            if pages['data']:
                page_id = pages['data'][0]['id']

        # Post mit Medien
        if post.media:
            # Upload Medien zuerst
            media_ids = []
            for media in post.media:
                media_id = await self.upload_media(media, None)
                media_ids.append(media_id)

            # Post mit mehreren Bildern (Carousel)
            if len(media_ids) > 1:
                result = self.graph.put_object(
                    parent_object=page_id,
                    connection_name='feed',
                    message=message,
                    attached_media=json.dumps([
                        {'media_fbid': media_id} for media_id in media_ids
                    ])
                )
            else:
                result = self.graph.put_object(
                    parent_object=page_id,
                    connection_name='feed',
                    message=message,
                    attached_media=media_ids[0] if media_ids else None
                )
        else:
            # Text-only Post
            result = self.graph.put_object(
                parent_object=page_id,
                connection_name='feed',
                message=message
            )

        return result

    async def _post_to_instagram(self, post: SocialPost) -> dict[str, Any]:
        """Post auf Instagram Business Account"""
        # Instagram benötigt ein Bild/Video
        if not post.media:
            raise ValueError("Instagram posts require media (image or video)")

        # Hole Instagram Business Account ID
        ig_business_id = post.account_id.metadata.get('instagram_business_id')

        if not ig_business_id:
            # Hole von Facebook Page
            page_id = post.account_id.metadata.get('page_id')
            page_info = self.graph.get_object(
                f"{page_id}",
                fields='instagram_business_account'
            )
            if 'instagram_business_account' in page_info:
                ig_business_id = page_info['instagram_business_account']['id']

        # Upload Container
        media = post.media[0]
        container_data = {
            'media_type': 'IMAGE' if media.type == MediaType.IMAGE else 'VIDEO',
            'caption': self._format_instagram_caption(post)
        }

        if media.url:
            container_data['image_url'] = media.url
        elif media.file_bytes:
            # Upload zu Facebook Servers (vereinfacht)
            # In Production: Zuerst zu Facebook hochladen
            pass

        # Create Container
        container = self.graph.put_object(
            parent_object=ig_business_id,
            connection_name='media',
            **container_data
        )

        # Publish Container
        result = self.graph.post_object(
            parent_object=ig_business_id,
            connection_name='media_publish',
            creation_id=container['id']
        )

        return result

    async def delete_post(self, platform_post_id: str, account: SocialMediaAccount) -> bool:
        """Löscht Facebook/Instagram Post"""
        try:
            await self.authenticate(account)
            result = self.graph.delete_object(platform_post_id)
            return result is True
        except Exception as e:
            logger.error(f"Failed to delete post: {e}")
            return False

    async def get_post_stats(self, platform_post_id: str, account: SocialMediaAccount) -> dict[str, int]:
        """Holt Post Analytics (Likes, Shares, Comments)"""
        try:
            await self.authenticate(account)

            # Hole Insights via Graph API
            insights = self.graph.get_object(
                f"{platform_post_id}/insights",
                metric='post_impressions,post_reactions_like_total,post_shares,post_comments'
            )

            stats = {
                'like_count': 0,
                'share_count': 0,
                'comment_count': 0,
                'impression_count': 0
            }

            for insight in insights.get('data', []):
                if insight['name'] == 'post_reactions_like_total':
                    stats['like_count'] = insight['values'][0]['value']
                elif insight['name'] == 'post_shares':
                    stats['share_count'] = insight['values'][0]['value']
                elif insight['name'] == 'post_comments':
                    stats['comment_count'] = insight['values'][0]['value']
                elif insight['name'] == 'post_impressions':
                    stats['impression_count'] = insight['values'][0]['value']

            return stats

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}

    async def upload_media(self, media: MediaAttachment, account: SocialMediaAccount) -> str:
        """Upload von Medien zu Facebook (für Posts)"""
        # Facebook benötigt zuerst einen Media Upload
        # Vereinfacht: Return URL (wird von Facebook gehandhabt)
        return media.url or "media_id_placeholder"

    async def refresh_token(self, account: SocialMediaAccount) -> SocialMediaAccount:
        """Erneuert Facebook Long-Lived Token"""

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://graph.facebook.com/v18.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.app_id,
                    "client_secret": self.app_secret,
                    "fb_exchange_token": account.refresh_token or account.access_token
                }
            )

            if response.status_code == 200:
                data = response.json()
                account.access_token = data['access_token']
                account.token_expires_at = datetime.utcnow().replace(
                    hour=datetime.utcnow().hour + (data.get('expires_in', 5184000) / 3600)
                )
            else:
                raise Exception(f"Token refresh failed: {response.text}")

        return account

    def _format_facebook_post(self, post: SocialPost) -> str:
        """Formatiert Facebook Post"""
        text = post.text

        # Hashtags
        if post.hashtags:
            text += '\n\n' + ' '.join([f'#{tag}' for tag in post.hashtags])

        # Link Preview
        if post.link_preview:
            text += f'\n\n{post.link_preview}'

        return text

    def _format_instagram_caption(self, post: SocialPost) -> str:
        """Formatiert Instagram Caption (Hashtags + Mentions)"""
        caption = post.text

        # Hashtags (max 30)
        if post.hashtags:
            caption += '\n\n' + ' '.join([f'#{tag}' for tag in post.hashtags[:30]])

        # Mentions
        if post.mentions:
            caption += '\n' + ' '.join([f'@{mention}' for mention in post.mentions])

        # Limit 2200 chars
        return caption[:2200]
