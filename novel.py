#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   ██████╗  ██████╗ ██████╗       ██╗     ███████╗██╗   ██╗███████╗██╗       ║
║  ██╔════╝ ██╔═══██╗██╔══██╗      ██║     ██╔════╝██║   ██║██╔════╝██║       ║
║  ██║  ███╗██║   ██║██║  ██║█████╗██║     █████╗  ██║   ██║█████╗  ██║       ║
║  ██║   ██║██║   ██║██║  ██║╚════╝██║     ██╔══╝  ╚██╗ ██╔╝██╔══╝  ██║       ║
║  ╚██████╔╝╚██████╔╝██████╔╝      ███████╗███████╗ ╚████╔╝ ███████╗███████╗  ║
║   ╚═════╝  ╚═════╝ ╚═════╝       ╚══════╝╚══════╝  ╚═══╝  ╚══════╝╚══════╝  ║
║                                                                              ║
║          UPTIME MONITORING SAAS - "KHATARNAK" EDITION                        ║
║          Neon Pink & Purple Gradient Theme | Enterprise Grade                ║
║                                                                              ║
║  Tech Stack:                                                                 ║
║    Backend:  FastAPI + SQLAlchemy + Celery + Redis                           ║
║    Database: PostgreSQL + Redis Cache                                        ║
║    Frontend: React/Next.js + Tailwind CSS (served inline)                   ║
║                                                                              ║
║  Author: God-Level AI Architect                                              ║
║  Lines:  ~4000 (Maximum Depth Single File)                                  ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# =============================================================================
# SECTION 0: IMPORTS & DEPENDENCIES
# =============================================================================

import os
import sys
import json
import uuid
import hmac
import hashlib
import socket
import struct
import time
import asyncio
import logging
import smtplib
import subprocess
import platform
import ssl
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from contextlib import asynccontextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from io import StringIO

# FastAPI & Related
from fastapi import (
    FastAPI, HTTPException, Depends, Request, Response,
    Query, Path, Body, Form, status, BackgroundTasks,
    WebSocket, WebSocketDisconnect
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# SQLAlchemy
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    Float, DateTime, ForeignKey, Enum as SAEnum, Index,
    UniqueConstraint, func, and_, or_, desc, asc, JSON,
    BigInteger, SmallInteger, Date, Numeric, event, inspect
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    sessionmaker, relationship, Session, joinedload, selectinload
)
from sqlalchemy.pool import QueuePool
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB, ARRAY

# Pydantic
from pydantic import (
    BaseModel, Field, validator, EmailStr, HttpUrl, constr, conint
)

# Auth & Security
import jwt
from passlib.context import CryptContext

# HTTP Client for monitoring
import httpx

# Redis
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Celery
try:
    from celery import Celery
    from celery.schedules import crontab
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False

# =============================================================================
# SECTION 1: CONFIGURATION
# =============================================================================

class Settings:
    """Application configuration with environment variable support."""

    # Application
    APP_NAME: str = "NeonWatch - God Level Uptime Monitor"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "Khatarnak Uptime Monitoring SaaS"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "neon-pink-purple-ultra-secret-key-2024-khatarnak")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 72

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./neonwatch.db"
    )
    POSTGRES_URL: str = os.getenv(
        "POSTGRES_URL",
        "postgresql://postgres:postgres@localhost:5432/neonwatch"
    )

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Celery
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

    # Email
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@neonwatch.io")

    # Monitoring defaults
    DEFAULT_CHECK_INTERVAL: int = 300  # 5 minutes
    HTTP_TIMEOUT: int = 30
    MAX_MONITORS_FREE: int = 10
    MAX_MONITORS_PRO: int = 100

    # Theme defaults
    DEFAULT_BG_VIDEO: str = ""
    DEFAULT_BG_MUSIC: str = ""
    DEFAULT_LOGO: str = ""
    DEFAULT_PRIMARY_COLOR: str = "#F806CC"
    DEFAULT_SECONDARY_COLOR: str = "#2E0249"


settings = Settings()

# =============================================================================
# SECTION 2: LOGGING CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NeonWatch")

# =============================================================================
# SECTION 3: DATABASE ENGINE & SESSION
# =============================================================================

USE_POSTGRES = "postgresql" in settings.DATABASE_URL

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    **({"pool_size": 20, "max_overflow": 30, "pool_recycle": 3600}
       if USE_POSTGRES else {"connect_args": {"check_same_thread": False}})
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency: yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# SECTION 4: REDIS CONNECTION
# =============================================================================

redis_client = None
if REDIS_AVAILABLE:
    try:
        redis_client = redis.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=5
        )
        redis_client.ping()
        logger.info("✅ Redis connected successfully")
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable: {e}. Using in-memory fallback.")
        redis_client = None

# In-memory fallback cache
_memory_cache: Dict[str, Any] = {}


def cache_set(key: str, value: Any, ttl: int = 300):
    """Set cache value with TTL."""
    if redis_client:
        redis_client.setex(key, ttl, json.dumps(value))
    else:
        _memory_cache[key] = {
            "value": value,
            "expires": time.time() + ttl
        }


def cache_get(key: str) -> Optional[Any]:
    """Get cached value."""
    if redis_client:
        val = redis_client.get(key)
        return json.loads(val) if val else None
    else:
        entry = _memory_cache.get(key)
        if entry and entry["expires"] > time.time():
            return entry["value"]
        elif entry:
            del _memory_cache[key]
        return None


def cache_delete(key: str):
    """Delete cache entry."""
    if redis_client:
        redis_client.delete(key)
    else:
        _memory_cache.pop(key, None)


# =============================================================================
# SECTION 5: PASSWORD HASHING & JWT UTILITIES
# =============================================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against its hash."""
    return pwd_context.verify(plain, hashed)


def create_jwt_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# =============================================================================
# SECTION 6: DATABASE MODELS (SQLAlchemy ORM)
# =============================================================================

class MonitorType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    PING = "ping"
    PORT = "port"
    KEYWORD = "keyword"


class MonitorStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    PENDING = "pending"
    PAUSED = "paused"
    UNKNOWN = "unknown"


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class UserPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class AlertType(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"


# ---- User Model ----
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()), nullable=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(128), nullable=True)
    avatar_url = Column(Text, nullable=True)
    role = Column(String(20), default=UserRole.USER.value, nullable=False)
    plan = Column(String(20), default=UserPlan.FREE.value, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(Text, nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    timezone = Column(String(64), default="UTC")
    notification_email = Column(String(255), nullable=True)
    webhook_url = Column(Text, nullable=True)
    slack_webhook = Column(Text, nullable=True)
    discord_webhook = Column(Text, nullable=True)
    telegram_chat_id = Column(String(64), nullable=True)
    api_key = Column(String(64), unique=True, default=lambda: str(uuid.uuid4()).replace("-", ""))
    max_monitors = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    monitors = relationship("Monitor", back_populates="owner", cascade="all, delete-orphan")
    alert_contacts = relationship("AlertContact", back_populates="owner", cascade="all, delete-orphan")
    status_pages = relationship("StatusPage", back_populates="owner", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "uid": self.uid,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "avatar_url": self.avatar_url,
            "role": self.role,
            "plan": self.plan,
            "is_active": self.is_active,
            "is_banned": self.is_banned,
            "ban_reason": self.ban_reason,
            "email_verified": self.email_verified,
            "timezone": self.timezone,
            "max_monitors": self.max_monitors,
            "api_key": self.api_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "monitor_count": len(self.monitors) if self.monitors else 0,
        }


# ---- Monitor Model ----
class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    monitor_type = Column(String(20), default=MonitorType.HTTP.value, nullable=False)
    status = Column(String(20), default=MonitorStatus.PENDING.value, nullable=False)
    check_interval = Column(Integer, default=300, nullable=False)  # seconds
    timeout = Column(Integer, default=30, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # HTTP specific
    http_method = Column(String(10), default="GET")
    http_headers = Column(Text, nullable=True)  # JSON string
    http_body = Column(Text, nullable=True)
    expected_status_code = Column(Integer, default=200)
    follow_redirects = Column(Boolean, default=True)
    verify_ssl = Column(Boolean, default=True)

    # Keyword specific
    keyword = Column(String(500), nullable=True)
    keyword_should_exist = Column(Boolean, default=True)

    # Port specific
    port = Column(Integer, nullable=True)

    # Results tracking
    last_check_at = Column(DateTime, nullable=True)
    last_status_change = Column(DateTime, nullable=True)
    last_response_time = Column(Float, nullable=True)  # milliseconds
    current_uptime_streak = Column(Integer, default=0)  # seconds
    total_checks = Column(Integer, default=0)
    total_up = Column(Integer, default=0)
    total_down = Column(Integer, default=0)
    uptime_percentage = Column(Float, default=100.0)

    # SSL monitoring
    ssl_expiry_date = Column(DateTime, nullable=True)
    ssl_days_remaining = Column(Integer, nullable=True)

    # Alert settings per monitor
    alert_on_down = Column(Boolean, default=True)
    alert_on_recovery = Column(Boolean, default=True)
    alert_threshold = Column(Integer, default=1)  # consecutive failures before alert
    consecutive_failures = Column(Integer, default=0)

    # Metadata
    tags = Column(Text, nullable=True)  # JSON array
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("User", back_populates="monitors")
    logs = relationship("MonitorLog", back_populates="monitor", cascade="all, delete-orphan",
                         order_by="desc(MonitorLog.created_at)")
    daily_stats = relationship("DailyStats", back_populates="monitor", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="monitor", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "uid": self.uid,
            "user_id": self.user_id,
            "name": self.name,
            "url": self.url,
            "monitor_type": self.monitor_type,
            "status": self.status,
            "check_interval": self.check_interval,
            "timeout": self.timeout,
            "is_active": self.is_active,
            "http_method": self.http_method,
            "expected_status_code": self.expected_status_code,
            "keyword": self.keyword,
            "keyword_should_exist": self.keyword_should_exist,
            "port": self.port,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_response_time": self.last_response_time,
            "total_checks": self.total_checks,
            "total_up": self.total_up,
            "total_down": self.total_down,
            "uptime_percentage": self.uptime_percentage,
            "ssl_expiry_date": self.ssl_expiry_date.isoformat() if self.ssl_expiry_date else None,
            "ssl_days_remaining": self.ssl_days_remaining,
            "alert_on_down": self.alert_on_down,
            "alert_on_recovery": self.alert_on_recovery,
            "alert_threshold": self.alert_threshold,
            "consecutive_failures": self.consecutive_failures,
            "tags": json.loads(self.tags) if self.tags else [],
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---- Monitor Log Model ----
class MonitorLog(Base):
    __tablename__ = "monitor_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    response_time = Column(Float, nullable=True)  # milliseconds
    status_code = Column(Integer, nullable=True)
    response_body_snippet = Column(Text, nullable=True)  # first 500 chars
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    ssl_valid = Column(Boolean, nullable=True)
    content_length = Column(Integer, nullable=True)
    headers_snapshot = Column(Text, nullable=True)  # JSON
    check_region = Column(String(50), default="us-east-1")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    monitor = relationship("Monitor", back_populates="logs")

    def to_dict(self):
        return {
            "id": self.id,
            "monitor_id": self.monitor_id,
            "status": self.status,
            "response_time": self.response_time,
            "status_code": self.status_code,
            "error_message": self.error_message,
            "ip_address": self.ip_address,
            "ssl_valid": self.ssl_valid,
            "content_length": self.content_length,
            "check_region": self.check_region,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Daily Stats Model ----
class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    total_checks = Column(Integer, default=0)
    up_checks = Column(Integer, default=0)
    down_checks = Column(Integer, default=0)
    uptime_percentage = Column(Float, default=100.0)
    avg_response_time = Column(Float, nullable=True)
    min_response_time = Column(Float, nullable=True)
    max_response_time = Column(Float, nullable=True)
    incidents_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('monitor_id', 'date', name='uq_monitor_date'),
    )

    # Relationships
    monitor = relationship("Monitor", back_populates="daily_stats")

    def to_dict(self):
        return {
            "id": self.id,
            "monitor_id": self.monitor_id,
            "date": self.date.isoformat() if self.date else None,
            "total_checks": self.total_checks,
            "up_checks": self.up_checks,
            "down_checks": self.down_checks,
            "uptime_percentage": self.uptime_percentage,
            "avg_response_time": self.avg_response_time,
            "min_response_time": self.min_response_time,
            "max_response_time": self.max_response_time,
            "incidents_count": self.incidents_count,
        }


# ---- Incident Model ----
class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    monitor_id = Column(Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    cause = Column(Text, nullable=True)
    is_resolved = Column(Boolean, default=False)
    alert_sent = Column(Boolean, default=False)
    recovery_alert_sent = Column(Boolean, default=False)

    # Relationships
    monitor = relationship("Monitor", back_populates="incidents")

    def to_dict(self):
        return {
            "id": self.id,
            "uid": self.uid,
            "monitor_id": self.monitor_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "cause": self.cause,
            "is_resolved": self.is_resolved,
        }


# ---- Alert Contact Model ----
class AlertContact(Base):
    __tablename__ = "alert_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    alert_type = Column(String(20), nullable=False)  # email, webhook, slack, etc.
    value = Column(Text, nullable=False)  # email address, webhook URL, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="alert_contacts")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "alert_type": self.alert_type,
            "value": self.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Status Page Model ----
class StatusPage(Base):
    __tablename__ = "status_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug = Column(String(128), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    monitor_ids = Column(Text, nullable=True)  # JSON array of monitor IDs
    is_public = Column(Boolean, default=True)
    custom_domain = Column(String(255), nullable=True)
    show_uptime_chart = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="status_pages")

    def to_dict(self):
        return {
            "id": self.id,
            "uid": self.uid,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "monitor_ids": json.loads(self.monitor_ids) if self.monitor_ids else [],
            "is_public": self.is_public,
            "custom_domain": self.custom_domain,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Site Config Model (SINGLETON - Super Admin CMS) ----
class SiteConfig(Base):
    __tablename__ = "site_config"

    id = Column(Integer, primary_key=True, default=1)
    site_name = Column(String(255), default="NeonWatch")
    site_tagline = Column(String(500), default="God-Level Uptime Monitoring")
    logo_url = Column(Text, default="")
    favicon_url = Column(Text, default="")
    bg_video_url = Column(Text, default="")
    bg_music_url = Column(Text, default="")
    primary_color_theme = Column(String(20), default="#F806CC")
    secondary_color_theme = Column(String(20), default="#2E0249")
    accent_color = Column(String(20), default="#A855F7")
    glow_color = Column(String(20), default="#F806CC")
    glassmorphism_opacity = Column(Float, default=0.15)
    glassmorphism_blur = Column(Integer, default=20)
    enable_particles = Column(Boolean, default=True)
    enable_animations = Column(Boolean, default=True)
    custom_css = Column(Text, default="")
    custom_js = Column(Text, default="")
    footer_text = Column(Text, default="© 2024 NeonWatch. All rights reserved.")
    maintenance_mode = Column(Boolean, default=False)
    maintenance_message = Column(Text, default="We'll be back soon!")
    signup_enabled = Column(Boolean, default=True)
    default_user_plan = Column(String(20), default="free")
    max_free_monitors = Column(Integer, default=10)
    max_pro_monitors = Column(Integer, default=100)
    smtp_host = Column(String(255), default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(255), default="")
    smtp_password = Column(String(255), default="")
    from_email = Column(String(255), default="")
    meta_title = Column(String(255), default="NeonWatch - Uptime Monitoring")
    meta_description = Column(Text, default="God-level uptime monitoring SaaS")
    og_image_url = Column(Text, default="")
    google_analytics_id = Column(String(50), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "site_name": self.site_name,
            "site_tagline": self.site_tagline,
            "logo_url": self.logo_url,
            "favicon_url": self.favicon_url,
            "bg_video_url": self.bg_video_url,
            "bg_music_url": self.bg_music_url,
            "primary_color_theme": self.primary_color_theme,
            "secondary_color_theme": self.secondary_color_theme,
            "accent_color": self.accent_color,
            "glow_color": self.glow_color,
            "glassmorphism_opacity": self.glassmorphism_opacity,
            "glassmorphism_blur": self.glassmorphism_blur,
            "enable_particles": self.enable_particles,
            "enable_animations": self.enable_animations,
            "custom_css": self.custom_css,
            "footer_text": self.footer_text,
            "maintenance_mode": self.maintenance_mode,
            "maintenance_message": self.maintenance_message,
            "signup_enabled": self.signup_enabled,
            "default_user_plan": self.default_user_plan,
            "max_free_monitors": self.max_free_monitors,
            "max_pro_monitors": self.max_pro_monitors,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "og_image_url": self.og_image_url,
            "google_analytics_id": self.google_analytics_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---- Audit Log Model ----
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# SECTION 7: PYDANTIC SCHEMAS (Request/Response Models)
# =============================================================================

class UserRegisterSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None

class UserLoginSchema(BaseModel):
    login: str  # username or email
    password: str

class UserUpdateSchema(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None
    notification_email: Optional[str] = None
    webhook_url: Optional[str] = None
    slack_webhook: Optional[str] = None
    discord_webhook: Optional[str] = None
    telegram_chat_id: Optional[str] = None

class MonitorCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(...)
    monitor_type: str = Field(default="http")
    check_interval: int = Field(default=300, ge=60, le=86400)
    timeout: int = Field(default=30, ge=5, le=120)
    http_method: str = Field(default="GET")
    http_headers: Optional[str] = None
    http_body: Optional[str] = None
    expected_status_code: int = Field(default=200)
    follow_redirects: bool = True
    verify_ssl: bool = True
    keyword: Optional[str] = None
    keyword_should_exist: bool = True
    port: Optional[int] = None
    alert_on_down: bool = True
    alert_on_recovery: bool = True
    alert_threshold: int = Field(default=1, ge=1, le=10)
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

class MonitorUpdateSchema(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    monitor_type: Optional[str] = None
    check_interval: Optional[int] = None
    timeout: Optional[int] = None
    is_active: Optional[bool] = None
    http_method: Optional[str] = None
    expected_status_code: Optional[int] = None
    keyword: Optional[str] = None
    keyword_should_exist: Optional[bool] = None
    port: Optional[int] = None
    alert_on_down: Optional[bool] = None
    alert_on_recovery: Optional[bool] = None
    alert_threshold: Optional[int] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None

class SiteConfigUpdateSchema(BaseModel):
    site_name: Optional[str] = None
    site_tagline: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    bg_video_url: Optional[str] = None
    bg_music_url: Optional[str] = None
    primary_color_theme: Optional[str] = None
    secondary_color_theme: Optional[str] = None
    accent_color: Optional[str] = None
    glow_color: Optional[str] = None
    glassmorphism_opacity: Optional[float] = None
    glassmorphism_blur: Optional[int] = None
    enable_particles: Optional[bool] = None
    enable_animations: Optional[bool] = None
    custom_css: Optional[str] = None
    footer_text: Optional[str] = None
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = None
    signup_enabled: Optional[bool] = None
    max_free_monitors: Optional[int] = None
    max_pro_monitors: Optional[int] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    og_image_url: Optional[str] = None
    google_analytics_id: Optional[str] = None

class AlertContactSchema(BaseModel):
    name: str
    alert_type: str
    value: str

class StatusPageSchema(BaseModel):
    slug: str = Field(..., min_length=3, max_length=128)
    title: str
    description: Optional[str] = None
    monitor_ids: Optional[List[int]] = None
    is_public: bool = True


# =============================================================================
# SECTION 8: AUTH DEPENDENCIES
# =============================================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Extract and validate the current user from JWT."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_jwt_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail=f"Account banned: {user.ban_reason or 'Contact admin'}")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin or superadmin role."""
    if user.role not in [UserRole.ADMIN.value, UserRole.SUPERADMIN.value]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """Require superadmin role."""
    if user.role != UserRole.SUPERADMIN.value:
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return user


# =============================================================================
# SECTION 9: MONITORING ENGINE - Core Check Functions
# =============================================================================

class MonitoringEngine:
    """The core monitoring engine supporting HTTP, Ping, Port, Keyword checks."""

    @staticmethod
    async def check_http(monitor: Monitor) -> dict:
        """Perform HTTP/HTTPS check."""
        result = {
            "status": MonitorStatus.DOWN.value,
            "response_time": None,
            "status_code": None,
            "error_message": None,
            "ip_address": None,
            "ssl_valid": None,
            "content_length": None,
            "response_body_snippet": None,
            "headers_snapshot": None,
        }

        headers = {}
        if monitor.http_headers:
            try:
                headers = json.loads(monitor.http_headers)
            except json.JSONDecodeError:
                pass

        headers.setdefault("User-Agent", "NeonWatch/1.0 Uptime Monitor")

        try:
            start = time.time()
            async with httpx.AsyncClient(
                timeout=monitor.timeout,
                follow_redirects=monitor.follow_redirects,
                verify=monitor.verify_ssl,
            ) as client:
                response = await client.request(
                    method=monitor.http_method or "GET",
                    url=monitor.url,
                    headers=headers,
                    content=monitor.http_body if monitor.http_body else None,
                )
            elapsed = (time.time() - start) * 1000  # Convert to milliseconds

            result["response_time"] = round(elapsed, 2)
            result["status_code"] = response.status_code
            result["content_length"] = len(response.content)
            result["response_body_snippet"] = response.text[:500] if response.text else None

            resp_headers = dict(response.headers)
            result["headers_snapshot"] = json.dumps(
                {k: v for k, v in list(resp_headers.items())[:20]}
            )

            # Determine status
            expected = monitor.expected_status_code or 200
            if response.status_code == expected:
                result["status"] = MonitorStatus.UP.value
            elif 200 <= response.status_code < 400:
                result["status"] = MonitorStatus.UP.value
            else:
                result["status"] = MonitorStatus.DOWN.value
                result["error_message"] = f"Expected status {expected}, got {response.status_code}"

            # SSL check for HTTPS
            if monitor.url.startswith("https://"):
                result["ssl_valid"] = True  # If we got here without error

            # Resolve IP
            try:
                from urllib.parse import urlparse
                parsed = urlparse(monitor.url)
                hostname = parsed.hostname
                if hostname:
                    ip = socket.gethostbyname(hostname)
                    result["ip_address"] = ip
            except Exception:
                pass

        except httpx.TimeoutException:
            result["error_message"] = f"Timeout after {monitor.timeout}s"
            result["response_time"] = monitor.timeout * 1000
        except httpx.ConnectError as e:
            result["error_message"] = f"Connection error: {str(e)[:200]}"
        except ssl.SSLError as e:
            result["error_message"] = f"SSL error: {str(e)[:200]}"
            result["ssl_valid"] = False
        except Exception as e:
            result["error_message"] = f"Error: {str(e)[:200]}"

        return result

    @staticmethod
    async def check_keyword(monitor: Monitor) -> dict:
        """Perform keyword check (HTTP + keyword search)."""
        result = await MonitoringEngine.check_http(monitor)

        if result["status"] == MonitorStatus.UP.value and monitor.keyword:
            body = result.get("response_body_snippet", "") or ""
            keyword_found = monitor.keyword.lower() in body.lower()

            if monitor.keyword_should_exist and not keyword_found:
                result["status"] = MonitorStatus.DOWN.value
                result["error_message"] = f"Keyword '{monitor.keyword}' not found in response"
            elif not monitor.keyword_should_exist and keyword_found:
                result["status"] = MonitorStatus.DOWN.value
                result["error_message"] = f"Keyword '{monitor.keyword}' found (should not exist)"

        return result

    @staticmethod
    async def check_ping(monitor: Monitor) -> dict:
        """Perform ping check using system ping command."""
        result = {
            "status": MonitorStatus.DOWN.value,
            "response_time": None,
            "error_message": None,
            "ip_address": None,
        }

        try:
            from urllib.parse import urlparse
            parsed = urlparse(monitor.url if "://" in monitor.url else f"http://{monitor.url}")
            host = parsed.hostname or monitor.url

            # Resolve hostname
            try:
                result["ip_address"] = socket.gethostbyname(host)
            except socket.gaierror:
                result["error_message"] = f"Cannot resolve hostname: {host}"
                return result

            # Use system ping
            param = "-n" if platform.system().lower() == "windows" else "-c"
            timeout_param = "-w" if platform.system().lower() == "windows" else "-W"

            start = time.time()
            process = await asyncio.create_subprocess_exec(
                "ping", param, "1", timeout_param, str(min(monitor.timeout, 10)), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=monitor.timeout
            )
            elapsed = (time.time() - start) * 1000

            if process.returncode == 0:
                result["status"] = MonitorStatus.UP.value
                result["response_time"] = round(elapsed, 2)

                output = stdout.decode()
                time_match = re.search(r'time[=<](\d+\.?\d*)', output)
                if time_match:
                    result["response_time"] = float(time_match.group(1))
            else:
                result["error_message"] = "Host unreachable"

        except asyncio.TimeoutError:
            result["error_message"] = f"Ping timeout after {monitor.timeout}s"
        except Exception as e:
            result["error_message"] = f"Ping error: {str(e)[:200]}"

        return result

    @staticmethod
    async def check_port(monitor: Monitor) -> dict:
        """Perform TCP port check."""
        result = {
            "status": MonitorStatus.DOWN.value,
            "response_time": None,
            "error_message": None,
            "ip_address": None,
        }

        try:
            from urllib.parse import urlparse
            parsed = urlparse(monitor.url if "://" in monitor.url else f"http://{monitor.url}")
            host = parsed.hostname or monitor.url
            port = monitor.port or parsed.port or 80

            try:
                result["ip_address"] = socket.gethostbyname(host)
            except socket.gaierror:
                result["error_message"] = f"Cannot resolve hostname: {host}"
                return result

            start = time.time()
            future = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(future, timeout=monitor.timeout)
            elapsed = (time.time() - start) * 1000

            result["status"] = MonitorStatus.UP.value
            result["response_time"] = round(elapsed, 2)

            writer.close()
            await writer.wait_closed()

        except asyncio.TimeoutError:
            result["error_message"] = f"Port connection timeout after {monitor.timeout}s"
        except ConnectionRefusedError:
            result["error_message"] = f"Connection refused on port {monitor.port}"
        except Exception as e:
            result["error_message"] = f"Port check error: {str(e)[:200]}"

        return result

    @staticmethod
    async def perform_check(monitor: Monitor) -> dict:
        """Route to the appropriate check method based on monitor type."""
        check_methods = {
            MonitorType.HTTP.value: MonitoringEngine.check_http,
            MonitorType.HTTPS.value: MonitoringEngine.check_http,
            MonitorType.PING.value: MonitoringEngine.check_ping,
            MonitorType.PORT.value: MonitoringEngine.check_port,
            MonitorType.KEYWORD.value: MonitoringEngine.check_keyword,
        }
        method = check_methods.get(monitor.monitor_type, MonitoringEngine.check_http)
        return await method(monitor)


# =============================================================================
# SECTION 10: SSL Certificate Checker
# =============================================================================

async def check_ssl_certificate(hostname: str) -> dict:
    """Check SSL certificate expiry for a hostname."""
    result = {"valid": False, "expiry_date": None, "days_remaining": None, "issuer": None}
    try:
        ctx = ssl.create_default_context()
        loop = asyncio.get_event_loop()

        def _check():
            with socket.create_connection((hostname, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    expiry_str = cert.get("notAfter", "")
                    expiry = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
                    days_rem = (expiry - datetime.utcnow()).days
                    issuer = dict(x[0] for x in cert.get("issuer", []))
                    return {
                        "valid": days_rem > 0,
                        "expiry_date": expiry,
                        "days_remaining": days_rem,
                        "issuer": issuer.get("organizationName", "Unknown"),
                    }

        result = await loop.run_in_executor(None, _check)
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


# =============================================================================
# SECTION 11: ALERTING ENGINE
# =============================================================================

class AlertingEngine:
    """Handles sending alerts via multiple channels."""

    @staticmethod
    async def send_email_alert(to_email: str, subject: str, body: str):
        """Send an email alert."""
        if not settings.SMTP_USER:
            logger.warning("SMTP not configured, skipping email alert")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.FROM_EMAIL
            msg["To"] = to_email
            html_body = f"""
            <html>
            <body style="background:#2E0249;color:#fff;font-family:Arial;padding:20px;">
              <div style="max-width:600px;margin:0 auto;background:rgba(46,2,73,0.8);
                          border:1px solid #F806CC;border-radius:12px;padding:30px;">
                <h1 style="color:#F806CC;text-align:center;">⚡ NeonWatch Alert</h1>
                <div style="color:#e0e0e0;line-height:1.6;">{body}</div>
                <hr style="border-color:#A855F7;margin:20px 0;">
                <p style="color:#888;font-size:12px;text-align:center;">
                  NeonWatch Uptime Monitoring - God Level Edition
                </p>
              </div>
            </body>
            </html>
            """
            msg.attach(MIMEText(html_body, "html"))

            loop = asyncio.get_event_loop()
            def _send():
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    server.starttls()
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.sendmail(settings.FROM_EMAIL, to_email, msg.as_string())
            await loop.run_in_executor(None, _send)
            logger.info(f"📧 Email alert sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    @staticmethod
    async def send_webhook_alert(webhook_url: str, payload: dict):
        """Send a webhook alert."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=payload)
                logger.info(f"🔗 Webhook sent to {webhook_url}: {response.status_code}")
                return response.status_code < 400
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            return False

    @staticmethod
    async def send_discord_alert(webhook_url: str, monitor_name: str, status: str, details: str):
        """Send a Discord webhook alert."""
        color = 0x00FF00 if status == "up" else 0xFF0000
        payload = {
            "embeds": [{
                "title": f"⚡ NeonWatch: {monitor_name}",
                "description": details,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "NeonWatch Monitoring"},
            }]
        }
        return await AlertingEngine.send_webhook_alert(webhook_url, payload)

    @staticmethod
    async def send_slack_alert(webhook_url: str, monitor_name: str, status: str, details: str):
        """Send a Slack webhook alert."""
        emoji = "✅" if status == "up" else "🔴"
        payload = {
            "text": f"{emoji} *NeonWatch Alert*: {monitor_name}\n{details}"
        }
        return await AlertingEngine.send_webhook_alert(webhook_url, payload)

    @staticmethod
    async def dispatch_alert(user: User, monitor: Monitor, status: str, details: str):
        """Dispatch alerts to all configured channels for a user."""
        subject = f"[{'UP ✅' if status == 'up' else 'DOWN 🔴'}] {monitor.name}"

        tasks = []

        # Email alert
        alert_email = user.notification_email or user.email
        if alert_email:
            tasks.append(AlertingEngine.send_email_alert(alert_email, subject, details))

        # Webhook
        if user.webhook_url:
            payload = {
                "monitor_name": monitor.name,
                "monitor_url": monitor.url,
                "status": status,
                "details": details,
                "timestamp": datetime.utcnow().isoformat(),
            }
            tasks.append(AlertingEngine.send_webhook_alert(user.webhook_url, payload))

        # Discord
        if user.discord_webhook:
            tasks.append(AlertingEngine.send_discord_alert(
                user.discord_webhook, monitor.name, status, details
            ))

        # Slack
        if user.slack_webhook:
            tasks.append(AlertingEngine.send_slack_alert(
                user.slack_webhook, monitor.name, status, details
            ))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# =============================================================================
# SECTION 12: DAILY STATS CALCULATOR
# =============================================================================

def calculate_daily_stats(db: Session, monitor_id: int, date: datetime.date = None):
    """Calculate and store daily uptime statistics."""
    if date is None:
        date = datetime.utcnow().date()

    start_dt = datetime.combine(date, datetime.min.time())
    end_dt = datetime.combine(date, datetime.max.time())

    logs = db.query(MonitorLog).filter(
        MonitorLog.monitor_id == monitor_id,
        MonitorLog.created_at >= start_dt,
        MonitorLog.created_at <= end_dt,
    ).all()

    if not logs:
        return

    total = len(logs)
    up_count = sum(1 for l in logs if l.status == MonitorStatus.UP.value)
    down_count = total - up_count
    response_times = [l.response_time for l in logs if l.response_time is not None]

    uptime_pct = (up_count / total * 100) if total > 0 else 100.0
    avg_rt = sum(response_times) / len(response_times) if response_times else None
    min_rt = min(response_times) if response_times else None
    max_rt = max(response_times) if response_times else None

    # Upsert daily stats
    stats = db.query(DailyStats).filter(
        DailyStats.monitor_id == monitor_id,
        DailyStats.date == date,
    ).first()

    if stats:
        stats.total_checks = total
        stats.up_checks = up_count
        stats.down_checks = down_count
        stats.uptime_percentage = round(uptime_pct, 4)
        stats.avg_response_time = round(avg_rt, 2) if avg_rt else None
        stats.min_response_time = round(min_rt, 2) if min_rt else None
        stats.max_response_time = round(max_rt, 2) if max_rt else None
    else:
        stats = DailyStats(
            monitor_id=monitor_id,
            date=date,
            total_checks=total,
            up_checks=up_count,
            down_checks=down_count,
            uptime_percentage=round(uptime_pct, 4),
            avg_response_time=round(avg_rt, 2) if avg_rt else None,
            min_response_time=round(min_rt, 2) if min_rt else None,
            max_response_time=round(max_rt, 2) if max_rt else None,
        )
        db.add(stats)

    db.commit()


# =============================================================================
# SECTION 13: BACKGROUND MONITOR RUNNER
# =============================================================================

async def run_single_monitor_check(monitor_id: int):
    """Execute a single monitor check and update the database."""
    db = SessionLocal()
    try:
        monitor = db.query(Monitor).options(
            joinedload(Monitor.owner)
        ).filter(Monitor.id == monitor_id).first()

        if not monitor or not monitor.is_active:
            return

        logger.info(f"🔍 Checking: {monitor.name} ({monitor.monitor_type}) -> {monitor.url}")

        result = await MonitoringEngine.perform_check(monitor)

        # Create log entry
        log = MonitorLog(
            monitor_id=monitor.id,
            status=result["status"],
            response_time=result.get("response_time"),
            status_code=result.get("status_code"),
            response_body_snippet=result.get("response_body_snippet"),
            error_message=result.get("error_message"),
            ip_address=result.get("ip_address"),
            ssl_valid=result.get("ssl_valid"),
            content_length=result.get("content_length"),
            headers_snapshot=result.get("headers_snapshot"),
        )
        db.add(log)

        # Update monitor stats
        previous_status = monitor.status
        monitor.status = result["status"]
        monitor.last_check_at = datetime.utcnow()
        monitor.last_response_time = result.get("response_time")
        monitor.total_checks = (monitor.total_checks or 0) + 1

        if result["status"] == MonitorStatus.UP.value:
            monitor.total_up = (monitor.total_up or 0) + 1
            monitor.consecutive_failures = 0
        else:
            monitor.total_down = (monitor.total_down or 0) + 1
            monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1

        # Uptime percentage
        if monitor.total_checks > 0:
            monitor.uptime_percentage = round(
                (monitor.total_up / monitor.total_checks) * 100, 4
            )

        # Incident tracking & alerting
        if previous_status != result["status"]:
            monitor.last_status_change = datetime.utcnow()

            if result["status"] == MonitorStatus.DOWN.value:
                # Status went DOWN
                if monitor.consecutive_failures >= monitor.alert_threshold:
                    incident = Incident(
                        monitor_id=monitor.id,
                        started_at=datetime.utcnow(),
                        cause=result.get("error_message", "Unknown"),
                    )
                    db.add(incident)

                    if monitor.alert_on_down and monitor.owner:
                        details = (
                            f"<h3>🔴 Monitor DOWN</h3>"
                            f"<p><strong>{monitor.name}</strong> is not responding.</p>"
                            f"<p>URL: {monitor.url}</p>"
                            f"<p>Error: {result.get('error_message', 'N/A')}</p>"
                            f"<p>Time: {datetime.utcnow().isoformat()}</p>"
                        )
                        await AlertingEngine.dispatch_alert(
                            monitor.owner, monitor, "down", details
                        )

            elif result["status"] == MonitorStatus.UP.value and previous_status == MonitorStatus.DOWN.value:
                # Recovery
                open_incident = db.query(Incident).filter(
                    Incident.monitor_id == monitor.id,
                    Incident.is_resolved == False,
                ).first()

                if open_incident:
                    open_incident.is_resolved = True
                    open_incident.resolved_at = datetime.utcnow()
                    open_incident.duration_seconds = int(
                        (datetime.utcnow() - open_incident.started_at).total_seconds()
                    )

                if monitor.alert_on_recovery and monitor.owner:
                    details = (
                        f"<h3>✅ Monitor UP (Recovered)</h3>"
                        f"<p><strong>{monitor.name}</strong> is back online!</p>"
                        f"<p>URL: {monitor.url}</p>"
                        f"<p>Response Time: {result.get('response_time', 'N/A')}ms</p>"
                        f"<p>Time: {datetime.utcnow().isoformat()}</p>"
                    )
                    await AlertingEngine.dispatch_alert(
                        monitor.owner, monitor, "up", details
                    )

        # SSL Certificate tracking
        if monitor.monitor_type in ["http", "https"] and monitor.url.startswith("https://"):
            try:
                from urllib.parse import urlparse
                hostname = urlparse(monitor.url).hostname
                ssl_info = await check_ssl_certificate(hostname)
                if ssl_info.get("expiry_date"):
                    monitor.ssl_expiry_date = ssl_info["expiry_date"]
                    monitor.ssl_days_remaining = ssl_info["days_remaining"]
            except Exception:
                pass

        db.commit()

        # Update daily stats
        calculate_daily_stats(db, monitor.id)

        # Update cache
        cache_delete(f"monitor:{monitor.id}")
        cache_delete(f"user_monitors:{monitor.user_id}")

        status_emoji = "✅" if result["status"] == "up" else "🔴"
        logger.info(
            f"{status_emoji} {monitor.name}: {result['status'].upper()} "
            f"({result.get('response_time', 'N/A')}ms)"
        )

    except Exception as e:
        logger.error(f"❌ Error checking monitor {monitor_id}: {e}")
        db.rollback()
    finally:
        db.close()


async def run_all_monitors():
    """Run checks for all active monitors that are due."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        monitors = db.query(Monitor).filter(
            Monitor.is_active == True,
            Monitor.status != MonitorStatus.PAUSED.value,
        ).all()

        tasks = []
        for monitor in monitors:
            if monitor.last_check_at is None:
                tasks.append(run_single_monitor_check(monitor.id))
            else:
                next_check = monitor.last_check_at + timedelta(seconds=monitor.check_interval)
                if now >= next_check:
                    tasks.append(run_single_monitor_check(monitor.id))

        if tasks:
            logger.info(f"🚀 Running {len(tasks)} monitor checks...")
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.debug("💤 No monitors due for checking")

    except Exception as e:
        logger.error(f"❌ Error in monitor runner: {e}")
    finally:
        db.close()


# =============================================================================
# SECTION 14: CELERY CONFIGURATION (Background Task Queue)
# =============================================================================

if CELERY_AVAILABLE:
    celery_app = Celery(
        "neonwatch",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "run-monitor-checks": {
                "task": "monitoring.run_monitor_checks_task",
                "schedule": 60.0,  # Every 60 seconds
            },
            "daily-stats-aggregation": {
                "task": "monitoring.aggregate_daily_stats_task",
                "schedule": crontab(minute=5, hour=0),  # Daily at 00:05
            },
            "cleanup-old-logs": {
                "task": "monitoring.cleanup_old_logs_task",
                "schedule": crontab(minute=0, hour=3),  # Daily at 03:00
            },
        },
    )

    @celery_app.task(name="monitoring.run_monitor_checks_task")
    def run_monitor_checks_task():
        """Celery task: run all due monitor checks."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_all_monitors())
        loop.close()

    @celery_app.task(name="monitoring.run_single_check_task")
    def run_single_check_task(monitor_id: int):
        """Celery task: run a single monitor check."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_single_monitor_check(monitor_id))
        loop.close()

    @celery_app.task(name="monitoring.aggregate_daily_stats_task")
    def aggregate_daily_stats_task():
        """Celery task: aggregate daily stats for all monitors."""
        db = SessionLocal()
        try:
            yesterday = (datetime.utcnow() - timedelta(days=1)).date()
            monitors = db.query(Monitor).filter(Monitor.is_active == True).all()
            for monitor in monitors:
                calculate_daily_stats(db, monitor.id, yesterday)
            logger.info(f"📊 Daily stats aggregated for {len(monitors)} monitors")
        finally:
            db.close()

    @celery_app.task(name="monitoring.cleanup_old_logs_task")
    def cleanup_old_logs_task():
        """Celery task: cleanup logs older than 90 days."""
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(days=90)
            deleted = db.query(MonitorLog).filter(
                MonitorLog.created_at < cutoff
            ).delete()
            db.commit()
            logger.info(f"🗑️ Cleaned up {deleted} old log entries")
        finally:
            db.close()


# =============================================================================
# SECTION 15: FASTAPI APPLICATION & LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - startup/shutdown."""
    # STARTUP
    logger.info("🚀 NeonWatch starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("📦 Database tables created/verified")

    # Initialize SiteConfig singleton
    db = SessionLocal()
    try:
        config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
        if not config:
            config = SiteConfig(id=1)
            db.add(config)
            db.commit()
            logger.info("⚙️ Default SiteConfig initialized")

        # Create default superadmin
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                email="admin@neonwatch.io",
                password_hash=hash_password("admin123456"),
                full_name="Super Administrator",
                role=UserRole.SUPERADMIN.value,
                plan=UserPlan.ENTERPRISE.value,
                is_active=True,
                email_verified=True,
                max_monitors=9999,
            )
            db.add(admin)
            db.commit()
            logger.info("👑 Default superadmin created (admin / admin123456)")
    finally:
        db.close()

    # Start background monitor loop (if Celery is not available)
    monitor_task = None
    if not CELERY_AVAILABLE:
        async def _monitor_loop():
            while True:
                try:
                    await run_all_monitors()
                except Exception as e:
                    logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(60)

        monitor_task = asyncio.create_task(_monitor_loop())
        logger.info("🔄 Built-in monitor loop started (no Celery)")

    logger.info("✨ NeonWatch is ready! God-Level monitoring activated.")

    yield

    # SHUTDOWN
    if monitor_task:
        monitor_task.cancel()
    logger.info("👋 NeonWatch shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# SECTION 16: API ROUTES - Authentication
# =============================================================================

@app.post("/api/auth/register", tags=["Auth"])
async def register(data: UserRegisterSchema, db: Session = Depends(get_db)):
    """Register a new user account."""
    # Check site config for signup
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if config and not config.signup_enabled:
        raise HTTPException(400, "Registration is currently disabled")

    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")

    max_monitors = config.max_free_monitors if config else 10

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        max_monitors=max_monitors,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_jwt_token({"user_id": user.id, "role": user.role})

    return {
        "success": True,
        "token": token,
        "user": user.to_dict(),
        "message": "Registration successful! Welcome to NeonWatch.",
    }


@app.post("/api/auth/login", tags=["Auth"])
async def login(data: UserLoginSchema, db: Session = Depends(get_db)):
    """Login with username/email and password."""
    user = db.query(User).filter(
        or_(User.username == data.login, User.email == data.login)
    ).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if user.is_banned:
        raise HTTPException(403, f"Account banned: {user.ban_reason or 'Contact admin'}")
    if not user.is_active:
        raise HTTPException(403, "Account deactivated")

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_jwt_token({"user_id": user.id, "role": user.role})

    return {
        "success": True,
        "token": token,
        "user": user.to_dict(),
    }


@app.get("/api/auth/me", tags=["Auth"])
async def get_me(user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    return {"success": True, "user": user.to_dict()}


@app.put("/api/auth/me", tags=["Auth"])
async def update_me(
    data: UserUpdateSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's profile."""
    for field, value in data.dict(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return {"success": True, "user": user.to_dict()}


@app.post("/api/auth/change-password", tags=["Auth"])
async def change_password(
    current_password: str = Body(...),
    new_password: str = Body(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change current user's password."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"success": True, "message": "Password updated"}


# =============================================================================
# SECTION 17: API ROUTES - Monitors CRUD
# =============================================================================

@app.get("/api/monitors", tags=["Monitors"])
async def list_monitors(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None),
    type_filter: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """List all monitors for the current user."""
    cache_key = f"user_monitors:{user.id}:{page}:{limit}:{status_filter}:{type_filter}:{search}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    query = db.query(Monitor).filter(Monitor.user_id == user.id)

    if status_filter:
        query = query.filter(Monitor.status == status_filter)
    if type_filter:
        query = query.filter(Monitor.monitor_type == type_filter)
    if search:
        query = query.filter(
            or_(Monitor.name.ilike(f"%{search}%"), Monitor.url.ilike(f"%{search}%"))
        )

    total = query.count()
    monitors = query.order_by(desc(Monitor.created_at)).offset(
        (page - 1) * limit
    ).limit(limit).all()

    result = {
        "success": True,
        "monitors": [m.to_dict() for m in monitors],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }

    cache_set(cache_key, result, ttl=30)
    return result


@app.post("/api/monitors", tags=["Monitors"])
async def create_monitor(
    data: MonitorCreateSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Create a new monitor."""
    current_count = db.query(Monitor).filter(Monitor.user_id == user.id).count()
    if current_count >= user.max_monitors:
        raise HTTPException(
            400,
            f"Monitor limit reached ({user.max_monitors}). Upgrade your plan.",
        )

    monitor = Monitor(
        user_id=user.id,
        name=data.name,
        url=data.url,
        monitor_type=data.monitor_type,
        check_interval=data.check_interval,
        timeout=data.timeout,
        http_method=data.http_method,
        http_headers=data.http_headers,
        http_body=data.http_body,
        expected_status_code=data.expected_status_code,
        follow_redirects=data.follow_redirects,
        verify_ssl=data.verify_ssl,
        keyword=data.keyword,
        keyword_should_exist=data.keyword_should_exist,
        port=data.port,
        alert_on_down=data.alert_on_down,
        alert_on_recovery=data.alert_on_recovery,
        alert_threshold=data.alert_threshold,
        tags=json.dumps(data.tags) if data.tags else None,
        notes=data.notes,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    cache_delete(f"user_monitors:{user.id}")

    # Run initial check
    if background_tasks:
        background_tasks.add_task(run_single_monitor_check, monitor.id)

    return {"success": True, "monitor": monitor.to_dict(), "message": "Monitor created!"}


@app.get("/api/monitors/{monitor_id}", tags=["Monitors"])
async def get_monitor(
    monitor_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed monitor info."""
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id, Monitor.user_id == user.id
    ).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    # Get recent logs
    logs = db.query(MonitorLog).filter(
        MonitorLog.monitor_id == monitor.id
    ).order_by(desc(MonitorLog.created_at)).limit(100).all()

    # Get recent incidents
    incidents = db.query(Incident).filter(
        Incident.monitor_id == monitor.id
    ).order_by(desc(Incident.started_at)).limit(20).all()

    # Get daily stats for last 30 days
    thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
    daily = db.query(DailyStats).filter(
        DailyStats.monitor_id == monitor.id,
        DailyStats.date >= thirty_days_ago,
    ).order_by(asc(DailyStats.date)).all()

    return {
        "success": True,
        "monitor": monitor.to_dict(),
        "logs": [l.to_dict() for l in logs],
        "incidents": [i.to_dict() for i in incidents],
        "daily_stats": [d.to_dict() for d in daily],
    }


@app.put("/api/monitors/{monitor_id}", tags=["Monitors"])
async def update_monitor(
    monitor_id: int,
    data: MonitorUpdateSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a monitor."""
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id, Monitor.user_id == user.id
    ).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    update_data = data.dict(exclude_unset=True)
    if "tags" in update_data:
        update_data["tags"] = json.dumps(update_data["tags"]) if update_data["tags"] else None

    for field, value in update_data.items():
        setattr(monitor, field, value)

    db.commit()
    db.refresh(monitor)

    cache_delete(f"monitor:{monitor.id}")
    cache_delete(f"user_monitors:{user.id}")

    return {"success": True, "monitor": monitor.to_dict()}


@app.delete("/api/monitors/{monitor_id}", tags=["Monitors"])
async def delete_monitor(
    monitor_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a monitor and all its data."""
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id, Monitor.user_id == user.id
    ).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    db.delete(monitor)
    db.commit()

    cache_delete(f"monitor:{monitor_id}")
    cache_delete(f"user_monitors:{user.id}")

    return {"success": True, "message": "Monitor deleted"}


@app.post("/api/monitors/{monitor_id}/check", tags=["Monitors"])
async def trigger_check(
    monitor_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    """Manually trigger a monitor check."""
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id, Monitor.user_id == user.id
    ).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    if background_tasks:
        background_tasks.add_task(run_single_monitor_check, monitor.id)

    return {"success": True, "message": "Check triggered"}


@app.post("/api/monitors/{monitor_id}/pause", tags=["Monitors"])
async def pause_monitor(
    monitor_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pause/unpause a monitor."""
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id, Monitor.user_id == user.id
    ).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")

    if monitor.status == MonitorStatus.PAUSED.value:
        monitor.status = MonitorStatus.PENDING.value
        monitor.is_active = True
        msg = "Monitor resumed"
    else:
        monitor.status = MonitorStatus.PAUSED.value
        monitor.is_active = False
        msg = "Monitor paused"

    db.commit()
    cache_delete(f"user_monitors:{user.id}")
    return {"success": True, "message": msg, "status": monitor.status}


# =============================================================================
# SECTION 18: API ROUTES - Dashboard & Stats
# =============================================================================

@app.get("/api/dashboard", tags=["Dashboard"])
async def get_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get dashboard overview data."""
    monitors = db.query(Monitor).filter(Monitor.user_id == user.id).all()

    total = len(monitors)
    up = sum(1 for m in monitors if m.status == MonitorStatus.UP.value)
    down = sum(1 for m in monitors if m.status == MonitorStatus.DOWN.value)
    paused = sum(1 for m in monitors if m.status == MonitorStatus.PAUSED.value)
    pending = total - up - down - paused

    avg_uptime = 0
    if monitors:
        uptimes = [m.uptime_percentage for m in monitors if m.uptime_percentage is not None]
        avg_uptime = sum(uptimes) / len(uptimes) if uptimes else 0

    avg_response = 0
    response_times = [m.last_response_time for m in monitors if m.last_response_time]
    if response_times:
        avg_response = sum(response_times) / len(response_times)

    # Recent incidents
    recent_incidents = db.query(Incident).join(Monitor).filter(
        Monitor.user_id == user.id,
    ).order_by(desc(Incident.started_at)).limit(10).all()

    # Overall daily stats (last 30 days)
    thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
    daily_aggregated = db.query(
        DailyStats.date,
        func.avg(DailyStats.uptime_percentage).label("avg_uptime"),
        func.avg(DailyStats.avg_response_time).label("avg_response_time"),
    ).join(Monitor).filter(
        Monitor.user_id == user.id,
        DailyStats.date >= thirty_days_ago,
    ).group_by(DailyStats.date).order_by(asc(DailyStats.date)).all()

    return {
        "success": True,
        "overview": {
            "total_monitors": total,
            "up": up,
            "down": down,
            "paused": paused,
            "pending": pending,
            "avg_uptime": round(avg_uptime, 2),
            "avg_response_time": round(avg_response, 2),
        },
        "monitors": [m.to_dict() for m in monitors],
        "recent_incidents": [i.to_dict() for i in recent_incidents],
        "daily_chart": [
            {
                "date": d.date.isoformat(),
                "uptime": round(d.avg_uptime, 2) if d.avg_uptime else 100,
                "response_time": round(d.avg_response_time, 2) if d.avg_response_time else 0,
            }
            for d in daily_aggregated
        ],
    }


# =============================================================================
# SECTION 19: API ROUTES - Site Config (Super Admin CMS)
# =============================================================================

@app.get("/api/site-config", tags=["Site Config"])
async def get_site_config(db: Session = Depends(get_db)):
    """Get public site configuration (no auth needed for theme data)."""
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if not config:
        config = SiteConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return {"success": True, "config": config.to_dict()}


@app.put("/api/site-config", tags=["Site Config"])
async def update_site_config(
    data: SiteConfigUpdateSchema,
    admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Update site configuration (Super Admin only)."""
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if not config:
        config = SiteConfig(id=1)
        db.add(config)

    for field, value in data.dict(exclude_unset=True).items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)

    cache_delete("site_config")

    # Audit log
    audit = AuditLog(
        user_id=admin.id,
        action="update_site_config",
        target_type="site_config",
        target_id=1,
        details=json.dumps(data.dict(exclude_unset=True)),
    )
    db.add(audit)
    db.commit()

    return {"success": True, "config": config.to_dict(), "message": "Site config updated!"}


# =============================================================================
# SECTION 20: API ROUTES - Super Admin Panel
# =============================================================================

@app.get("/api/admin/users", tags=["Admin"])
async def admin_list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = None,
):
    """List all users (Admin only)."""
    query = db.query(User)
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%"),
            )
        )
    total = query.count()
    users = query.order_by(desc(User.created_at)).offset(
        (page - 1) * limit
    ).limit(limit).all()

    return {
        "success": True,
        "users": [u.to_dict() for u in users],
        "total": total,
        "page": page,
    }


@app.get("/api/admin/users/{user_id}", tags=["Admin"])
async def admin_get_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get user details with all monitors (Admin only)."""
    user = db.query(User).options(selectinload(User.monitors)).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "success": True,
        "user": user.to_dict(),
        "monitors": [m.to_dict() for m in user.monitors],
    }


@app.post("/api/admin/users/{user_id}/ban", tags=["Admin"])
async def admin_ban_user(
    user_id: int,
    reason: str = Body("Violated terms of service"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Ban a user (Admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role == UserRole.SUPERADMIN.value:
        raise HTTPException(403, "Cannot ban a superadmin")

    user.is_banned = True
    user.ban_reason = reason
    db.commit()

    audit = AuditLog(
        user_id=admin.id, action="ban_user",
        target_type="user", target_id=user_id,
        details=f"Reason: {reason}",
    )
    db.add(audit)
    db.commit()

    return {"success": True, "message": f"User {user.username} banned"}


@app.post("/api/admin/users/{user_id}/unban", tags=["Admin"])
async def admin_unban_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unban a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = False
    user.ban_reason = None
    db.commit()
    return {"success": True, "message": f"User {user.username} unbanned"}


@app.put("/api/admin/users/{user_id}/role", tags=["Admin"])
async def admin_change_role(
    user_id: int,
    role: str = Body(...),
    admin: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Change a user's role (Superadmin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if role not in [r.value for r in UserRole]:
        raise HTTPException(400, f"Invalid role. Must be one of: {[r.value for r in UserRole]}")
    user.role = role
    db.commit()
    return {"success": True, "message": f"User role updated to {role}"}


@app.put("/api/admin/users/{user_id}/plan", tags=["Admin"])
async def admin_change_plan(
    user_id: int,
    plan: str = Body(...),
    max_monitors: int = Body(10),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Change a user's plan (Admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.plan = plan
    user.max_monitors = max_monitors
    db.commit()
    return {"success": True, "message": f"User plan updated to {plan}"}


@app.get("/api/admin/stats", tags=["Admin"])
async def admin_global_stats(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get global system statistics."""
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True, User.is_banned == False).count()
    total_monitors = db.query(Monitor).count()
    active_monitors = db.query(Monitor).filter(Monitor.is_active == True).count()
    total_checks = db.query(func.sum(Monitor.total_checks)).scalar() or 0
    total_incidents = db.query(Incident).count()
    open_incidents = db.query(Incident).filter(Incident.is_resolved == False).count()

    # User signups last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_users_week = db.query(User).filter(User.created_at >= week_ago).count()

    # Monitors by type
    type_distribution = db.query(
        Monitor.monitor_type, func.count(Monitor.id)
    ).group_by(Monitor.monitor_type).all()

    # Plan distribution
    plan_distribution = db.query(
        User.plan, func.count(User.id)
    ).group_by(User.plan).all()

    return {
        "success": True,
        "stats": {
            "total_users": total_users,
            "active_users": active_users,
            "new_users_week": new_users_week,
            "total_monitors": total_monitors,
            "active_monitors": active_monitors,
            "total_checks": total_checks,
            "total_incidents": total_incidents,
            "open_incidents": open_incidents,
            "monitor_types": {t: c for t, c in type_distribution},
            "plan_distribution": {p: c for p, c in plan_distribution},
        },
    }


@app.get("/api/admin/audit-logs", tags=["Admin"])
async def admin_audit_logs(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Get audit logs."""
    total = db.query(AuditLog).count()
    logs = db.query(AuditLog).order_by(
        desc(AuditLog.created_at)
    ).offset((page - 1) * limit).limit(limit).all()

    return {
        "success": True,
        "logs": [l.to_dict() for l in logs],
        "total": total,
        "page": page,
    }


@app.get("/api/admin/monitors", tags=["Admin"])
async def admin_list_all_monitors(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """List all monitors across all users (Admin only)."""
    total = db.query(Monitor).count()
    monitors = db.query(Monitor).options(joinedload(Monitor.owner)).order_by(
        desc(Monitor.created_at)
    ).offset((page - 1) * limit).limit(limit).all()

    result = []
    for m in monitors:
        md = m.to_dict()
        md["owner_username"] = m.owner.username if m.owner else "Unknown"
        md["owner_email"] = m.owner.email if m.owner else "Unknown"
        result.append(md)

    return {"success": True, "monitors": result, "total": total, "page": page}


# =============================================================================
# SECTION 21: API ROUTES - Alert Contacts
# =============================================================================

@app.get("/api/alert-contacts", tags=["Alerts"])
async def list_alert_contacts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contacts = db.query(AlertContact).filter(AlertContact.user_id == user.id).all()
    return {"success": True, "contacts": [c.to_dict() for c in contacts]}


@app.post("/api/alert-contacts", tags=["Alerts"])
async def create_alert_contact(
    data: AlertContactSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = AlertContact(
        user_id=user.id,
        name=data.name,
        alert_type=data.alert_type,
        value=data.value,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return {"success": True, "contact": contact.to_dict()}


@app.delete("/api/alert-contacts/{contact_id}", tags=["Alerts"])
async def delete_alert_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = db.query(AlertContact).filter(
        AlertContact.id == contact_id, AlertContact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    db.delete(contact)
    db.commit()
    return {"success": True, "message": "Contact deleted"}


# =============================================================================
# SECTION 22: API ROUTES - Status Pages
# =============================================================================

@app.get("/api/status-pages", tags=["Status Pages"])
async def list_status_pages(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pages = db.query(StatusPage).filter(StatusPage.user_id == user.id).all()
    return {"success": True, "pages": [p.to_dict() for p in pages]}


@app.post("/api/status-pages", tags=["Status Pages"])
async def create_status_page(
    data: StatusPageSchema,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(StatusPage).filter(StatusPage.slug == data.slug).first():
        raise HTTPException(400, "Slug already taken")

    page = StatusPage(
        user_id=user.id,
        slug=data.slug,
        title=data.title,
        description=data.description,
        monitor_ids=json.dumps(data.monitor_ids) if data.monitor_ids else None,
        is_public=data.is_public,
    )
    db.add(page)
    db.commit()
    db.refresh(page)
    return {"success": True, "page": page.to_dict()}


@app.get("/api/status/{slug}", tags=["Status Pages"])
async def get_public_status_page(slug: str, db: Session = Depends(get_db)):
    """Get a public status page by slug (no auth required)."""
    page = db.query(StatusPage).filter(StatusPage.slug == slug, StatusPage.is_public == True).first()
    if not page:
        raise HTTPException(404, "Status page not found")

    monitor_ids = json.loads(page.monitor_ids) if page.monitor_ids else []
    monitors = db.query(Monitor).filter(Monitor.id.in_(monitor_ids)).all() if monitor_ids else []

    # Get 30-day stats for each monitor
    thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
    monitor_data = []
    for m in monitors:
        daily = db.query(DailyStats).filter(
            DailyStats.monitor_id == m.id,
            DailyStats.date >= thirty_days_ago,
        ).order_by(asc(DailyStats.date)).all()
        monitor_data.append({
            "name": m.name,
            "status": m.status,
            "uptime_percentage": m.uptime_percentage,
            "last_response_time": m.last_response_time,
            "daily": [d.to_dict() for d in daily],
        })

    overall_uptime = 0
    if monitors:
        uptimes = [m.uptime_percentage for m in monitors if m.uptime_percentage is not None]
        overall_uptime = sum(uptimes) / len(uptimes) if uptimes else 100

    return {
        "success": True,
        "page": page.to_dict(),
        "monitors": monitor_data,
        "overall_uptime": round(overall_uptime, 2),
    }


# =============================================================================
# SECTION 23: WEBSOCKET - Real-Time Updates
# =============================================================================

connected_clients: Dict[int, List[WebSocket]] = {}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time monitor updates."""
    await websocket.accept()

    if user_id not in connected_clients:
        connected_clients[user_id] = []
    connected_clients[user_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # Heartbeat
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        connected_clients[user_id].remove(websocket)
        if not connected_clients[user_id]:
            del connected_clients[user_id]


async def notify_user(user_id: int, data: dict):
    """Send real-time notification to connected user."""
    if user_id in connected_clients:
        for ws in connected_clients[user_id]:
            try:
                await ws.send_json(data)
            except Exception:
                pass


# =============================================================================
# SECTION 24: HEALTH CHECK ENDPOINT
# =============================================================================

@app.get("/api/health", tags=["System"])
async def health_check():
    """System health check."""
    checks = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "database": "connected",
        "redis": "connected" if redis_client else "unavailable",
        "celery": "available" if CELERY_AVAILABLE else "unavailable",
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        db = SessionLocal()
        db.execute("SELECT 1" if USE_POSTGRES else "SELECT 1")
        db.close()
    except Exception:
        checks["database"] = "error"
        checks["status"] = "degraded"

    return checks


# =============================================================================
# SECTION 25: FULL FRONTEND (React + Tailwind CSS - Inline HTML/JS/CSS)
# =============================================================================

FRONTEND_HTML = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title id="page-title">NeonWatch - God Level Uptime Monitoring</title>
    <meta name="description" content="God-level uptime monitoring SaaS with neon pink & purple theme">

    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- React CDN -->
    <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <!-- Babel for JSX -->
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <!-- Lucide Icons -->
    <link rel="stylesheet" href="https://unpkg.com/lucide-static@latest/font/lucide.css">

    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'neon-pink': '#F806CC',
                        'neon-purple': '#A855F7',
                        'deep-purple': '#2E0249',
                        'darker-purple': '#1A0130',
                        'mid-purple': '#570A57',
                        'glow-pink': '#FF2CF1',
                        'electric-violet': '#8B5CF6',
                        'neon-green': '#00FF88',
                        'neon-red': '#FF1744',
                        'neon-yellow': '#FFE500',
                        'glass-white': 'rgba(255,255,255,0.08)',
                        'glass-border': 'rgba(248,6,204,0.3)',
                    },
                    boxShadow: {
                        'neon': '0 0 20px rgba(248,6,204,0.5), 0 0 60px rgba(248,6,204,0.2)',
                        'neon-lg': '0 0 30px rgba(248,6,204,0.6), 0 0 80px rgba(248,6,204,0.3)',
                        'neon-purple': '0 0 20px rgba(168,85,247,0.5), 0 0 60px rgba(168,85,247,0.2)',
                        'neon-green': '0 0 15px rgba(0,255,136,0.6)',
                        'neon-red': '0 0 15px rgba(255,23,68,0.6)',
                        'glass': '0 8px 32px rgba(0,0,0,0.37)',
                    },
                    animation: {
                        'glow-pulse': 'glowPulse 2s ease-in-out infinite alternate',
                        'float': 'float 6s ease-in-out infinite',
                        'slide-up': 'slideUp 0.5s ease-out',
                        'fade-in': 'fadeIn 0.5s ease-out',
                        'spin-slow': 'spin 8s linear infinite',
                    },
                    keyframes: {
                        glowPulse: {
                            '0%': { filter: 'drop-shadow(0 0 10px #F806CC) drop-shadow(0 0 30px #A855F7)' },
                            '100%': { filter: 'drop-shadow(0 0 20px #F806CC) drop-shadow(0 0 50px #A855F7) drop-shadow(0 0 70px #F806CC)' },
                        },
                        float: {
                            '0%, 100%': { transform: 'translateY(0px)' },
                            '50%': { transform: 'translateY(-10px)' },
                        },
                        slideUp: {
                            '0%': { opacity: '0', transform: 'translateY(30px)' },
                            '100%': { opacity: '1', transform: 'translateY(0)' },
                        },
                        fadeIn: {
                            '0%': { opacity: '0' },
                            '100%': { opacity: '1' },
                        },
                    },
                    backdropBlur: {
                        'xs': '2px',
                        'glass': '20px',
                    },
                },
            },
        }
    </script>

    <style>
        /* ==================== GLOBAL STYLES ==================== */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }
        html { scroll-behavior: smooth; }

        body {
            font-family: 'Inter', sans-serif;
            background: #0D0015;
            color: #e2e8f0;
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* Background Video */
        #bg-video-container {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            z-index: -2; overflow: hidden;
        }
        #bg-video-container video {
            width: 100%; height: 100%; object-fit: cover;
        }

        /* Dark overlay over video */
        #bg-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            z-index: -1;
            background: linear-gradient(135deg,
                rgba(13,0,21,0.88) 0%,
                rgba(46,2,73,0.85) 30%,
                rgba(87,10,87,0.82) 60%,
                rgba(13,0,21,0.90) 100%);
        }

        /* Animated gradient background fallback */
        .animated-bg {
            background: linear-gradient(-45deg, #0D0015, #2E0249, #570A57, #1A0130);
            background-size: 400% 400%;
            animation: gradientShift 15s ease infinite;
        }

        @keyframes gradientShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* Glassmorphism Card */
        .glass-card {
            background: rgba(13, 0, 21, 0.6);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(248, 6, 204, 0.15);
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4),
                        inset 0 1px 0 rgba(255,255,255,0.05);
        }
        .glass-card:hover {
            border-color: rgba(248, 6, 204, 0.35);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4),
                        0 0 20px rgba(248, 6, 204, 0.1),
                        inset 0 1px 0 rgba(255,255,255,0.05);
        }

        /* Logo glow animation */
        .logo-glow {
            animation: logoGlow 2s ease-in-out infinite alternate;
        }
        @keyframes logoGlow {
            0% {
                text-shadow: 0 0 10px #F806CC, 0 0 20px #F806CC, 0 0 40px #A855F7;
                filter: brightness(1);
            }
            100% {
                text-shadow: 0 0 20px #F806CC, 0 0 40px #F806CC, 0 0 60px #A855F7, 0 0 80px #F806CC;
                filter: brightness(1.2);
            }
        }

        /* Neon button */
        .neon-btn {
            background: linear-gradient(135deg, #F806CC, #A855F7);
            border: none;
            color: white;
            font-weight: 600;
            padding: 10px 24px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 0 15px rgba(248,6,204,0.3);
        }
        .neon-btn:hover {
            box-shadow: 0 0 25px rgba(248,6,204,0.6), 0 0 50px rgba(168,85,247,0.3);
            transform: translateY(-2px);
        }

        .neon-btn-outline {
            background: transparent;
            border: 2px solid #F806CC;
            color: #F806CC;
            padding: 10px 24px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .neon-btn-outline:hover {
            background: rgba(248,6,204,0.15);
            box-shadow: 0 0 20px rgba(248,6,204,0.3);
        }

        /* Neon Input */
        .neon-input {
            background: rgba(13,0,21,0.6);
            border: 1px solid rgba(248,6,204,0.2);
            color: #e2e8f0;
            padding: 12px 16px;
            border-radius: 12px;
            outline: none;
            transition: all 0.3s ease;
            width: 100%;
            font-size: 14px;
        }
        .neon-input:focus {
            border-color: #F806CC;
            box-shadow: 0 0 15px rgba(248,6,204,0.2);
        }
        .neon-input::placeholder {
            color: rgba(255,255,255,0.3);
        }

        /* Status dots */
        .status-dot {
            width: 12px; height: 12px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-up {
            background: #00FF88;
            box-shadow: 0 0 10px #00FF88, 0 0 20px rgba(0,255,136,0.3);
            animation: statusPulse 2s ease-in-out infinite;
        }
        .status-down {
            background: #FF1744;
            box-shadow: 0 0 10px #FF1744, 0 0 20px rgba(255,23,68,0.3);
            animation: statusPulse 1s ease-in-out infinite;
        }
        .status-pending {
            background: #FFE500;
            box-shadow: 0 0 10px #FFE500;
        }
        .status-paused {
            background: #888;
            box-shadow: 0 0 5px #888;
        }

        @keyframes statusPulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.2); }
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0D0015; }
        ::-webkit-scrollbar-thumb {
            background: linear-gradient(#F806CC, #A855F7);
            border-radius: 3px;
        }

        /* Music toggle */
        .music-toggle {
            position: fixed; bottom: 20px; right: 20px; z-index: 1000;
            background: rgba(13,0,21,0.8);
            border: 1px solid rgba(248,6,204,0.3);
            border-radius: 50%;
            width: 50px; height: 50px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }
        .music-toggle:hover {
            border-color: #F806CC;
            box-shadow: 0 0 20px rgba(248,6,204,0.4);
        }
        .music-toggle.playing {
            animation: musicBounce 1s ease-in-out infinite;
        }
        @keyframes musicBounce {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }

        /* Uptime bar */
        .uptime-bar {
            display: flex; gap: 2px; height: 30px; align-items: flex-end;
        }
        .uptime-bar-segment {
            flex: 1; min-width: 3px; border-radius: 2px;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        .uptime-bar-segment:hover {
            opacity: 0.8;
            transform: scaleY(1.2);
        }

        /* Toast notification */
        .toast {
            position: fixed; top: 20px; right: 20px; z-index: 9999;
            padding: 16px 24px;
            border-radius: 12px;
            backdrop-filter: blur(20px);
            animation: slideInRight 0.5s ease-out;
            max-width: 400px;
        }
        .toast-success {
            background: rgba(0,255,136,0.15);
            border: 1px solid rgba(0,255,136,0.3);
            color: #00FF88;
        }
        .toast-error {
            background: rgba(255,23,68,0.15);
            border: 1px solid rgba(255,23,68,0.3);
            color: #FF1744;
        }
        @keyframes slideInRight {
            0% { transform: translateX(100%); opacity: 0; }
            100% { transform: translateX(0); opacity: 1; }
        }

        /* Sidebar */
        .sidebar {
            background: rgba(13,0,21,0.85);
            backdrop-filter: blur(20px);
            border-right: 1px solid rgba(248,6,204,0.1);
        }
        .sidebar-link {
            display: flex; align-items: center; gap: 12px;
            padding: 12px 20px; border-radius: 10px;
            color: rgba(255,255,255,0.6);
            transition: all 0.3s ease;
            text-decoration: none;
            cursor: pointer;
        }
        .sidebar-link:hover, .sidebar-link.active {
            background: rgba(248,6,204,0.1);
            color: #F806CC;
            border-left: 3px solid #F806CC;
        }

        /* Particles */
        .particle {
            position: fixed;
            background: radial-gradient(circle, #F806CC, transparent);
            border-radius: 50%;
            pointer-events: none;
            opacity: 0.15;
            animation: floatParticle 20s linear infinite;
        }
        @keyframes floatParticle {
            0% { transform: translateY(100vh) rotate(0deg); opacity: 0; }
            10% { opacity: 0.15; }
            90% { opacity: 0.15; }
            100% { transform: translateY(-100vh) rotate(720deg); opacity: 0; }
        }

        /* Responsive */
        @media (max-width: 768px) {
            .sidebar { display: none; }
            .sidebar.mobile-open { display: block; position: fixed; z-index: 999; width: 260px; height: 100vh; }
        }

        /* Stat card shimmer effect */
        .shimmer {
            background: linear-gradient(90deg,
                rgba(248,6,204,0) 0%,
                rgba(248,6,204,0.08) 50%,
                rgba(248,6,204,0) 100%);
            background-size: 200% 100%;
            animation: shimmerEffect 2s infinite;
        }
        @keyframes shimmerEffect {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }

        /* Monitor card status stripe */
        .monitor-card { position: relative; overflow: hidden; }
        .monitor-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 4px; height: 100%;
        }
        .monitor-card.status-card-up::before { background: #00FF88; box-shadow: 0 0 10px #00FF88; }
        .monitor-card.status-card-down::before { background: #FF1744; box-shadow: 0 0 10px #FF1744; }
        .monitor-card.status-card-pending::before { background: #FFE500; }
        .monitor-card.status-card-paused::before { background: #888; }

        /* Select styling */
        .neon-select {
            background: rgba(13,0,21,0.6);
            border: 1px solid rgba(248,6,204,0.2);
            color: #e2e8f0;
            padding: 12px 16px;
            border-radius: 12px;
            outline: none;
            appearance: none;
            cursor: pointer;
            width: 100%;
        }
        .neon-select:focus {
            border-color: #F806CC;
            box-shadow: 0 0 15px rgba(248,6,204,0.2);
        }

        /* Spinner */
        .spinner {
            border: 3px solid rgba(248,6,204,0.2);
            border-top: 3px solid #F806CC;
            border-radius: 50%;
            width: 40px; height: 40px;
            animation: spin 0.8s linear infinite;
        }

        /* Toggle switch */
        .toggle-switch {
            position: relative;
            width: 48px; height: 24px;
            background: rgba(255,255,255,0.1);
            border-radius: 24px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .toggle-switch.active {
            background: linear-gradient(135deg, #F806CC, #A855F7);
        }
        .toggle-switch::after {
            content: '';
            position: absolute;
            top: 2px; left: 2px;
            width: 20px; height: 20px;
            background: white;
            border-radius: 50%;
            transition: all 0.3s ease;
        }
        .toggle-switch.active::after {
            left: 26px;
        }

        /* Tab styles */
        .tab-btn {
            padding: 10px 20px;
            border-radius: 10px;
            color: rgba(255,255,255,0.5);
            cursor: pointer;
            transition: all 0.3s ease;
            border: 1px solid transparent;
        }
        .tab-btn.active {
            background: rgba(248,6,204,0.15);
            color: #F806CC;
            border-color: rgba(248,6,204,0.3);
        }
        .tab-btn:hover {
            color: #F806CC;
        }
    </style>
</head>
<body>
    <div id="root"></div>

    <!-- Background Video Container -->
    <div id="bg-video-container"></div>
    <div id="bg-overlay" class="animated-bg"></div>

    <!-- Background Audio -->
    <audio id="bg-audio" loop preload="none"></audio>

    <script type="text/babel">
    // ================================================================
    // NEONWATCH REACT APPLICATION
    // ================================================================

    const { useState, useEffect, useCallback, useRef, useMemo, createContext, useContext } = React;

    // ======== API Configuration ========
    const API_BASE = window.location.origin + '/api';

    const api = {
        async request(method, path, body = null, token = null) {
            const headers = { 'Content-Type': 'application/json' };
            if (token) headers['Authorization'] = `Bearer ${token}`;
            const opts = { method, headers };
            if (body) opts.body = JSON.stringify(body);
            const res = await fetch(API_BASE + path, opts);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Request failed');
            return data;
        },
        get(path, token) { return this.request('GET', path, null, token); },
        post(path, body, token) { return this.request('POST', path, body, token); },
        put(path, body, token) { return this.request('PUT', path, body, token); },
        delete(path, token) { return this.request('DELETE', path, null, token); },
    };

    // ======== Context ========
    const AppContext = createContext();

    const useApp = () => useContext(AppContext);

    // ======== Toast Component ========
    function Toast({ message, type, onClose }) {
        useEffect(() => {
            const timer = setTimeout(onClose, 4000);
            return () => clearTimeout(timer);
        }, []);
        return (
            <div className={`toast toast-${type}`}>
                <div className="flex items-center gap-3">
                    <span>{type === 'success' ? '✅' : '❌'}</span>
                    <span className="font-medium">{message}</span>
                </div>
            </div>
        );
    }

    // ======== Particles ========
    function Particles() {
        return (
            <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
                {[...Array(15)].map((_, i) => (
                    <div key={i} className="particle" style={{
                        width: `${Math.random() * 6 + 2}px`,
                        height: `${Math.random() * 6 + 2}px`,
                        left: `${Math.random() * 100}%`,
                        animationDelay: `${Math.random() * 20}s`,
                        animationDuration: `${Math.random() * 15 + 15}s`,
                    }} />
                ))}
            </div>
        );
    }

    // ======== Spinner ========
    function Spinner({ size = 'md' }) {
        const sizes = { sm: 'w-5 h-5', md: 'w-10 h-10', lg: 'w-16 h-16' };
        return <div className={`spinner ${sizes[size]}`} />;
    }

    // ======== Logo Component ========
    function Logo({ config, size = 'md' }) {
        const sizes = { sm: 'text-xl', md: 'text-3xl', lg: 'text-5xl' };
        if (config?.logo_url) {
            return <img src={config.logo_url} alt="Logo" className={`h-10 animate-glow-pulse logo-glow`} />;
        }
        return (
            <div className={`font-black ${sizes[size]} logo-glow flex items-center gap-2`}>
                <span className="text-neon-pink">⚡</span>
                <span className="bg-gradient-to-r from-neon-pink via-neon-purple to-electric-violet bg-clip-text text-transparent">
                    {config?.site_name || 'NeonWatch'}
                </span>
            </div>
        );
    }

    // ======== Status Dot ========
    function StatusDot({ status }) {
        const cls = {
            up: 'status-up', down: 'status-down',
            pending: 'status-pending', paused: 'status-paused', unknown: 'status-pending'
        };
        return <span className={`status-dot ${cls[status] || 'status-pending'}`} />;
    }

    // ======== Music Toggle ========
    function MusicToggle({ musicUrl }) {
        const [playing, setPlaying] = useState(false);
        const audioRef = useRef(null);

        useEffect(() => {
            audioRef.current = document.getElementById('bg-audio');
            if (musicUrl && audioRef.current) {
                audioRef.current.src = musicUrl;
            }
        }, [musicUrl]);

        const toggle = () => {
            if (!audioRef.current || !musicUrl) return;
            if (playing) {
                audioRef.current.pause();
            } else {
                audioRef.current.play().catch(() => {});
            }
            setPlaying(!playing);
        };

        if (!musicUrl) return null;
        return (
            <button onClick={toggle} className={`music-toggle ${playing ? 'playing' : ''}`}
                    title={playing ? 'Pause Music' : 'Play Music'}>
                <span className="text-neon-pink text-xl">{playing ? '🔊' : '🔇'}</span>
            </button>
        );
    }

    // ======== Login Page ========
    function LoginPage({ onLogin, switchToRegister }) {
        const [login, setLogin] = useState('');
        const [password, setPassword] = useState('');
        const [error, setError] = useState('');
        const [loading, setLoading] = useState(false);

        const handleSubmit = async (e) => {
            e.preventDefault();
            setLoading(true); setError('');
            try {
                const data = await api.post('/auth/login', { login, password });
                onLogin(data.token, data.user);
            } catch (err) { setError(err.message); }
            setLoading(false);
        };

        return (
            <div className="min-h-screen flex items-center justify-center p-4">
                <div className="glass-card p-8 w-full max-w-md animate-slide-up">
                    <div className="text-center mb-8">
                        <Logo size="lg" />
                        <p className="text-white/50 mt-2">Sign in to your monitoring dashboard</p>
                    </div>
                    <form onSubmit={handleSubmit} className="space-y-5">
                        {error && (
                            <div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">
                                {error}
                            </div>
                        )}
                        <div>
                            <label className="text-sm text-white/60 mb-1 block">Username or Email</label>
                            <input type="text" value={login} onChange={e => setLogin(e.target.value)}
                                   className="neon-input" placeholder="Enter username or email" required />
                        </div>
                        <div>
                            <label className="text-sm text-white/60 mb-1 block">Password</label>
                            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                                   className="neon-input" placeholder="Enter password" required />
                        </div>
                        <button type="submit" className="neon-btn w-full py-3 text-lg" disabled={loading}>
                            {loading ? <Spinner size="sm" /> : '⚡ Sign In'}
                        </button>
                    </form>
                    <p className="text-center text-white/40 mt-6 text-sm">
                        Don't have an account?{' '}
                        <span onClick={switchToRegister} className="text-neon-pink cursor-pointer hover:underline">
                            Register
                        </span>
                    </p>
                </div>
            </div>
        );
    }

    // ======== Register Page ========
    function RegisterPage({ onLogin, switchToLogin }) {
        const [form, setForm] = useState({ username: '', email: '', password: '', full_name: '' });
        const [error, setError] = useState('');
        const [loading, setLoading] = useState(false);

        const handleSubmit = async (e) => {
            e.preventDefault();
            setLoading(true); setError('');
            try {
                const data = await api.post('/auth/register', form);
                onLogin(data.token, data.user);
            } catch (err) { setError(err.message); }
            setLoading(false);
        };

        return (
            <div className="min-h-screen flex items-center justify-center p-4">
                <div className="glass-card p-8 w-full max-w-md animate-slide-up">
                    <div className="text-center mb-8">
                        <Logo size="lg" />
                        <p className="text-white/50 mt-2">Create your monitoring account</p>
                    </div>
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {error && (
                            <div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">{error}</div>
                        )}
                        <input type="text" value={form.full_name} onChange={e => setForm({...form, full_name: e.target.value})}
                               className="neon-input" placeholder="Full Name" />
                        <input type="text" value={form.username} onChange={e => setForm({...form, username: e.target.value})}
                               className="neon-input" placeholder="Username" required />
                        <input type="email" value={form.email} onChange={e => setForm({...form, email: e.target.value})}
                               className="neon-input" placeholder="Email" required />
                        <input type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})}
                               className="neon-input" placeholder="Password (min 8 chars)" required />
                        <button type="submit" className="neon-btn w-full py-3 text-lg" disabled={loading}>
                            {loading ? <Spinner size="sm" /> : '🚀 Create Account'}
                        </button>
                    </form>
                    <p className="text-center text-white/40 mt-6 text-sm">
                        Already have an account?{' '}
                        <span onClick={switchToLogin} className="text-neon-pink cursor-pointer hover:underline">Sign In</span>
                    </p>
                </div>
            </div>
        );
    }

    // ======== Stat Card ========
    function StatCard({ icon, label, value, color = 'neon-pink', subtext }) {
        return (
            <div className="glass-card p-5 animate-slide-up">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-2xl">{icon}</span>
                    <span className={`text-xs px-2 py-1 rounded-full bg-${color}/10 text-${color}`}>{subtext}</span>
                </div>
                <p className="text-3xl font-bold bg-gradient-to-r from-neon-pink to-neon-purple bg-clip-text text-transparent">{value}</p>
                <p className="text-sm text-white/50 mt-1">{label}</p>
            </div>
        );
    }

    // ======== Monitor Card ========
    function MonitorCard({ monitor, onClick }) {
        const statusClass = `status-card-${monitor.status}`;
        return (
            <div onClick={() => onClick(monitor)} className={`glass-card monitor-card ${statusClass} p-5 cursor-pointer hover:scale-[1.02] transition-all duration-300 animate-fade-in`}>
                <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                        <StatusDot status={monitor.status} />
                        <h3 className="font-semibold text-white truncate max-w-[200px]">{monitor.name}</h3>
                    </div>
                    <span className="text-xs px-2 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase font-mono">{monitor.monitor_type}</span>
                </div>
                <p className="text-xs text-white/40 truncate mb-3 font-mono">{monitor.url}</p>
                <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                        <p className="text-lg font-bold text-neon-green">{monitor.uptime_percentage?.toFixed(2) || '0.00'}%</p>
                        <p className="text-xs text-white/40">Uptime</p>
                    </div>
                    <div>
                        <p className="text-lg font-bold text-neon-purple">{monitor.last_response_time?.toFixed(0) || '-'}ms</p>
                        <p className="text-xs text-white/40">Response</p>
                    </div>
                    <div>
                        <p className="text-lg font-bold text-white/80">{monitor.total_checks || 0}</p>
                        <p className="text-xs text-white/40">Checks</p>
                    </div>
                </div>
            </div>
        );
    }

    // ======== Create Monitor Modal ========
    function CreateMonitorModal({ onClose, onCreated, token }) {
        const [form, setForm] = useState({
            name: '', url: '', monitor_type: 'http', check_interval: 300,
            timeout: 30, expected_status_code: 200, keyword: '', port: '',
            alert_on_down: true, alert_on_recovery: true, alert_threshold: 1,
        });
        const [loading, setLoading] = useState(false);
        const [error, setError] = useState('');

        const handleSubmit = async (e) => {
            e.preventDefault(); setLoading(true); setError('');
            try {
                const payload = { ...form };
                if (payload.port) payload.port = parseInt(payload.port);
                else delete payload.port;
                if (!payload.keyword) delete payload.keyword;
                const data = await api.post('/monitors', payload, token);
                onCreated(data.monitor);
                onClose();
            } catch (err) { setError(err.message); }
            setLoading(false);
        };

        return (
            <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
                <div className="glass-card p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto animate-slide-up" onClick={e => e.stopPropagation()}>
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-2xl font-bold text-neon-pink">➕ New Monitor</h2>
                        <button onClick={onClose} className="text-white/50 hover:text-white text-2xl">&times;</button>
                    </div>
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {error && <div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">{error}</div>}
                        <div>
                            <label className="text-sm text-white/60 mb-1 block">Monitor Name</label>
                            <input className="neon-input" value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="My Website" required />
                        </div>
                        <div>
                            <label className="text-sm text-white/60 mb-1 block">URL / Host</label>
                            <input className="neon-input" value={form.url} onChange={e => setForm({...form, url: e.target.value})} placeholder="https://example.com" required />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="text-sm text-white/60 mb-1 block">Type</label>
                                <select className="neon-select" value={form.monitor_type} onChange={e => setForm({...form, monitor_type: e.target.value})}>
                                    <option value="http">HTTP(S)</option>
                                    <option value="ping">Ping</option>
                                    <option value="port">Port</option>
                                    <option value="keyword">Keyword</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-sm text-white/60 mb-1 block">Interval (sec)</label>
                                <select className="neon-select" value={form.check_interval} onChange={e => setForm({...form, check_interval: parseInt(e.target.value)})}>
                                    <option value="60">1 min</option>
                                    <option value="180">3 min</option>
                                    <option value="300">5 min</option>
                                    <option value="600">10 min</option>
                                    <option value="1800">30 min</option>
                                    <option value="3600">1 hour</option>
                                </select>
                            </div>
                        </div>
                        {form.monitor_type === 'keyword' && (
                            <div>
                                <label className="text-sm text-white/60 mb-1 block">Keyword to search</label>
                                <input className="neon-input" value={form.keyword} onChange={e => setForm({...form, keyword: e.target.value})} placeholder="Expected keyword" />
                            </div>
                        )}
                        {form.monitor_type === 'port' && (
                            <div>
                                <label className="text-sm text-white/60 mb-1 block">Port Number</label>
                                <input type="number" className="neon-input" value={form.port} onChange={e => setForm({...form, port: e.target.value})} placeholder="443" />
                            </div>
                        )}
                        <div>
                            <label className="text-sm text-white/60 mb-1 block">Timeout (seconds)</label>
                            <input type="number" className="neon-input" value={form.timeout} onChange={e => setForm({...form, timeout: parseInt(e.target.value)})} />
                        </div>
                        <button type="submit" className="neon-btn w-full py-3" disabled={loading}>
                            {loading ? 'Creating...' : '🚀 Create Monitor'}
                        </button>
                    </form>
                </div>
            </div>
        );
    }

    // ======== Monitor Detail View ========
    function MonitorDetail({ monitorId, token, onBack }) {
        const [data, setData] = useState(null);
        const [loading, setLoading] = useState(true);

        useEffect(() => {
            loadDetail();
        }, [monitorId]);

        const loadDetail = async () => {
            setLoading(true);
            try {
                const d = await api.get(`/monitors/${monitorId}`, token);
                setData(d);
            } catch (err) { console.error(err); }
            setLoading(false);
        };

        const triggerCheck = async () => {
            try {
                await api.post(`/monitors/${monitorId}/check`, {}, token);
                setTimeout(loadDetail, 3000);
            } catch (err) { console.error(err); }
        };

        if (loading) return <div className="flex justify-center py-20"><Spinner /></div>;
        if (!data) return <div className="text-center py-20 text-white/50">Monitor not found</div>;

        const m = data.monitor;
        const logs = data.logs || [];

        return (
            <div className="space-y-6 animate-fade-in">
                <div className="flex items-center gap-4 mb-6">
                    <button onClick={onBack} className="neon-btn-outline px-4 py-2">← Back</button>
                    <StatusDot status={m.status} />
                    <h1 className="text-2xl font-bold">{m.name}</h1>
                    <span className="text-xs px-3 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase">{m.monitor_type}</span>
                    <button onClick={triggerCheck} className="neon-btn ml-auto">⚡ Check Now</button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <StatCard icon="📊" label="Uptime" value={`${m.uptime_percentage?.toFixed(2) || 0}%`} subtext="overall" />
                    <StatCard icon="⚡" label="Response Time" value={`${m.last_response_time?.toFixed(0) || '-'}ms`} subtext="last" />
                    <StatCard icon="✅" label="Total Checks" value={m.total_checks || 0} subtext="all time" />
                    <StatCard icon="🔴" label="Downtime Events" value={m.total_down || 0} subtext="failures" />
                </div>

                <div className="glass-card p-5">
                    <h3 className="text-lg font-semibold text-neon-pink mb-2">Monitor URL</h3>
                    <p className="font-mono text-sm text-white/60 break-all">{m.url}</p>
                </div>

                {data.daily_stats && data.daily_stats.length > 0 && (
                    <div className="glass-card p-5">
                        <h3 className="text-lg font-semibold text-neon-pink mb-4">30-Day Uptime</h3>
                        <div className="uptime-bar">
                            {data.daily_stats.map((d, i) => {
                                const uptime = d.uptime_percentage || 100;
                                const color = uptime >= 99.5 ? '#00FF88' : uptime >= 95 ? '#FFE500' : '#FF1744';
                                return (
                                    <div key={i} className="uptime-bar-segment" title={`${d.date}: ${uptime.toFixed(2)}%`}
                                         style={{ height: `${Math.max(uptime * 0.3, 5)}px`, background: color }} />
                                );
                            })}
                        </div>
                    </div>
                )}

                <div className="glass-card p-5">
                    <h3 className="text-lg font-semibold text-neon-pink mb-4">Recent Logs</h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-white/50 border-b border-white/10">
                                    <th className="py-2 text-left">Status</th>
                                    <th className="py-2 text-left">Response</th>
                                    <th className="py-2 text-left">Code</th>
                                    <th className="py-2 text-left">Error</th>
                                    <th className="py-2 text-left">Time</th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.slice(0, 30).map(log => (
                                    <tr key={log.id} className="border-b border-white/5 hover:bg-white/5">
                                        <td className="py-2"><StatusDot status={log.status} /></td>
                                        <td className="py-2 text-neon-purple">{log.response_time?.toFixed(0) || '-'}ms</td>
                                        <td className="py-2">{log.status_code || '-'}</td>
                                        <td className="py-2 text-red-400 truncate max-w-[200px]">{log.error_message || '-'}</td>
                                        <td className="py-2 text-white/40 font-mono text-xs">{new Date(log.created_at).toLocaleString()}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        );
    }

    // ======== Dashboard Page ========
    function DashboardPage({ token, user }) {
        const [dashboard, setDashboard] = useState(null);
        const [loading, setLoading] = useState(true);
        const [showCreate, setShowCreate] = useState(false);
        const [selectedMonitor, setSelectedMonitor] = useState(null);

        const loadDashboard = async () => {
            try {
                const data = await api.get('/dashboard', token);
                setDashboard(data);
            } catch (err) { console.error(err); }
            setLoading(false);
        };

        useEffect(() => { loadDashboard(); const i = setInterval(loadDashboard, 30000); return () => clearInterval(i); }, []);

        if (selectedMonitor) {
            return <MonitorDetail monitorId={selectedMonitor.id} token={token} onBack={() => { setSelectedMonitor(null); loadDashboard(); }} />;
        }

        if (loading) return <div className="flex justify-center py-20"><Spinner /></div>;

        const ov = dashboard?.overview || {};

        return (
            <div className="space-y-6 animate-fade-in">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-neon-pink to-neon-purple bg-clip-text text-transparent">
                            Dashboard
                        </h1>
                        <p className="text-white/40 mt-1">Welcome back, {user.full_name || user.username}! 👋</p>
                    </div>
                    <button onClick={() => setShowCreate(true)} className="neon-btn flex items-center gap-2">
                        <span>➕</span> Add Monitor
                    </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <StatCard icon="📡" label="Total Monitors" value={ov.total_monitors || 0} subtext="active" />
                    <StatCard icon="✅" label="Monitors UP" value={ov.up || 0} subtext={`${ov.down || 0} down`} />
                    <StatCard icon="📊" label="Avg Uptime" value={`${ov.avg_uptime?.toFixed(2) || 100}%`} subtext="overall" />
                    <StatCard icon="⚡" label="Avg Response" value={`${ov.avg_response_time?.toFixed(0) || 0}ms`} subtext="latest" />
                </div>

                {dashboard?.monitors?.length > 0 ? (
                    <div>
                        <h2 className="text-xl font-semibold mb-4 text-white/80">Your Monitors</h2>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {dashboard.monitors.map(m => (
                                <MonitorCard key={m.id} monitor={m} onClick={setSelectedMonitor} />
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="glass-card p-12 text-center">
                        <p className="text-5xl mb-4">📡</p>
                        <h3 className="text-2xl font-bold text-white/80 mb-2">No monitors yet</h3>
                        <p className="text-white/40 mb-6">Create your first monitor to start tracking uptime</p>
                        <button onClick={() => setShowCreate(true)} className="neon-btn">Create First Monitor</button>
                    </div>
                )}

                {showCreate && (
                    <CreateMonitorModal
                        token={token}
                        onClose={() => setShowCreate(false)}
                        onCreated={() => loadDashboard()}
                    />
                )}
            </div>
        );
    }

    // ======== Admin: Site Config Page ========
    function AdminSiteConfigPage({ token }) {
        const [config, setConfig] = useState(null);
        const [loading, setLoading] = useState(true);
        const [saving, setSaving] = useState(false);
        const [toast, setToast] = useState(null);

        useEffect(() => {
            api.get('/site-config', token).then(d => { setConfig(d.config); setLoading(false); });
        }, []);

        const save = async () => {
            setSaving(true);
            try {
                const data = await api.put('/site-config', config, token);
                setConfig(data.config);
                setToast({ message: 'Site config updated!', type: 'success' });
                // Apply changes immediately
                const vid = document.querySelector('#bg-video-container video');
                if (vid && config.bg_video_url) { vid.src = config.bg_video_url; vid.load(); vid.play(); }
                const aud = document.getElementById('bg-audio');
                if (aud && config.bg_music_url) { aud.src = config.bg_music_url; }
            } catch (err) { setToast({ message: err.message, type: 'error' }); }
            setSaving(false);
        };

        if (loading) return <div className="flex justify-center py-20"><Spinner /></div>;

        const Field = ({ label, field, type = 'text', placeholder }) => (
            <div>
                <label className="text-sm text-white/60 mb-1 block">{label}</label>
                {type === 'textarea' ? (
                    <textarea className="neon-input min-h-[80px]" value={config[field] || ''} onChange={e => setConfig({...config, [field]: e.target.value})} placeholder={placeholder} />
                ) : type === 'checkbox' ? (
                    <div className={`toggle-switch ${config[field] ? 'active' : ''}`} onClick={() => setConfig({...config, [field]: !config[field]})} />
                ) : (
                    <input type={type} className="neon-input" value={config[field] || ''} onChange={e => setConfig({...config, [field]: type === 'number' ? parseFloat(e.target.value) : e.target.value})} placeholder={placeholder} />
                )}
            </div>
        );

        return (
            <div className="space-y-6 animate-fade-in">
                {toast && <Toast {...toast} onClose={() => setToast(null)} />}
                <div className="flex items-center justify-between">
                    <h1 className="text-3xl font-bold text-neon-pink">⚙️ Site Configuration</h1>
                    <button onClick={save} className="neon-btn" disabled={saving}>{saving ? 'Saving...' : '💾 Save All'}</button>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="glass-card p-6 space-y-4">
                        <h3 className="text-xl font-semibold text-neon-purple">🏷️ Branding</h3>
                        <Field label="Site Name" field="site_name" placeholder="NeonWatch" />
                        <Field label="Site Tagline" field="site_tagline" placeholder="God-Level Monitoring" />
                        <Field label="Logo URL" field="logo_url" placeholder="https://..." />
                        <Field label="Favicon URL" field="favicon_url" placeholder="https://..." />
                        <Field label="Footer Text" field="footer_text" placeholder="© 2024..." />
                    </div>

                    <div className="glass-card p-6 space-y-4">
                        <h3 className="text-xl font-semibold text-neon-purple">🎬 Media & Background</h3>
                        <Field label="Background Video URL (mp4/webm)" field="bg_video_url" placeholder="https://...video.mp4" />
                        <Field label="Background Music URL (mp3)" field="bg_music_url" placeholder="https://...music.mp3" />
                        <Field label="OG Image URL" field="og_image_url" placeholder="https://...image.png" />
                    </div>

                    <div className="glass-card p-6 space-y-4">
                        <h3 className="text-xl font-semibold text-neon-purple">🎨 Theme Colors</h3>
                        <div className="grid grid-cols-2 gap-4">
                            <Field label="Primary Color" field="primary_color_theme" placeholder="#F806CC" />
                            <Field label="Secondary Color" field="secondary_color_theme" placeholder="#2E0249" />
                            <Field label="Accent Color" field="accent_color" placeholder="#A855F7" />
                            <Field label="Glow Color" field="glow_color" placeholder="#F806CC" />
                        </div>
                        <Field label="Glass Opacity" field="glassmorphism_opacity" type="number" placeholder="0.15" />
                        <Field label="Glass Blur (px)" field="glassmorphism_blur" type="number" placeholder="20" />
                    </div>

                    <div className="glass-card p-6 space-y-4">
                        <h3 className="text-xl font-semibold text-neon-purple">🔧 Features</h3>
                        <div className="space-y-3">
                            <div className="flex items-center justify-between"><span className="text-white/70">Enable Particles</span><Field field="enable_particles" type="checkbox" /></div>
                            <div className="flex items-center justify-between"><span className="text-white/70">Enable Animations</span><Field field="enable_animations" type="checkbox" /></div>
                            <div className="flex items-center justify-between"><span className="text-white/70">Maintenance Mode</span><Field field="maintenance_mode" type="checkbox" /></div>
                            <div className="flex items-center justify-between"><span className="text-white/70">Signup Enabled</span><Field field="signup_enabled" type="checkbox" /></div>
                        </div>
                        <Field label="Max Free Monitors" field="max_free_monitors" type="number" placeholder="10" />
                        <Field label="Max Pro Monitors" field="max_pro_monitors" type="number" placeholder="100" />
                    </div>

                    <div className="glass-card p-6 space-y-4 lg:col-span-2">
                        <h3 className="text-xl font-semibold text-neon-purple">🔍 SEO & Analytics</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <Field label="Meta Title" field="meta_title" placeholder="NeonWatch..." />
                            <Field label="Google Analytics ID" field="google_analytics_id" placeholder="G-XXXXXXX" />
                        </div>
                        <Field label="Meta Description" field="meta_description" type="textarea" placeholder="Description..." />
                        <Field label="Custom CSS" field="custom_css" type="textarea" placeholder=".my-class { ... }" />
                    </div>
                </div>
            </div>
        );
    }

    // ======== Admin: Users Management ========
    function AdminUsersPage({ token }) {
        const [users, setUsers] = useState([]);
        const [loading, setLoading] = useState(true);
        const [search, setSearch] = useState('');
        const [toast, setToast] = useState(null);

        const loadUsers = async () => {
            try {
                const data = await api.get(`/admin/users?search=${search}&limit=100`, token);
                setUsers(data.users);
            } catch (err) { console.error(err); }
            setLoading(false);
        };

        useEffect(() => { loadUsers(); }, [search]);

        const banUser = async (userId) => {
            try {
                await api.post(`/admin/users/${userId}/ban`, 'Violated terms of service', token);
                setToast({ message: 'User banned', type: 'success' });
                loadUsers();
            } catch (err) { setToast({ message: err.message, type: 'error' }); }
        };

        const unbanUser = async (userId) => {
            try {
                await api.post(`/admin/users/${userId}/unban`, {}, token);
                setToast({ message: 'User unbanned', type: 'success' });
                loadUsers();
            } catch (err) { setToast({ message: err.message, type: 'error' }); }
        };

        return (
            <div className="space-y-6 animate-fade-in">
                {toast && <Toast {...toast} onClose={() => setToast(null)} />}
                <h1 className="text-3xl font-bold text-neon-pink">👥 User Management</h1>
                <input className="neon-input max-w-md" value={search} onChange={e => setSearch(e.target.value)} placeholder="🔍 Search users..." />

                {loading ? <Spinner /> : (
                    <div className="glass-card overflow-hidden">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="bg-neon-pink/5 text-neon-pink">
                                    <th className="p-3 text-left">User</th>
                                    <th className="p-3 text-left">Email</th>
                                    <th className="p-3 text-left">Role</th>
                                    <th className="p-3 text-left">Plan</th>
                                    <th className="p-3 text-left">Monitors</th>
                                    <th className="p-3 text-left">Status</th>
                                    <th className="p-3 text-left">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {users.map(u => (
                                    <tr key={u.id} className="border-b border-white/5 hover:bg-white/5">
                                        <td className="p-3 font-semibold">{u.username}</td>
                                        <td className="p-3 text-white/60">{u.email}</td>
                                        <td className="p-3"><span className="px-2 py-1 rounded-full text-xs bg-neon-purple/20 text-neon-purple">{u.role}</span></td>
                                        <td className="p-3 text-white/60">{u.plan}</td>
                                        <td className="p-3">{u.monitor_count}</td>
                                        <td className="p-3">{u.is_banned ? <span className="text-neon-red">Banned</span> : <span className="text-neon-green">Active</span>}</td>
                                        <td className="p-3">
                                            {u.is_banned ? (
                                                <button onClick={() => unbanUser(u.id)} className="text-neon-green hover:underline text-xs">Unban</button>
                                            ) : (
                                                <button onClick={() => banUser(u.id)} className="text-neon-red hover:underline text-xs">Ban</button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        );
    }

    // ======== Admin: Stats Page ========
    function AdminStatsPage({ token }) {
        const [stats, setStats] = useState(null);
        const [loading, setLoading] = useState(true);

        useEffect(() => {
            api.get('/admin/stats', token).then(d => { setStats(d.stats); setLoading(false); });
        }, []);

        if (loading) return <div className="flex justify-center py-20"><Spinner /></div>;

        return (
            <div className="space-y-6 animate-fade-in">
                <h1 className="text-3xl font-bold text-neon-pink">📊 System Statistics</h1>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <StatCard icon="👥" label="Total Users" value={stats.total_users} subtext={`${stats.new_users_week} this week`} />
                    <StatCard icon="📡" label="Total Monitors" value={stats.total_monitors} subtext={`${stats.active_monitors} active`} />
                    <StatCard icon="✅" label="Total Checks" value={stats.total_checks?.toLocaleString()} subtext="all time" />
                    <StatCard icon="🔴" label="Incidents" value={stats.total_incidents} subtext={`${stats.open_incidents} open`} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="glass-card p-6">
                        <h3 className="text-lg font-semibold text-neon-purple mb-4">Monitor Types</h3>
                        {Object.entries(stats.monitor_types || {}).map(([type, count]) => (
                            <div key={type} className="flex justify-between py-2 border-b border-white/5">
                                <span className="text-white/70 uppercase">{type}</span>
                                <span className="text-neon-pink font-bold">{count}</span>
                            </div>
                        ))}
                    </div>
                    <div className="glass-card p-6">
                        <h3 className="text-lg font-semibold text-neon-purple mb-4">Plan Distribution</h3>
                        {Object.entries(stats.plan_distribution || {}).map(([plan, count]) => (
                            <div key={plan} className="flex justify-between py-2 border-b border-white/5">
                                <span className="text-white/70 uppercase">{plan}</span>
                                <span className="text-neon-pink font-bold">{count}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    // ======== Settings Page ========
    function SettingsPage({ token, user, onUpdate }) {
        const [form, setForm] = useState({
            full_name: user.full_name || '',
            notification_email: user.notification_email || '',
            webhook_url: user.webhook_url || '',
            discord_webhook: user.discord_webhook || '',
            slack_webhook: user.slack_webhook || '',
            timezone: user.timezone || 'UTC',
        });
        const [toast, setToast] = useState(null);
        const [saving, setSaving] = useState(false);

        const save = async () => {
            setSaving(true);
            try {
                const data = await api.put('/auth/me', form, token);
                onUpdate(data.user);
                setToast({ message: 'Settings saved!', type: 'success' });
            } catch (err) { setToast({ message: err.message, type: 'error' }); }
            setSaving(false);
        };

        return (
            <div className="space-y-6 animate-fade-in max-w-2xl">
                {toast && <Toast {...toast} onClose={() => setToast(null)} />}
                <h1 className="text-3xl font-bold text-neon-pink">⚙️ Account Settings</h1>
                <div className="glass-card p-6 space-y-4">
                    <h3 className="text-lg font-semibold text-neon-purple">Profile</h3>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Full Name</label>
                        <input className="neon-input" value={form.full_name} onChange={e => setForm({...form, full_name: e.target.value})} />
                    </div>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Timezone</label>
                        <input className="neon-input" value={form.timezone} onChange={e => setForm({...form, timezone: e.target.value})} />
                    </div>
                </div>
                <div className="glass-card p-6 space-y-4">
                    <h3 className="text-lg font-semibold text-neon-purple">Alert Channels</h3>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Notification Email</label>
                        <input className="neon-input" value={form.notification_email} onChange={e => setForm({...form, notification_email: e.target.value})} placeholder="alerts@example.com" />
                    </div>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Webhook URL</label>
                        <input className="neon-input" value={form.webhook_url} onChange={e => setForm({...form, webhook_url: e.target.value})} placeholder="https://..." />
                    </div>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Discord Webhook</label>
                        <input className="neon-input" value={form.discord_webhook} onChange={e => setForm({...form, discord_webhook: e.target.value})} placeholder="https://discord.com/api/webhooks/..." />
                    </div>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Slack Webhook</label>
                        <input className="neon-input" value={form.slack_webhook} onChange={e => setForm({...form, slack_webhook: e.target.value})} placeholder="https://hooks.slack.com/..." />
                    </div>
                </div>
                <div className="glass-card p-6 space-y-4">
                    <h3 className="text-lg font-semibold text-neon-purple">API Access</h3>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">API Key</label>
                        <input className="neon-input font-mono" value={user.api_key} readOnly />
                    </div>
                    <div>
                        <label className="text-sm text-white/60 mb-1 block">Plan</label>
                        <span className="px-3 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase font-semibold">{user.plan}</span>
                        <span className="text-white/40 ml-3">({user.max_monitors} monitors max)</span>
                    </div>
                </div>
                <button onClick={save} className="neon-btn w-full py-3" disabled={saving}>{saving ? 'Saving...' : '💾 Save Settings'}</button>
            </div>
        );
    }

    // ======== Sidebar ========
    function Sidebar({ currentPage, setPage, user, onLogout, siteConfig }) {
        const isAdmin = user.role === 'admin' || user.role === 'superadmin';

        const links = [
            { id: 'dashboard', label: 'Dashboard', icon: '📊' },
            { id: 'monitors', label: 'Monitors', icon: '📡' },
            { id: 'settings', label: 'Settings', icon: '⚙️' },
        ];
        const adminLinks = [
            { id: 'admin-stats', label: 'System Stats', icon: '📈' },
            { id: 'admin-users', label: 'Users', icon: '👥' },
            { id: 'admin-config', label: 'Site Config', icon: '🎨' },
        ];

        return (
            <div className="sidebar w-64 min-h-screen p-4 flex flex-col">
                <div className="mb-8 px-2">
                    <Logo config={siteConfig} size="sm" />
                </div>

                <nav className="flex-1 space-y-1">
                    {links.map(link => (
                        <div key={link.id} className={`sidebar-link ${currentPage === link.id ? 'active' : ''}`} onClick={() => setPage(link.id)}>
                            <span className="text-xl">{link.icon}</span>
                            <span>{link.label}</span>
                        </div>
                    ))}

                    {isAdmin && (
                        <>
                            <div className="mt-6 mb-2 px-4 text-xs text-neon-pink/60 uppercase tracking-wider font-semibold">Admin Panel</div>
                            {adminLinks.map(link => (
                                <div key={link.id} className={`sidebar-link ${currentPage === link.id ? 'active' : ''}`} onClick={() => setPage(link.id)}>
                                    <span className="text-xl">{link.icon}</span>
                                    <span>{link.label}</span>
                                </div>
                            ))}
                        </>
                    )}
                </nav>

                <div className="mt-auto pt-4 border-t border-white/10">
                    <div className="px-4 py-2">
                        <p className="text-sm font-semibold text-white/80">{user.full_name || user.username}</p>
                        <p className="text-xs text-white/40">{user.email}</p>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-neon-purple/20 text-neon-purple mt-1 inline-block">{user.role}</span>
                    </div>
                    <div className="sidebar-link mt-2 text-red-400" onClick={onLogout}>
                        <span>🚪</span>
                        <span>Logout</span>
                    </div>
                </div>
            </div>
        );
    }

    // ======== Main App ========
    function App() {
        const [token, setToken] = useState(localStorage.getItem('nw_token'));
        const [user, setUser] = useState(null);
        const [page, setPage] = useState('dashboard');
        const [authPage, setAuthPage] = useState('login');
        const [siteConfig, setSiteConfig] = useState(null);
        const [loading, setLoading] = useState(true);

        // Load site config
        useEffect(() => {
            api.get('/site-config').then(d => {
                setSiteConfig(d.config);
                document.title = d.config.meta_title || d.config.site_name || 'NeonWatch';

                // Set background video
                const vidContainer = document.getElementById('bg-video-container');
                if (d.config.bg_video_url && vidContainer) {
                    vidContainer.innerHTML = `<video autoplay muted loop playsinline><source src="${d.config.bg_video_url}" type="video/mp4"></video>`;
                }

                // Set background music source
                const audio = document.getElementById('bg-audio');
                if (d.config.bg_music_url && audio) {
                    audio.src = d.config.bg_music_url;
                }
            }).catch(() => {});
        }, []);

        // Validate token on load
        useEffect(() => {
            if (token) {
                api.get('/auth/me', token).then(d => {
                    setUser(d.user);
                    setLoading(false);
                }).catch(() => {
                    localStorage.removeItem('nw_token');
                    setToken(null);
                    setLoading(false);
                });
            } else {
                setLoading(false);
            }
        }, [token]);

        const handleLogin = (newToken, userData) => {
            localStorage.setItem('nw_token', newToken);
            setToken(newToken);
            setUser(userData);
        };

        const handleLogout = () => {
            localStorage.removeItem('nw_token');
            setToken(null);
            setUser(null);
            setPage('dashboard');
        };

        if (loading) {
            return (
                <div className="min-h-screen flex items-center justify-center">
                    <div className="text-center">
                        <Spinner size="lg" />
                        <p className="mt-4 text-neon-pink/60 animate-pulse">Loading NeonWatch...</p>
                    </div>
                </div>
            );
        }

        // Not authenticated
        if (!token || !user) {
            return (
                <div>
                    <Particles />
                    {authPage === 'login' ? (
                        <LoginPage onLogin={handleLogin} switchToRegister={() => setAuthPage('register')} />
                    ) : (
                        <RegisterPage onLogin={handleLogin} switchToLogin={() => setAuthPage('login')} />
                    )}
                    <MusicToggle musicUrl={siteConfig?.bg_music_url} />
                </div>
            );
        }

        // Authenticated - render dashboard
        const renderPage = () => {
            switch (page) {
                case 'dashboard': return <DashboardPage token={token} user={user} />;
                case 'monitors': return <DashboardPage token={token} user={user} />;
                case 'settings': return <SettingsPage token={token} user={user} onUpdate={setUser} />;
                case 'admin-stats': return <AdminStatsPage token={token} />;
                case 'admin-users': return <AdminUsersPage token={token} />;
                case 'admin-config': return <AdminSiteConfigPage token={token} />;
                default: return <DashboardPage token={token} user={user} />;
            }
        };

        return (
            <div className="flex min-h-screen">
                <Particles />
                <Sidebar currentPage={page} setPage={setPage} user={user} onLogout={handleLogout} siteConfig={siteConfig} />
                <main className="flex-1 p-6 md:p-8 overflow-y-auto relative z-10 min-h-screen">
                    {renderPage()}
                </main>
                <MusicToggle musicUrl={siteConfig?.bg_music_url} />
            </div>
        );
    }

    // ======== RENDER ========
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(<App />);
    </script>
</body>
</html>
"""


# =============================================================================
# SECTION 26: SERVE FRONTEND
# =============================================================================

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def serve_frontend():
    """Serve the full React SPA frontend."""
    return HTMLResponse(content=FRONTEND_HTML)


@app.get("/dashboard", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/register", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/admin", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/admin/{path:path}", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/settings", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/monitors", response_class=HTMLResponse, tags=["Frontend"])
@app.get("/monitors/{path:path}", response_class=HTMLResponse, tags=["Frontend"])
async def serve_frontend_routes():
    """Serve the SPA for all client-side routes."""
    return HTMLResponse(content=FRONTEND_HTML)


# =============================================================================
# SECTION 27: PUBLIC STATUS PAGE FRONTEND
# =============================================================================

STATUS_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Status Page - NeonWatch</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
    body { font-family: 'Inter', sans-serif; background: linear-gradient(135deg, #0D0015, #2E0249, #1A0130); color: #e2e8f0; min-height: 100vh; }
    .glass { background: rgba(13,0,21,0.6); backdrop-filter: blur(20px); border: 1px solid rgba(248,6,204,0.15); border-radius: 16px; }
    .status-up { color: #00FF88; } .status-down { color: #FF1744; }
    .dot-up { background: #00FF88; box-shadow: 0 0 10px #00FF88; }
    .dot-down { background: #FF1744; box-shadow: 0 0 10px #FF1744; }
</style>
</head><body class="p-4 md:p-8">
<div id="status-root" class="max-w-4xl mx-auto"></div>
<script>
const slug = window.location.pathname.split('/status/')[1];
if (slug) {
    fetch('/api/status/' + slug).then(r => r.json()).then(data => {
        if (!data.success) { document.getElementById('status-root').innerHTML = '<p class="text-center text-xl mt-20">Status page not found.</p>'; return; }
        const p = data.page;
        let html = `<div class="text-center mb-8"><h1 class="text-4xl font-bold" style="background: linear-gradient(to right, #F806CC, #A855F7); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">${p.title}</h1>`;
        if (p.description) html += `<p class="text-white/50 mt-2">${p.description}</p>`;
        html += `<p class="mt-4 text-2xl font-bold ${data.overall_uptime >= 99 ? 'status-up' : 'status-down'}">${data.overall_uptime.toFixed(2)}% Overall Uptime</p></div>`;
        html += '<div class="space-y-4">';
        data.monitors.forEach(m => {
            const isUp = m.status === 'up';
            html += `<div class="glass p-5"><div class="flex items-center justify-between"><div class="flex items-center gap-3"><span class="w-3 h-3 rounded-full ${isUp ? 'dot-up' : 'dot-down'}"></span><h3 class="font-semibold text-lg">${m.name}</h3></div><span class="${isUp ? 'status-up' : 'status-down'} font-bold">${isUp ? 'Operational' : 'Down'}</span></div><div class="mt-3 flex gap-1 h-6">`;
            if (m.daily && m.daily.length > 0) {
                m.daily.forEach(d => {
                    const u = d.uptime_percentage || 100;
                    const c = u >= 99.5 ? '#00FF88' : u >= 95 ? '#FFE500' : '#FF1744';
                    html += `<div style="flex:1;background:${c};border-radius:2px;min-width:3px;" title="${d.date}: ${u.toFixed(1)}%"></div>`;
                });
            }
            html += `</div><div class="flex justify-between mt-2 text-xs text-white/40"><span>30 days ago</span><span>Today</span></div><p class="text-sm text-white/50 mt-2">Uptime: ${(m.uptime_percentage || 100).toFixed(2)}% | Response: ${m.last_response_time?.toFixed(0) || '-'}ms</p></div>`;
        });
        html += '</div><p class="text-center text-white/30 text-sm mt-8">Powered by NeonWatch ⚡</p>';
        document.getElementById('status-root').innerHTML = html;
    });
}
</script></body></html>
"""


@app.get("/status/{slug}", response_class=HTMLResponse, tags=["Frontend"])
async def serve_status_page(slug: str):
    """Serve the public status page HTML."""
    return HTMLResponse(content=STATUS_PAGE_HTML)


# =============================================================================
# SECTION 28: ERROR HANDLERS
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "detail": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "Internal server error", "status_code": 500},
    )


# =============================================================================
# SECTION 29: MIDDLEWARE - Request Logging
# =============================================================================

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all incoming requests."""
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 2)

    if not request.url.path.startswith("/api/health"):
        logger.debug(
            f"{request.method} {request.url.path} -> {response.status_code} ({elapsed}ms)"
        )

    response.headers["X-Response-Time"] = f"{elapsed}ms"
    response.headers["X-Powered-By"] = "NeonWatch/1.0"
    return response


# =============================================================================
# SECTION 30: MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for running the application."""
    import uvicorn

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║   ⚡ NEONWATCH - GOD LEVEL UPTIME MONITORING ⚡              ║
    ║                                                              ║
    ║   🌐 Frontend:  http://localhost:8000                        ║
    ║   📚 API Docs:  http://localhost:8000/docs                   ║
    ║   🔐 Admin:     admin / admin123456                          ║
    ║                                                              ║
    ║   Theme: Neon Pink & Purple Gradient 💜💖                     ║
    ║   Status: KHATARNAK MODE ACTIVATED 🔥                        ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "monitoring:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
        workers=1,
        access_log=True,
    )


if __name__ == "__main__":
    main()