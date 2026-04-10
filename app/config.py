"""Flask 환경설정 — dev/prod 분리."""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """기본 설정."""
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"

    # SQLite3 데이터베이스
    DATABASE = os.environ.get("DATABASE") or str(BASE_DIR / "instance" / "video.db")

    # 세션 설정
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # 일일 생성 제한
    FREE_DAILY_LIMIT = 3
    PREMIUM_DAILY_LIMIT = 50

    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # 파일 경로
    DRAFTS_DIR = Path.home() / ".verticals" / "drafts"
    MEDIA_DIR = Path.home() / ".verticals" / "media"


class DevelopmentConfig(Config):
    """개발 환경."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"


class ProductionConfig(Config):
    """프로덕션 환경."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Strict"
    # SECRET_KEY 검증은 create_app()에서 수행


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
