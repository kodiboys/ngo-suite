# FILE: src/adapters/api_social.py
# MODULE: Social Media API Endpoints (FastAPI)
# REST Endpoints für Posts, Analytics, Account Management

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from src.adapters.auth import get_current_active_user, require_role
from src.core.entities.base import User, UserRole
from src.ports.social_base import CreatePostRequest, PostResponse, SocialPlatform
from src.services.social_service import SocialMediaService, SocialMediaWorker

router = APIRouter(prefix="/api/v1/social", tags=["social"])


# ==================== Dependency ====================


async def get_social_service(request: Request) -> SocialMediaService:
    """Dependency Injection für Social Media Service"""
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return SocialMediaService(session_factory, redis_client, event_bus)


# ==================== Post Management ====================


@router.post("/posts", response_model=PostResponse)
async def create_post(
    request: Request,
    post_request: CreatePostRequest,
    background_tasks: BackgroundTasks,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
):
    """
    Erstellt neuen Social Media Post
    Kann sofort veröffentlicht oder zeitgesteuert werden
    """
    post = await social_service.create_post(post_request, current_user.id)

    # Starte Worker im Hintergrund für sofortige Posts
    if not post_request.scheduled_at:
        worker = SocialMediaWorker(social_service)
        background_tasks.add_task(worker.run_once, post.id)

    return PostResponse(
        id=post.id,
        platform=post.platform,
        text=post.text,
        status=post.status,
        platform_post_id=post.platform_post_id,
        published_at=post.published_at,
        scheduled_at=post.scheduled_at,
        engagement={},
    )


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: UUID,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Löscht veröffentlichten Post von der Plattform"""
    success = await social_service.delete_post(post_id, current_user.id)
    return {"success": success, "message": "Post deleted from platform"}


@router.get("/posts/{post_id}/analytics")
async def get_post_analytics(
    post_id: UUID,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(get_current_active_user),
):
    """Holt Engagement-Analytics für einen Post"""
    analytics = await social_service.get_post_analytics(post_id)
    return analytics


@router.get("/posts/campaign/{campaign_id}/report")
async def get_campaign_report(
    campaign_id: UUID,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
):
    """Bericht für Social Media Kampagne"""
    report = await social_service.get_campaign_report(campaign_id)
    return report


# ==================== Account Management ====================


@router.post("/connect/{platform}")
async def connect_social_account(
    platform: SocialPlatform,
    access_token: str,
    refresh_token: str | None = None,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(get_current_active_user),
):
    """
    Verbindet Social Media Account mit der Plattform
    """
    account = await social_service.connect_account(
        platform=platform,
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=current_user.id,
    )

    return {
        "id": str(account.id),
        "platform": account.platform.value,
        "username": account.platform_username,
        "connected_at": account.created_at.isoformat(),
    }


@router.get("/accounts")
async def get_connected_accounts(
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(get_current_active_user),
):
    """Listet alle verbundenen Social Media Accounts"""
    accounts = await social_service.get_user_accounts(current_user.id)
    return [
        {
            "id": str(a.id),
            "platform": a.platform.value,
            "username": a.platform_username,
            "is_active": a.is_active,
        }
        for a in accounts
    ]


# ==================== Post Templates ====================


@router.post("/templates/donation-thank-you")
async def post_donation_thank_you(
    donation_id: UUID,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
):
    """
    Automatischer Dankes-Post für Spende
    """
    text = "🎉 Vielen Dank für Ihre großzügige Spende! Mit Ihrer Unterstützung können wir weiterhin helfen. #Danke #TrueAngels"

    post_request = CreatePostRequest(
        text=text, platform=SocialPlatform.TWITTER, hashtags=["Danke", "TrueAngels", "Spende"]
    )

    post = await social_service.create_post(post_request, current_user.id)

    return {"post_id": post.id, "message": "Thank you post created"}


@router.post("/templates/project-update")
async def post_project_update(
    project_id: UUID,
    social_service: SocialMediaService = Depends(get_social_service),
    current_user: User = Depends(require_role(UserRole.PROJECT_MANAGER)),
):
    """
    Automatisches Projekt-Update
    """
    text = "📊 Fortschrittsupdate unseres Projekts! Wir arbeiten weiter mit voller Kraft. #ProjektUpdate #TrueAngels"

    post_request = CreatePostRequest(
        text=text,
        platform=SocialPlatform.FACEBOOK,
        hashtags=["ProjektUpdate", "TrueAngels", "Hilfe"],
    )

    post = await social_service.create_post(post_request, current_user.id)

    return {"post_id": post.id, "message": "Project update post created"}


# ==================== Webhooks ====================


@router.post("/webhook/twitter")
async def twitter_webhook(
    request: Request, social_service: SocialMediaService = Depends(get_social_service)
):
    """Twitter Webhook für Mentions und Direct Messages"""
    # Verarbeite Mentions, antworte automatisch etc.
    # payload = await request.json()  # Bei Bedarf aktivieren
    return {"received": True}


@router.post("/webhook/facebook")
async def facebook_webhook(
    request: Request, social_service: SocialMediaService = Depends(get_social_service)
):
    """Facebook Webhook für Kommentare und Reactions"""
    # In Production: Automatische Antworten auf Kommentare
    # payload = await request.json()  # Bei Bedarf aktivieren
    return {"received": True}
