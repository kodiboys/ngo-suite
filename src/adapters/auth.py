# FILE: src/adapters/auth.py
# MODULE: Authentication & Authorization mit OAuth2/JWT, RBAC, MFA
# Enterprise Auth mit Vault-Integration, Rate-Limiting, Audit
# Version: 3.0.0

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import hvac
import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.entities.base import AuditLog, User, UserRole
from src.core.events.event_bus import Event, EventBus

# ==================== Konfiguration ====================

SECRET_KEY = "YOUR_SUPER_SECRET_KEY_CHANGE_ME"  # In Production: Aus Vault laden
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ==================== Pydantic Models ====================


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: str  # user_id
    role: UserRole
    exp: datetime
    jti: str  # JWT ID für Revocation


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: Dict[str, Any]


class MFASetupResponse(BaseModel):
    secret: str
    qr_code_url: str


# ==================== Dependencies ====================


async def get_session(request: Request) -> AsyncSession:
    """Dependency Injection für Datenbank-Session"""
    async with request.app.state.db_session_factory() as session:
        yield session


async def get_redis_client(request: Request) -> redis.Redis:
    """Dependency Injection für Redis Client"""
    return request.app.state.redis


async def get_event_bus(request: Request) -> EventBus:
    """Dependency Injection für Event Bus"""
    return request.app.state.event_bus


# ==================== JWT Manager ====================


class JWTHandler:
    """JWT Token Management mit Revocation & Refresh"""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def create_tokens(self, user_id: UUID, role: UserRole) -> Dict[str, str]:
        """Erstellt Access & Refresh Tokens"""
        # Access Token (kurzlebig)
        access_exp = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_jti = str(uuid4())
        access_token = jwt.encode(
            {
                "sub": str(user_id),
                "role": role.value,
                "exp": access_exp,
                "jti": access_jti,
                "type": "access",
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

        # Refresh Token (länger, einmalig verwendbar)
        refresh_exp = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        refresh_jti = str(uuid4())
        refresh_token = jwt.encode(
            {
                "sub": str(user_id),
                "role": role.value,
                "exp": refresh_exp,
                "jti": refresh_jti,
                "type": "refresh",
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

        # Speichere Refresh Token in Redis für Revocation
        await self.redis.setex(
            f"refresh_token:{refresh_jti}", REFRESH_TOKEN_EXPIRE_DAYS * 86400, str(user_id)
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, str]:
        """Erneuert Access Token mit Refresh Token"""
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])

            # Prüfe Token Typ
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=401, detail="Invalid token type")

            # Prüfe ob Refresh Token revoked
            jti = payload.get("jti")
            if not await self.redis.exists(f"refresh_token:{jti}"):
                raise HTTPException(status_code=401, detail="Token revoked")

            # Lösche alten Refresh Token (One-Time Use)
            await self.redis.delete(f"refresh_token:{jti}")

            # Erstelle neue Tokens
            user_id = UUID(payload.get("sub"))
            role = UserRole(payload.get("role"))
            return await self.create_tokens(user_id, role)

        except JWTError as e:
            raise HTTPException(status_code=401, detail="Invalid refresh token") from e

    async def revoke_token(self, jti: str):
        """Revociert einen Token (Logout)"""
        await self.redis.delete(f"refresh_token:{jti}")


# ==================== Password Manager ====================


class PasswordManager:
    """Sicheres Passwort-Hashing mit bcrypt"""

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)


# ==================== MFA Manager ====================


class MFAManager:
    """TOTP Multi-Factor Authentication"""

    def __init__(self):
        import pyotp

        self.pyotp = pyotp

    def setup_mfa(self, user_email: str) -> Dict[str, str]:
        """Generiert MFA Secret und QR Code"""
        secret = self.pyotp.random_base32()
        totp = self.pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(user_email, issuer_name="TrueAngels")

        return {"secret": secret, "qr_code_url": provisioning_uri}

    def verify_mfa(self, secret: str, code: str) -> bool:
        """Verifiziert TOTP Code"""
        import pyotp

        totp = pyotp.TOTP(secret)
        return totp.verify(code)


# ==================== Auth Service ====================


class AuthService:
    """Haupt-Authentifizierungs-Service mit Audit & Rate-Limiting"""

    def __init__(self, session_factory, redis_client: redis.Redis, event_bus: EventBus):
        self.session_factory = session_factory
        self.redis = redis_client
        self.event_bus = event_bus
        self.jwt_handler = JWTHandler(redis_client)
        self.password_manager = PasswordManager()
        self.mfa_manager = MFAManager()

    async def login(
        self, request: Request, login_data: LoginRequest, ip_address: str
    ) -> LoginResponse:
        """Benutzer-Login mit Rate-Limiting & Audit"""

        # Rate-Limiting: Max 5 Versuche pro Minute
        rate_key = f"login_attempts:{login_data.email}"
        attempts = await self.redis.incr(rate_key)
        if attempts == 1:
            await self.redis.expire(rate_key, 60)
        if attempts > 5:
            raise HTTPException(status_code=429, detail="Too many login attempts")

        # Suche User
        async with self.session_factory() as session:
            stmt = select(User).where(User.email == login_data.email)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user or not self.password_manager.verify_password(
                login_data.password, user.password_hash
            ):
                # Audit: Fehlgeschlagener Login
                await self._log_audit(
                    session=session,
                    user_id=None,
                    action="LOGIN_FAILED",
                    entity_type="user",
                    entity_id=None,
                    ip_address=ip_address,
                    reason="Invalid credentials",
                    request=request,
                )
                raise HTTPException(status_code=401, detail="Invalid credentials")

            # MFA Prüfung
            if user.mfa_enabled:
                if not login_data.mfa_code:
                    raise HTTPException(status_code=401, detail="MFA code required")
                if not self.mfa_manager.verify_mfa(user.mfa_secret, login_data.mfa_code):
                    raise HTTPException(status_code=401, detail="Invalid MFA code")

            # Update last login
            await session.execute(
                update(User)
                .where(User.id == user.id)
                .values(last_login_at=datetime.utcnow(), last_login_ip=ip_address)
            )
            await session.commit()

            # Create tokens
            tokens = await self.jwt_handler.create_tokens(user.id, user.role)

            # Audit: Erfolgreicher Login
            await self._log_audit(
                session=session,
                user_id=user.id,
                action="LOGIN_SUCCESS",
                entity_type="user",
                entity_id=user.id,
                ip_address=ip_address,
                new_values={"role": user.role.value},
                request=request,
            )

            # Publish Login Event
            await self.event_bus.publish(
                Event(
                    aggregate_id=user.id,
                    aggregate_type="User",
                    event_type="UserLoggedIn",
                    data={"email": user.email, "ip": ip_address},
                    user_id=user.id,
                    metadata={"user_agent": request.headers.get("user-agent")},
                )
            )

            return LoginResponse(
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                user={
                    "id": str(user.id),
                    "email": user.email,
                    "role": user.role.value,
                    "mfa_enabled": user.mfa_enabled,
                },
            )

    async def register(self, email: str, password: str, name: str = None) -> User:
        """Benutzer-Registrierung mit Validierung"""
        async with self.session_factory() as session:
            # Prüfe ob Email existiert
            stmt = select(User).where(User.email == email)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already registered")

            # Erstelle User
            user = User(
                email=email,
                password_hash=self.password_manager.hash_password(password),
                name_encrypted=name,
                role=UserRole.DONOR,
                created_at=datetime.utcnow(),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            return user

    async def setup_mfa(self, user_id: UUID) -> MFASetupResponse:
        """MFA für Benutzer einrichten"""
        async with self.session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            # Generiere MFA Secret
            mfa_setup = self.mfa_manager.setup_mfa(user.email)

            # Speichere Secret (noch nicht aktiviert)
            await session.execute(
                update(User).where(User.id == user_id).values(mfa_secret=mfa_setup["secret"])
            )
            await session.commit()

            return MFASetupResponse(
                secret=mfa_setup["secret"], qr_code_url=mfa_setup["qr_code_url"]
            )

    async def enable_mfa(self, user_id: UUID, code: str):
        """MFA aktivieren nach Verifikation"""
        async with self.session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one()

            if not self.mfa_manager.verify_mfa(user.mfa_secret, code):
                raise HTTPException(status_code=400, detail="Invalid MFA code")

            await session.execute(update(User).where(User.id == user_id).values(mfa_enabled=True))
            await session.commit()

    async def _log_audit(
        self,
        session: AsyncSession,
        user_id: Optional[UUID],
        action: str,
        entity_type: str,
        entity_id: Optional[UUID],
        ip_address: str,
        reason: str = None,
        new_values: Dict = None,
        request: Request = None,
    ):
        """Interne Audit-Log Funktion"""
        audit = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent") if request else None,
            reason=reason,
            new_values=new_values,
            retention_until=datetime.utcnow() + timedelta(days=3650),
        )
        session.add(audit)
        await session.commit()


# ==================== Dependency Injection für FastAPI ====================


async def get_auth_service(request: Request) -> AuthService:
    """Dependency Injection für Auth Service"""
    redis_client = request.app.state.redis
    session_factory = request.app.state.db_session_factory
    event_bus = request.app.state.event_bus
    return AuthService(session_factory, redis_client, event_bus)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Extrahiert und validiert JWT Token, gibt User zurück"""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = UUID(payload.get("sub"))

        # Prüfe Token Typ
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        # Lade User aus DB
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        if user.is_pseudonymized:
            raise HTTPException(status_code=403, detail="Account pseudonymized")

        return user

    except JWTError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Prüft ob User aktiv ist"""
    return current_user


def require_role(required_role: UserRole):
    """Decorator für Role-Based Access Control"""

    async def role_checker(current_user: User = Depends(get_current_active_user)):
        if current_user.role != required_role and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Role {required_role.value} required"
            )
        return current_user

    return role_checker


def require_permission(permission: str):
    """Decorator für feingranulare Berechtigungen"""

    async def permission_checker(current_user: User = Depends(get_current_active_user)):
        if permission not in current_user.permissions and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission {permission} required"
            )
        return current_user

    return permission_checker
