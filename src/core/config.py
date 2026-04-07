# FILE: src/core/config.py
# MODULE: Zentrale Konfiguration für TrueAngels NGO Suite
# Lädt Umgebungsvariablen, verwaltet Secrets, stellt Settings bereit

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Zentrale Konfiguration für die TrueAngels NGO Suite.
    Lädt Werte aus .env Datei und Umgebungsvariablen.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # ==================== Basis Konfiguration ====================
    APP_NAME: str = "TrueAngels NGO Suite"
    APP_VERSION: str = "3.0.0"
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production|test)$")
    DEBUG: bool = Field(default=False)
    SECRET_KEY: SecretStr = Field(default=SecretStr("change_me_in_production"))
    
    # ==================== API Konfiguration ====================
    API_V1_PREFIX: str = "/api/v1"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4
    
    # CORS
    CORS_ORIGINS: List[str] = Field(default=[
        "http://localhost:3000",
        "http://localhost:8501",
        "https://angels4ukraine.de",
        "https://www.angels4ukraine.de",
        "https://api.angels4ukraine.de",
        "https://transparenz.angels4ukraine.de"
    ])
    
    # ==================== Datenbank ====================
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "trueangels"
    DB_USER: str = "admin"
    DB_PASSWORD: SecretStr = Field(default=SecretStr("change_me"))
    
    @property
    def DATABASE_URL(self) -> str:
        """PostgreSQL Verbindungs-URL"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD.get_secret_value()}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def DATABASE_URL_ASYNC(self) -> str:
        """Async PostgreSQL Verbindungs-URL"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD.get_secret_value()}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # ==================== Redis ====================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[SecretStr] = None
    REDIS_DB: int = 0
    
    @property
    def REDIS_URL(self) -> str:
        """Redis Verbindungs-URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD.get_secret_value()}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    # ==================== Celery ====================
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_TASK_EAGER_PROPAGATES: bool = False
    
    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def set_celery_broker(cls, v, info):
        if v is None:
            return f"redis://:{info.data.get('REDIS_PASSWORD', '')}@{info.data.get('REDIS_HOST', 'localhost')}:{info.data.get('REDIS_PORT', 6379)}/0"
        return v
    
    # ==================== Stripe ====================
    STRIPE_SECRET_KEY: Optional[SecretStr] = None
    STRIPE_PUBLIC_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[SecretStr] = None
    
    # ==================== PayPal ====================
    PAYPAL_CLIENT_ID: Optional[str] = None
    PAYPAL_CLIENT_SECRET: Optional[SecretStr] = None
    PAYPAL_MODE: str = Field(default="sandbox", pattern="^(sandbox|live)$")
    
    # ==================== Klarna ====================
    KLARNA_USERNAME: Optional[str] = None
    KLARNA_PASSWORD: Optional[SecretStr] = None
    KLARNA_MODE: str = Field(default="sandbox", pattern="^(sandbox|playground|live)$")
    
    # ==================== Social Media ====================
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[SecretStr] = None
    TWITTER_BEARER_TOKEN: Optional[SecretStr] = None
    
    FACEBOOK_APP_ID: Optional[str] = None
    FACEBOOK_APP_SECRET: Optional[SecretStr] = None
    
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[SecretStr] = None
    
    # ==================== Wasabi S3 ====================
    WASABI_ACCESS_KEY: Optional[str] = None
    WASABI_SECRET_KEY: Optional[SecretStr] = None
    WASABI_BUCKET_NAME: str = "trueangels-backups"
    WASABI_ENDPOINT: str = "https://s3.wasabisys.com"
    
    # ==================== MinIO (Entwicklung) ====================
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: SecretStr = Field(default=SecretStr("minioadmin"))
    MINIO_BUCKET: str = "trueangels"
    MINIO_SECURE: bool = False
    
    # ==================== HashiCorp Vault ====================
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_TOKEN: Optional[SecretStr] = None
    
    # ==================== Email (SMTP) ====================
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[SecretStr] = None
    SMTP_FROM: str = "noreply@trueangels.de"
    SMTP_USE_TLS: bool = True
    
    # ==================== Telegram ====================
    TELEGRAM_BOT_TOKEN: Optional[SecretStr] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    
    # ==================== Transparenz ====================
    TRANSPARENCY_SALT: str = Field(default="trueangels_salt_2024")
    TRANSPARENCY_CACHE_TTL: int = 300  # 5 Minuten
    
    # ==================== Rate Limiting ====================
    RATE_LIMIT_GLOBAL: int = 1000
    RATE_LIMIT_AUTH: int = 5
    RATE_LIMIT_ADMIN: int = 200
    RATE_LIMIT_API_KEY: int = 100
    
    # ==================== Monitoring ====================
    SENTRY_DSN: Optional[str] = None
    PROMETHEUS_ENABLED: bool = True
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_ENDPOINT: str = "http://localhost:4318/v1/traces"
    
    # ==================== Logging ====================
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    LOG_FORMAT: str = "json"  # json oder text
    
    # ==================== Security ====================
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # ==================== Features ====================
    FEATURE_TRANSPARENCY_API: bool = True
    FEATURE_SOCIAL_MEDIA: bool = True
    FEATURE_BACKUPS: bool = True
    FEATURE_EVENT_SOURCING: bool = True
    
    # ==================== Pfade ====================
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    LOG_DIR: Path = BASE_DIR / "logs"
    BACKUP_DIR: Path = BASE_DIR / "backups"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    STATIC_DIR: Path = BASE_DIR / "static"
    
    def ensure_directories(self):
        """Stellt sicher, dass alle benötigten Verzeichnisse existieren"""
        for dir_path in [self.LOG_DIR, self.BACKUP_DIR, self.UPLOAD_DIR, self.STATIC_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
    
    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "test"
    
    def get_cors_origins(self) -> List[str]:
        """Gibt CORS Origins als Liste zurück"""
        return self.CORS_ORIGINS
    
    def get_webhook_secrets(self) -> Dict[str, str]:
        """Gibt Webhook Secrets für verschiedene Provider zurück"""
        secrets = {}
        if self.STRIPE_WEBHOOK_SECRET:
            secrets["stripe"] = self.STRIPE_WEBHOOK_SECRET.get_secret_value()
        return secrets
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# ==================== Singleton Instance ====================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Gibt eine Singleton-Instanz der Settings zurück.
    Verwendet LRU Cache für Performance.
    """
    settings = Settings()
    settings.ensure_directories()
    return settings


# ==================== Convenience Export ====================

settings = get_settings()