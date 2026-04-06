# FILE: src/ports/social_linkedin.py
# MODULE: LinkedIn Social Media Provider Implementation
# LinkedIn API v2 für Company Pages & Personal Profiles

import logging
from datetime import datetime

import httpx

from src.ports.social_base import (
    MediaAttachment,
    PostStatus,
    SocialMediaAccount,
    SocialPost,
    SocialProviderInterface,
)

logger = logging.getLogger(__name__)


class LinkedInProvider(SocialProviderInterface):
    """
    LinkedIn Provider Implementation
    Features:
    - Post auf Company Page
    - Post auf Personal Profile
    - Article Posts
    - Image/Video Posts
    - Analytics via LinkedIn API
    """

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.client = None

    async def authenticate(self, account: SocialMediaAccount) -> bool:
        """Authentifiziert sich mit OAuth 2.0"""
        try:
            self.access_token = account.access_token
            self.client = httpx.AsyncClient(timeout=30.0)

            # Teste Authentifizierung
            response = await self.client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"LinkedIn authentication failed: {e}")
            return False

    async def post(self, post: SocialPost) -> SocialPost:
        """Veröffentlicht Post auf LinkedIn"""
        try:
            if not self.client:
                await self.authenticate(post.account_id)

            # Hole Author URN (Person oder Company)
            author_urn = await self._get_author_urn(post.account_id)

            # Erstelle Post
            post_data = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": post.text},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }

            # Füge Medien hinzu
            if post.media:
                media_urns = []
                for media in post.media:
                    media_urn = await self.upload_media(media, None)
                    media_urns.append(media_urn)

                post_data["specificContent"]["com.linkedin.ugc.ShareContent"][
                    "shareMediaCategory"
                ] = "IMAGE"
                post_data["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                    {"status": "READY", "media": media_urn} for media_urn in media_urns
                ]

            # Post erstellen
            response = await self.client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                json=post_data,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()

            result = response.json()
            post.platform_post_id = result["id"]
            post.status = PostStatus.PUBLISHED
            post.published_at = datetime.utcnow()

            logger.info(f"LinkedIn post published: {result['id']}")
            return post

        except Exception as e:
            logger.error(f"LinkedIn post failed: {e}")
            post.status = PostStatus.FAILED
            post.error_message = str(e)
            raise

    async def delete_post(self, platform_post_id: str, account: SocialMediaAccount) -> bool:
        """Löscht LinkedIn Post"""
        try:
            await self.authenticate(account)

            response = await self.client.delete(
                f"https://api.linkedin.com/v2/ugcPosts/{platform_post_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )

            return response.status_code == 204

        except Exception as e:
            logger.error(f"Failed to delete LinkedIn post: {e}")
            return False

    async def get_post_stats(
        self, platform_post_id: str, account: SocialMediaAccount
    ) -> dict[str, int]:
        """Holt LinkedIn Post Analytics"""
        try:
            await self.authenticate(account)

            response = await self.client.get(
                f"https://api.linkedin.com/v2/socialActions/{platform_post_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            response.raise_for_status()

            data = response.json()

            return {
                "like_count": data.get("likesSummary", {}).get("totalLikes", 0),
                "comment_count": data.get("commentsSummary", {}).get("totalComments", 0),
                "share_count": data.get("sharesSummary", {}).get("totalShares", 0),
                "impression_count": 0,  # Erfordert spezielle Insights API
            }

        except Exception as e:
            logger.error(f"Failed to get LinkedIn stats: {e}")
            return {}

    async def upload_media(self, media: MediaAttachment, account: SocialMediaAccount) -> str:
        """Upload von Bildern zu LinkedIn"""
        try:
            # 1. Register Upload
            register_response = await self.client.post(
                "https://api.linkedin.com/v2/assets?action=registerUpload",
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": await self._get_author_urn(account.id),
                        "serviceRelationships": [
                            {
                                "relationshipType": "OWNER",
                                "identifier": "urn:li:userGeneratedContent",
                            }
                        ],
                    }
                },
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            register_response.raise_for_status()
            upload_data = register_response.json()

            upload_url = upload_data["value"]["uploadMechanism"][
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
            ]["uploadUrl"]
            asset_urn = upload_data["value"]["asset"]

            # 2. Upload Media
            if media.file_bytes:
                upload_response = await self.client.put(
                    upload_url, content=media.file_bytes, headers={"Content-Type": "image/jpeg"}
                )
            elif media.url:
                async with httpx.AsyncClient() as http_client:
                    media_response = await http_client.get(media.url)
                    upload_response = await self.client.put(
                        upload_url,
                        content=media_response.content,
                        headers={"Content-Type": "image/jpeg"},
                    )
            else:
                raise ValueError("No media data provided")

            upload_response.raise_for_status()

            return asset_urn

        except Exception as e:
            logger.error(f"LinkedIn media upload failed: {e}")
            raise

    async def refresh_token(self, account: SocialMediaAccount) -> SocialMediaAccount:
        """Erneuert LinkedIn Access Token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": account.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )

            if response.status_code == 200:
                data = response.json()
                account.access_token = data["access_token"]
                if "refresh_token" in data:
                    account.refresh_token = data["refresh_token"]
                account.token_expires_at = datetime.utcnow().replace(
                    hour=datetime.utcnow().hour + (data.get("expires_in", 5184000) / 3600)
                )
            else:
                raise Exception(f"Token refresh failed: {response.text}")

        return account

    async def _get_author_urn(self, account_id: UUID) -> str:
        """Holt Author URN (Person oder Company)"""
        # In Production: Aus Account Metadata
        return "urn:li:person:your_linkedin_id"
