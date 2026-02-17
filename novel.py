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
║          NEONWATCH - GOD LEVEL UPTIME MONITORING SAAS                        ║
║          Neon Pink & Purple Gradient | Enterprise Grade | ASGI Ready         ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# =============================================================================
# SECTION 0: IMPORTS
# =============================================================================

import os
import sys
import json
import uuid
import hashlib
import socket
import time
import asyncio
import logging
import smtplib
import platform
import ssl
import re
from datetime import datetime, timedelta, timezone, date as date_type
from typing import Optional, List, Dict, Any, Union
from enum import Enum as PyEnum
from contextlib import asynccontextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# FastAPI
from fastapi import (
    FastAPI, HTTPException, Depends, Request, Response,
    Query, Body, BackgroundTasks, WebSocket, WebSocketDisconnect,
    status as http_status
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# SQLAlchemy
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    Float, DateTime, ForeignKey, Index, UniqueConstraint,
    func, and_, or_, desc, asc, Date, event, text as sa_text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    sessionmaker, relationship, Session, joinedload, selectinload
)

# Pydantic
from pydantic import BaseModel, Field

# Auth
import jwt as pyjwt
from passlib.context import CryptContext

# HTTP Client
import httpx


# =============================================================================
# SECTION 1: CONFIGURATION
# =============================================================================

class Settings:
    """Application settings from environment variables."""
    APP_NAME: str = "NeonWatch - God Level Uptime Monitor"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "neon-pink-purple-ultra-secret-key-2024-khatarnak-edition")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 72

    # Database - SQLite for simplicity on Render
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./neonwatch.db")

    # Fix Render's postgres:// to postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    # Email (optional)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "noreply@neonwatch.io")

    DEFAULT_CHECK_INTERVAL: int = 300
    HTTP_TIMEOUT: int = 30


settings = Settings()


# =============================================================================
# SECTION 2: LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NeonWatch")


# =============================================================================
# SECTION 3: DATABASE ENGINE & SESSION
# =============================================================================

is_sqlite = "sqlite" in settings.DATABASE_URL

engine_kwargs = {"pool_pre_ping": True, "echo": False}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_recycle": 3600})

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# SECTION 4: IN-MEMORY CACHE (No Redis required)
# =============================================================================

_cache: Dict[str, Any] = {}


def cache_set(key: str, value: Any, ttl: int = 300):
    _cache[key] = {"value": value, "expires": time.time() + ttl}


def cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if entry and entry["expires"] > time.time():
        return entry["value"]
    if entry:
        del _cache[key]
    return None


def cache_delete(key: str):
    _cache.pop(key, None)


# =============================================================================
# SECTION 5: PASSWORD & JWT UTILS
# =============================================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_jwt_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return pyjwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Optional[dict]:
    try:
        return pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None


# =============================================================================
# SECTION 6: DATABASE MODELS
# =============================================================================

class MonitorType(str, PyEnum):
    HTTP = "http"
    HTTPS = "https"
    PING = "ping"
    PORT = "port"
    KEYWORD = "keyword"


class MonitorStatus(str, PyEnum):
    UP = "up"
    DOWN = "down"
    PENDING = "pending"
    PAUSED = "paused"


class UserRole(str, PyEnum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class UserPlan(str, PyEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ---- User ----
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
    email_verified = Column(Boolean, default=False)
    timezone_str = Column(String(64), default="UTC")
    notification_email = Column(String(255), nullable=True)
    webhook_url = Column(Text, nullable=True)
    slack_webhook = Column(Text, nullable=True)
    discord_webhook = Column(Text, nullable=True)
    telegram_chat_id = Column(String(64), nullable=True)
    api_key = Column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    max_monitors = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    monitors = relationship("Monitor", back_populates="owner", cascade="all, delete-orphan")
    alert_contacts = relationship("AlertContact", back_populates="owner", cascade="all, delete-orphan")
    status_pages = relationship("StatusPage", back_populates="owner", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "uid": self.uid, "username": self.username,
            "email": self.email, "full_name": self.full_name,
            "avatar_url": self.avatar_url, "role": self.role, "plan": self.plan,
            "is_active": self.is_active, "is_banned": self.is_banned,
            "ban_reason": self.ban_reason, "timezone": self.timezone_str,
            "notification_email": self.notification_email,
            "webhook_url": self.webhook_url, "slack_webhook": self.slack_webhook,
            "discord_webhook": self.discord_webhook,
            "max_monitors": self.max_monitors, "api_key": self.api_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "monitor_count": len(self.monitors) if self.monitors else 0,
        }


# ---- Monitor ----
class Monitor(Base):
    __tablename__ = "monitors"
    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    monitor_type = Column(String(20), default=MonitorType.HTTP.value)
    status = Column(String(20), default=MonitorStatus.PENDING.value)
    check_interval = Column(Integer, default=300)
    timeout = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    http_method = Column(String(10), default="GET")
    http_headers = Column(Text, nullable=True)
    http_body = Column(Text, nullable=True)
    expected_status_code = Column(Integer, default=200)
    follow_redirects = Column(Boolean, default=True)
    verify_ssl = Column(Boolean, default=True)
    keyword = Column(String(500), nullable=True)
    keyword_should_exist = Column(Boolean, default=True)
    port = Column(Integer, nullable=True)
    last_check_at = Column(DateTime, nullable=True)
    last_status_change = Column(DateTime, nullable=True)
    last_response_time = Column(Float, nullable=True)
    total_checks = Column(Integer, default=0)
    total_up = Column(Integer, default=0)
    total_down = Column(Integer, default=0)
    uptime_percentage = Column(Float, default=100.0)
    ssl_expiry_date = Column(DateTime, nullable=True)
    ssl_days_remaining = Column(Integer, nullable=True)
    alert_on_down = Column(Boolean, default=True)
    alert_on_recovery = Column(Boolean, default=True)
    alert_threshold = Column(Integer, default=1)
    consecutive_failures = Column(Integer, default=0)
    tags = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="monitors")
    logs = relationship("MonitorLog", back_populates="monitor", cascade="all, delete-orphan",
                         order_by="desc(MonitorLog.created_at)")
    daily_stats = relationship("DailyStats", back_populates="monitor", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="monitor", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "uid": self.uid, "user_id": self.user_id,
            "name": self.name, "url": self.url, "monitor_type": self.monitor_type,
            "status": self.status, "check_interval": self.check_interval,
            "timeout": self.timeout, "is_active": self.is_active,
            "http_method": self.http_method,
            "expected_status_code": self.expected_status_code,
            "keyword": self.keyword, "port": self.port,
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_response_time": self.last_response_time,
            "total_checks": self.total_checks, "total_up": self.total_up,
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


# ---- Monitor Log ----
class MonitorLog(Base):
    __tablename__ = "monitor_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    response_time = Column(Float, nullable=True)
    status_code = Column(Integer, nullable=True)
    response_body_snippet = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    ssl_valid = Column(Boolean, nullable=True)
    content_length = Column(Integer, nullable=True)
    headers_snapshot = Column(Text, nullable=True)
    check_region = Column(String(50), default="default")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    monitor = relationship("Monitor", back_populates="logs")

    def to_dict(self):
        return {
            "id": self.id, "monitor_id": self.monitor_id, "status": self.status,
            "response_time": self.response_time, "status_code": self.status_code,
            "error_message": self.error_message, "ip_address": self.ip_address,
            "ssl_valid": self.ssl_valid, "content_length": self.content_length,
            "check_region": self.check_region,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Daily Stats ----
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

    __table_args__ = (UniqueConstraint('monitor_id', 'date', name='uq_monitor_date'),)
    monitor = relationship("Monitor", back_populates="daily_stats")

    def to_dict(self):
        return {
            "id": self.id, "monitor_id": self.monitor_id,
            "date": self.date.isoformat() if self.date else None,
            "total_checks": self.total_checks, "up_checks": self.up_checks,
            "down_checks": self.down_checks,
            "uptime_percentage": self.uptime_percentage,
            "avg_response_time": self.avg_response_time,
            "min_response_time": self.min_response_time,
            "max_response_time": self.max_response_time,
        }


# ---- Incident ----
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

    monitor = relationship("Monitor", back_populates="incidents")

    def to_dict(self):
        return {
            "id": self.id, "uid": self.uid, "monitor_id": self.monitor_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
            "cause": self.cause, "is_resolved": self.is_resolved,
        }


# ---- Alert Contact ----
class AlertContact(Base):
    __tablename__ = "alert_contacts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    alert_type = Column(String(20), nullable=False)
    value = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="alert_contacts")

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "alert_type": self.alert_type,
            "value": self.value, "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Status Page ----
class StatusPage(Base):
    __tablename__ = "status_pages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug = Column(String(128), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    monitor_ids = Column(Text, nullable=True)
    is_public = Column(Boolean, default=True)
    custom_domain = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="status_pages")

    def to_dict(self):
        return {
            "id": self.id, "uid": self.uid, "slug": self.slug,
            "title": self.title, "description": self.description,
            "monitor_ids": json.loads(self.monitor_ids) if self.monitor_ids else [],
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---- Site Config (SINGLETON CMS) ----
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
    footer_text = Column(Text, default="© 2024 NeonWatch. All rights reserved.")
    maintenance_mode = Column(Boolean, default=False)
    maintenance_message = Column(Text, default="We'll be back soon!")
    signup_enabled = Column(Boolean, default=True)
    default_user_plan = Column(String(20), default="free")
    max_free_monitors = Column(Integer, default=10)
    max_pro_monitors = Column(Integer, default=100)
    meta_title = Column(String(255), default="NeonWatch - Uptime Monitoring")
    meta_description = Column(Text, default="God-level uptime monitoring SaaS")
    og_image_url = Column(Text, default="")
    google_analytics_id = Column(String(50), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "site_name": self.site_name,
            "site_tagline": self.site_tagline, "logo_url": self.logo_url,
            "favicon_url": self.favicon_url, "bg_video_url": self.bg_video_url,
            "bg_music_url": self.bg_music_url,
            "primary_color_theme": self.primary_color_theme,
            "secondary_color_theme": self.secondary_color_theme,
            "accent_color": self.accent_color, "glow_color": self.glow_color,
            "glassmorphism_opacity": self.glassmorphism_opacity,
            "glassmorphism_blur": self.glassmorphism_blur,
            "enable_particles": self.enable_particles,
            "enable_animations": self.enable_animations,
            "custom_css": self.custom_css, "footer_text": self.footer_text,
            "maintenance_mode": self.maintenance_mode,
            "signup_enabled": self.signup_enabled,
            "max_free_monitors": self.max_free_monitors,
            "max_pro_monitors": self.max_pro_monitors,
            "meta_title": self.meta_title, "meta_description": self.meta_description,
            "og_image_url": self.og_image_url,
            "google_analytics_id": self.google_analytics_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ---- Audit Log ----
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "action": self.action,
            "target_type": self.target_type, "target_id": self.target_id,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# SECTION 7: PYDANTIC SCHEMAS
# =============================================================================

class UserRegisterSchema(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None


class UserLoginSchema(BaseModel):
    login: str
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
    url: str
    monitor_type: str = "http"
    check_interval: int = Field(default=300, ge=60, le=86400)
    timeout: int = Field(default=30, ge=5, le=120)
    http_method: str = "GET"
    http_headers: Optional[str] = None
    http_body: Optional[str] = None
    expected_status_code: int = 200
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
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(401, "Authentication required")
    payload = decode_jwt_token(credentials.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_banned:
        raise HTTPException(403, f"Account banned: {user.ban_reason or 'Contact admin'}")
    if not user.is_active:
        raise HTTPException(403, "Account deactivated")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in [UserRole.ADMIN.value, UserRole.SUPERADMIN.value]:
        raise HTTPException(403, "Admin access required")
    return user


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.SUPERADMIN.value:
        raise HTTPException(403, "Super Admin access required")
    return user


# =============================================================================
# SECTION 9: MONITORING ENGINE
# =============================================================================

class MonitoringEngine:
    """Core monitoring engine: HTTP, Ping, Port, Keyword checks."""

    @staticmethod
    async def check_http(monitor: Monitor) -> dict:
        result = {
            "status": MonitorStatus.DOWN.value, "response_time": None,
            "status_code": None, "error_message": None, "ip_address": None,
            "ssl_valid": None, "content_length": None,
            "response_body_snippet": None, "headers_snapshot": None,
        }
        headers = {}
        if monitor.http_headers:
            try:
                headers = json.loads(monitor.http_headers)
            except json.JSONDecodeError:
                pass
        headers.setdefault("User-Agent", "NeonWatch/2.0 Uptime Monitor")
        try:
            start = time.time()
            async with httpx.AsyncClient(
                timeout=monitor.timeout,
                follow_redirects=monitor.follow_redirects,
                verify=monitor.verify_ssl,
            ) as client:
                response = await client.request(
                    method=monitor.http_method or "GET", url=monitor.url,
                    headers=headers, content=monitor.http_body or None,
                )
            elapsed = (time.time() - start) * 1000
            result["response_time"] = round(elapsed, 2)
            result["status_code"] = response.status_code
            result["content_length"] = len(response.content)
            result["response_body_snippet"] = response.text[:500] if response.text else None
            resp_hdrs = dict(response.headers)
            result["headers_snapshot"] = json.dumps({k: v for k, v in list(resp_hdrs.items())[:15]})
            expected = monitor.expected_status_code or 200
            if response.status_code == expected or (200 <= response.status_code < 400):
                result["status"] = MonitorStatus.UP.value
            else:
                result["error_message"] = f"Expected {expected}, got {response.status_code}"
            if monitor.url.startswith("https://"):
                result["ssl_valid"] = True
            try:
                from urllib.parse import urlparse
                hostname = urlparse(monitor.url).hostname
                if hostname:
                    result["ip_address"] = socket.gethostbyname(hostname)
            except Exception:
                pass
        except httpx.TimeoutException:
            result["error_message"] = f"Timeout after {monitor.timeout}s"
            result["response_time"] = monitor.timeout * 1000
        except httpx.ConnectError as e:
            result["error_message"] = f"Connection error: {str(e)[:200]}"
        except Exception as e:
            result["error_message"] = f"Error: {str(e)[:200]}"
        return result

    @staticmethod
    async def check_keyword(monitor: Monitor) -> dict:
        result = await MonitoringEngine.check_http(monitor)
        if result["status"] == MonitorStatus.UP.value and monitor.keyword:
            body = result.get("response_body_snippet", "") or ""
            found = monitor.keyword.lower() in body.lower()
            if monitor.keyword_should_exist and not found:
                result["status"] = MonitorStatus.DOWN.value
                result["error_message"] = f"Keyword '{monitor.keyword}' not found"
            elif not monitor.keyword_should_exist and found:
                result["status"] = MonitorStatus.DOWN.value
                result["error_message"] = f"Keyword '{monitor.keyword}' found (should not exist)"
        return result

    @staticmethod
    async def check_ping(monitor: Monitor) -> dict:
        result = {"status": MonitorStatus.DOWN.value, "response_time": None, "error_message": None, "ip_address": None}
        try:
            from urllib.parse import urlparse
            parsed = urlparse(monitor.url if "://" in monitor.url else f"http://{monitor.url}")
            host = parsed.hostname or monitor.url
            try:
                result["ip_address"] = socket.gethostbyname(host)
            except socket.gaierror:
                result["error_message"] = f"Cannot resolve: {host}"
                return result
            param = "-n" if platform.system().lower() == "windows" else "-c"
            timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
            start = time.time()
            process = await asyncio.create_subprocess_exec(
                "ping", param, "1", timeout_param, str(min(monitor.timeout, 10)), host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=monitor.timeout)
            elapsed = (time.time() - start) * 1000
            if process.returncode == 0:
                result["status"] = MonitorStatus.UP.value
                result["response_time"] = round(elapsed, 2)
                m = re.search(r'time[=<](\d+\.?\d*)', stdout.decode())
                if m:
                    result["response_time"] = float(m.group(1))
            else:
                result["error_message"] = "Host unreachable"
        except asyncio.TimeoutError:
            result["error_message"] = f"Ping timeout ({monitor.timeout}s)"
        except Exception as e:
            result["error_message"] = f"Ping error: {str(e)[:200]}"
        return result

    @staticmethod
    async def check_port(monitor: Monitor) -> dict:
        result = {"status": MonitorStatus.DOWN.value, "response_time": None, "error_message": None, "ip_address": None}
        try:
            from urllib.parse import urlparse
            parsed = urlparse(monitor.url if "://" in monitor.url else f"http://{monitor.url}")
            host = parsed.hostname or monitor.url
            port = monitor.port or parsed.port or 80
            try:
                result["ip_address"] = socket.gethostbyname(host)
            except socket.gaierror:
                result["error_message"] = f"Cannot resolve: {host}"
                return result
            start = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=monitor.timeout
            )
            elapsed = (time.time() - start) * 1000
            result["status"] = MonitorStatus.UP.value
            result["response_time"] = round(elapsed, 2)
            writer.close()
            await writer.wait_closed()
        except asyncio.TimeoutError:
            result["error_message"] = f"Port timeout ({monitor.timeout}s)"
        except ConnectionRefusedError:
            result["error_message"] = f"Connection refused on port {monitor.port}"
        except Exception as e:
            result["error_message"] = f"Port error: {str(e)[:200]}"
        return result

    @staticmethod
    async def perform_check(monitor: Monitor) -> dict:
        methods = {
            MonitorType.HTTP.value: MonitoringEngine.check_http,
            MonitorType.HTTPS.value: MonitoringEngine.check_http,
            MonitorType.PING.value: MonitoringEngine.check_ping,
            MonitorType.PORT.value: MonitoringEngine.check_port,
            MonitorType.KEYWORD.value: MonitoringEngine.check_keyword,
        }
        method = methods.get(monitor.monitor_type, MonitoringEngine.check_http)
        return await method(monitor)


# =============================================================================
# SECTION 10: ALERTING ENGINE
# =============================================================================

class AlertingEngine:
    @staticmethod
    async def send_webhook(url: str, payload: dict):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json=payload)
        except Exception as e:
            logger.error(f"Webhook failed: {e}")

    @staticmethod
    async def send_discord(url: str, name: str, status: str, details: str):
        payload = {"embeds": [{"title": f"⚡ {name}", "description": details,
                               "color": 0x00FF88 if status == "up" else 0xFF0000,
                               "timestamp": datetime.utcnow().isoformat()}]}
        await AlertingEngine.send_webhook(url, payload)

    @staticmethod
    async def send_slack(url: str, name: str, status: str, details: str):
        emoji = "✅" if status == "up" else "🔴"
        await AlertingEngine.send_webhook(url, {"text": f"{emoji} *{name}*: {details}"})

    @staticmethod
    async def dispatch(user: User, monitor: Monitor, status: str, details: str):
        tasks = []
        if user.webhook_url:
            tasks.append(AlertingEngine.send_webhook(user.webhook_url, {
                "monitor": monitor.name, "url": monitor.url,
                "status": status, "details": details,
                "timestamp": datetime.utcnow().isoformat(),
            }))
        if user.discord_webhook:
            tasks.append(AlertingEngine.send_discord(user.discord_webhook, monitor.name, status, details))
        if user.slack_webhook:
            tasks.append(AlertingEngine.send_slack(user.slack_webhook, monitor.name, status, details))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# =============================================================================
# SECTION 11: DAILY STATS CALCULATOR
# =============================================================================

def calculate_daily_stats(db: Session, monitor_id: int, target_date=None):
    if target_date is None:
        target_date = datetime.utcnow().date()
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date, datetime.max.time())
    logs = db.query(MonitorLog).filter(
        MonitorLog.monitor_id == monitor_id,
        MonitorLog.created_at >= start_dt,
        MonitorLog.created_at <= end_dt,
    ).all()
    if not logs:
        return
    total = len(logs)
    up_count = sum(1 for l in logs if l.status == MonitorStatus.UP.value)
    rts = [l.response_time for l in logs if l.response_time is not None]
    uptime_pct = (up_count / total * 100) if total > 0 else 100.0
    stats = db.query(DailyStats).filter(
        DailyStats.monitor_id == monitor_id, DailyStats.date == target_date
    ).first()
    if stats:
        stats.total_checks = total
        stats.up_checks = up_count
        stats.down_checks = total - up_count
        stats.uptime_percentage = round(uptime_pct, 4)
        stats.avg_response_time = round(sum(rts) / len(rts), 2) if rts else None
        stats.min_response_time = round(min(rts), 2) if rts else None
        stats.max_response_time = round(max(rts), 2) if rts else None
    else:
        stats = DailyStats(
            monitor_id=monitor_id, date=target_date,
            total_checks=total, up_checks=up_count, down_checks=total - up_count,
            uptime_percentage=round(uptime_pct, 4),
            avg_response_time=round(sum(rts) / len(rts), 2) if rts else None,
            min_response_time=round(min(rts), 2) if rts else None,
            max_response_time=round(max(rts), 2) if rts else None,
        )
        db.add(stats)
    db.commit()


# =============================================================================
# SECTION 12: BACKGROUND MONITOR RUNNER
# =============================================================================

async def run_single_check(monitor_id: int):
    db = SessionLocal()
    try:
        monitor = db.query(Monitor).options(joinedload(Monitor.owner)).filter(Monitor.id == monitor_id).first()
        if not monitor or not monitor.is_active:
            return
        logger.info(f"🔍 Checking: {monitor.name} ({monitor.monitor_type}) -> {monitor.url}")
        result = await MonitoringEngine.perform_check(monitor)

        log = MonitorLog(
            monitor_id=monitor.id, status=result["status"],
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

        if monitor.total_checks > 0:
            monitor.uptime_percentage = round((monitor.total_up / monitor.total_checks) * 100, 4)

        # Incident & alert logic
        if previous_status != result["status"]:
            monitor.last_status_change = datetime.utcnow()
            if result["status"] == MonitorStatus.DOWN.value:
                if monitor.consecutive_failures >= monitor.alert_threshold:
                    db.add(Incident(monitor_id=monitor.id, cause=result.get("error_message", "Unknown")))
                    if monitor.alert_on_down and monitor.owner:
                        details = f"🔴 {monitor.name} is DOWN. URL: {monitor.url}. Error: {result.get('error_message', 'N/A')}"
                        await AlertingEngine.dispatch(monitor.owner, monitor, "down", details)
            elif result["status"] == MonitorStatus.UP.value and previous_status == MonitorStatus.DOWN.value:
                open_inc = db.query(Incident).filter(
                    Incident.monitor_id == monitor.id, Incident.is_resolved == False
                ).first()
                if open_inc:
                    open_inc.is_resolved = True
                    open_inc.resolved_at = datetime.utcnow()
                    open_inc.duration_seconds = int((datetime.utcnow() - open_inc.started_at).total_seconds())
                if monitor.alert_on_recovery and monitor.owner:
                    details = f"✅ {monitor.name} is BACK UP. Response: {result.get('response_time', 'N/A')}ms"
                    await AlertingEngine.dispatch(monitor.owner, monitor, "up", details)

        db.commit()
        calculate_daily_stats(db, monitor.id)
        cache_delete(f"user_monitors:{monitor.user_id}")

        emoji = "✅" if result["status"] == "up" else "🔴"
        logger.info(f"{emoji} {monitor.name}: {result['status'].upper()} ({result.get('response_time', '-')}ms)")
    except Exception as e:
        logger.error(f"❌ Check error for monitor {monitor_id}: {e}")
        db.rollback()
    finally:
        db.close()


async def run_all_monitors():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        monitors = db.query(Monitor).filter(
            Monitor.is_active == True, Monitor.status != MonitorStatus.PAUSED.value
        ).all()
        tasks = []
        for m in monitors:
            if m.last_check_at is None:
                tasks.append(run_single_check(m.id))
            elif now >= m.last_check_at + timedelta(seconds=m.check_interval):
                tasks.append(run_single_check(m.id))
        if tasks:
            logger.info(f"🚀 Running {len(tasks)} monitor checks...")
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"❌ Monitor runner error: {e}")
    finally:
        db.close()


# =============================================================================
# SECTION 13: APP LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown handler."""
    logger.info("🚀 NeonWatch starting up...")

    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("📦 Database tables created/verified")

    # Init singleton config + default admin
    db = SessionLocal()
    try:
        config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
        if not config:
            db.add(SiteConfig(id=1))
            db.commit()
            logger.info("⚙️ Default SiteConfig created")

        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin", email="admin@neonwatch.io",
                password_hash=hash_password("admin123456"),
                full_name="Super Administrator",
                role=UserRole.SUPERADMIN.value,
                plan=UserPlan.ENTERPRISE.value,
                is_active=True, email_verified=True, max_monitors=9999,
            )
            db.add(admin)
            db.commit()
            logger.info("👑 Default superadmin: admin / admin123456")
    finally:
        db.close()

    # Background monitor loop
    async def _loop():
        while True:
            try:
                await run_all_monitors()
            except Exception as e:
                logger.error(f"Loop error: {e}")
            await asyncio.sleep(60)

    task = asyncio.create_task(_loop())
    logger.info("🔄 Background monitor loop started")
    logger.info("✨ NeonWatch is LIVE!")

    yield

    task.cancel()
    logger.info("👋 NeonWatch shutdown")


# =============================================================================
# SECTION 14: FASTAPI APP
# =============================================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
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
# SECTION 15: MIDDLEWARE
# =============================================================================

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 2)
    response.headers["X-Response-Time"] = f"{elapsed}ms"
    response.headers["X-Powered-By"] = "NeonWatch/2.0"
    return response


# =============================================================================
# SECTION 16: AUTH ROUTES
# =============================================================================

@app.post("/api/auth/register", tags=["Auth"])
async def register(data: UserRegisterSchema, db: Session = Depends(get_db)):
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if config and not config.signup_enabled:
        raise HTTPException(400, "Registration disabled")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username taken")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")
    max_mon = config.max_free_monitors if config else 10
    user = User(
        username=data.username, email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name, max_monitors=max_mon,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_jwt_token({"user_id": user.id, "role": user.role})
    return {"success": True, "token": token, "user": user.to_dict()}


@app.post("/api/auth/login", tags=["Auth"])
async def login(data: UserLoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        or_(User.username == data.login, User.email == data.login)
    ).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if user.is_banned:
        raise HTTPException(403, f"Banned: {user.ban_reason or 'Contact admin'}")
    if not user.is_active:
        raise HTTPException(403, "Account deactivated")
    user.last_login = datetime.utcnow()
    db.commit()
    token = create_jwt_token({"user_id": user.id, "role": user.role})
    return {"success": True, "token": token, "user": user.to_dict()}


@app.get("/api/auth/me", tags=["Auth"])
async def get_me(user: User = Depends(get_current_user)):
    return {"success": True, "user": user.to_dict()}


@app.put("/api/auth/me", tags=["Auth"])
async def update_me(data: UserUpdateSchema, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    update_data = data.dict(exclude_unset=True)
    if "timezone" in update_data:
        user.timezone_str = update_data.pop("timezone")
    for field, value in update_data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return {"success": True, "user": user.to_dict()}


# =============================================================================
# SECTION 17: MONITOR CRUD ROUTES
# =============================================================================

@app.get("/api/monitors", tags=["Monitors"])
async def list_monitors(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = None, type_filter: Optional[str] = None,
    search: Optional[str] = None,
):
    query = db.query(Monitor).filter(Monitor.user_id == user.id)
    if status_filter:
        query = query.filter(Monitor.status == status_filter)
    if type_filter:
        query = query.filter(Monitor.monitor_type == type_filter)
    if search:
        query = query.filter(or_(Monitor.name.ilike(f"%{search}%"), Monitor.url.ilike(f"%{search}%")))
    total = query.count()
    monitors = query.order_by(desc(Monitor.created_at)).offset((page - 1) * limit).limit(limit).all()
    return {"success": True, "monitors": [m.to_dict() for m in monitors], "total": total, "page": page}


@app.post("/api/monitors", tags=["Monitors"])
async def create_monitor(
    data: MonitorCreateSchema, user: User = Depends(get_current_user),
    db: Session = Depends(get_db), background_tasks: BackgroundTasks = None,
):
    count = db.query(Monitor).filter(Monitor.user_id == user.id).count()
    if count >= user.max_monitors:
        raise HTTPException(400, f"Monitor limit reached ({user.max_monitors})")
    monitor = Monitor(
        user_id=user.id, name=data.name, url=data.url,
        monitor_type=data.monitor_type, check_interval=data.check_interval,
        timeout=data.timeout, http_method=data.http_method,
        http_headers=data.http_headers, http_body=data.http_body,
        expected_status_code=data.expected_status_code,
        follow_redirects=data.follow_redirects, verify_ssl=data.verify_ssl,
        keyword=data.keyword, keyword_should_exist=data.keyword_should_exist,
        port=data.port, alert_on_down=data.alert_on_down,
        alert_on_recovery=data.alert_on_recovery, alert_threshold=data.alert_threshold,
        tags=json.dumps(data.tags) if data.tags else None, notes=data.notes,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    cache_delete(f"user_monitors:{user.id}")
    if background_tasks:
        background_tasks.add_task(asyncio.get_event_loop().run_until_complete, run_single_check(monitor.id))
    return {"success": True, "monitor": monitor.to_dict()}


@app.get("/api/monitors/{monitor_id}", tags=["Monitors"])
async def get_monitor(monitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")
    logs = db.query(MonitorLog).filter(MonitorLog.monitor_id == monitor.id).order_by(desc(MonitorLog.created_at)).limit(100).all()
    incidents = db.query(Incident).filter(Incident.monitor_id == monitor.id).order_by(desc(Incident.started_at)).limit(20).all()
    thirty_ago = datetime.utcnow().date() - timedelta(days=30)
    daily = db.query(DailyStats).filter(DailyStats.monitor_id == monitor.id, DailyStats.date >= thirty_ago).order_by(asc(DailyStats.date)).all()
    return {
        "success": True, "monitor": monitor.to_dict(),
        "logs": [l.to_dict() for l in logs],
        "incidents": [i.to_dict() for i in incidents],
        "daily_stats": [d.to_dict() for d in daily],
    }


@app.put("/api/monitors/{monitor_id}", tags=["Monitors"])
async def update_monitor(monitor_id: int, data: MonitorUpdateSchema, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")
    update_data = data.dict(exclude_unset=True)
    if "tags" in update_data:
        update_data["tags"] = json.dumps(update_data["tags"]) if update_data["tags"] else None
    for field, value in update_data.items():
        setattr(monitor, field, value)
    db.commit()
    db.refresh(monitor)
    cache_delete(f"user_monitors:{user.id}")
    return {"success": True, "monitor": monitor.to_dict()}


@app.delete("/api/monitors/{monitor_id}", tags=["Monitors"])
async def delete_monitor(monitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")
    db.delete(monitor)
    db.commit()
    cache_delete(f"user_monitors:{user.id}")
    return {"success": True, "message": "Monitor deleted"}


@app.post("/api/monitors/{monitor_id}/check", tags=["Monitors"])
async def trigger_check(monitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db), background_tasks: BackgroundTasks = None):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
    if not monitor:
        raise HTTPException(404, "Monitor not found")
    if background_tasks:
        background_tasks.add_task(asyncio.get_event_loop().run_until_complete, run_single_check(monitor.id))
    return {"success": True, "message": "Check triggered"}


@app.post("/api/monitors/{monitor_id}/pause", tags=["Monitors"])
async def pause_monitor(monitor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == user.id).first()
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
# SECTION 18: DASHBOARD ROUTE
# =============================================================================

@app.get("/api/dashboard", tags=["Dashboard"])
async def get_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    monitors = db.query(Monitor).filter(Monitor.user_id == user.id).all()
    total = len(monitors)
    up = sum(1 for m in monitors if m.status == MonitorStatus.UP.value)
    down = sum(1 for m in monitors if m.status == MonitorStatus.DOWN.value)
    paused = sum(1 for m in monitors if m.status == MonitorStatus.PAUSED.value)
    uptimes = [m.uptime_percentage for m in monitors if m.uptime_percentage is not None]
    avg_uptime = sum(uptimes) / len(uptimes) if uptimes else 100
    rts = [m.last_response_time for m in monitors if m.last_response_time]
    avg_rt = sum(rts) / len(rts) if rts else 0
    recent_incidents = db.query(Incident).join(Monitor).filter(
        Monitor.user_id == user.id
    ).order_by(desc(Incident.started_at)).limit(10).all()
    thirty_ago = datetime.utcnow().date() - timedelta(days=30)
    daily_agg = db.query(
        DailyStats.date,
        func.avg(DailyStats.uptime_percentage).label("avg_uptime"),
        func.avg(DailyStats.avg_response_time).label("avg_rt"),
    ).join(Monitor).filter(
        Monitor.user_id == user.id, DailyStats.date >= thirty_ago
    ).group_by(DailyStats.date).order_by(asc(DailyStats.date)).all()
    return {
        "success": True,
        "overview": {
            "total_monitors": total, "up": up, "down": down, "paused": paused,
            "pending": total - up - down - paused,
            "avg_uptime": round(avg_uptime, 2), "avg_response_time": round(avg_rt, 2),
        },
        "monitors": [m.to_dict() for m in monitors],
        "recent_incidents": [i.to_dict() for i in recent_incidents],
        "daily_chart": [
            {"date": d.date.isoformat(),
             "uptime": round(float(d.avg_uptime), 2) if d.avg_uptime else 100,
             "response_time": round(float(d.avg_rt), 2) if d.avg_rt else 0}
            for d in daily_agg
        ],
    }


# =============================================================================
# SECTION 19: SITE CONFIG ROUTES
# =============================================================================

@app.get("/api/site-config", tags=["Site Config"])
async def get_site_config(db: Session = Depends(get_db)):
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if not config:
        config = SiteConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return {"success": True, "config": config.to_dict()}


@app.put("/api/site-config", tags=["Site Config"])
async def update_site_config(data: SiteConfigUpdateSchema, admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    config = db.query(SiteConfig).filter(SiteConfig.id == 1).first()
    if not config:
        config = SiteConfig(id=1)
        db.add(config)
    for field, value in data.dict(exclude_unset=True).items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    db.add(AuditLog(user_id=admin.id, action="update_site_config", target_type="site_config", target_id=1,
                    details=json.dumps(data.dict(exclude_unset=True))))
    db.commit()
    cache_delete("site_config")
    return {"success": True, "config": config.to_dict(), "message": "Config updated!"}


# =============================================================================
# SECTION 20: ADMIN ROUTES
# =============================================================================

@app.get("/api/admin/users", tags=["Admin"])
async def admin_list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db),
                           page: int = Query(1, ge=1), limit: int = Query(50), search: Optional[str] = None):
    query = db.query(User)
    if search:
        query = query.filter(or_(User.username.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
    total = query.count()
    users = query.order_by(desc(User.created_at)).offset((page - 1) * limit).limit(limit).all()
    return {"success": True, "users": [u.to_dict() for u in users], "total": total, "page": page}


@app.get("/api/admin/users/{user_id}", tags=["Admin"])
async def admin_get_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).options(selectinload(User.monitors)).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return {"success": True, "user": user.to_dict(), "monitors": [m.to_dict() for m in user.monitors]}


@app.post("/api/admin/users/{user_id}/ban", tags=["Admin"])
async def admin_ban_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role == UserRole.SUPERADMIN.value:
        raise HTTPException(403, "Cannot ban superadmin")
    user.is_banned = True
    user.ban_reason = "Violated terms of service"
    db.commit()
    db.add(AuditLog(user_id=admin.id, action="ban_user", target_type="user", target_id=user_id))
    db.commit()
    return {"success": True, "message": f"{user.username} banned"}


@app.post("/api/admin/users/{user_id}/unban", tags=["Admin"])
async def admin_unban_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = False
    user.ban_reason = None
    db.commit()
    return {"success": True, "message": f"{user.username} unbanned"}


@app.put("/api/admin/users/{user_id}/role", tags=["Admin"])
async def admin_change_role(user_id: int, role: str = Body(..., embed=True),
                            admin: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if role not in [r.value for r in UserRole]:
        raise HTTPException(400, f"Invalid role")
    user.role = role
    db.commit()
    return {"success": True, "message": f"Role updated to {role}"}


@app.get("/api/admin/stats", tags=["Admin"])
async def admin_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True, User.is_banned == False).count()
    total_monitors = db.query(Monitor).count()
    active_monitors = db.query(Monitor).filter(Monitor.is_active == True).count()
    total_checks = db.query(func.sum(Monitor.total_checks)).scalar() or 0
    total_incidents = db.query(Incident).count()
    open_incidents = db.query(Incident).filter(Incident.is_resolved == False).count()
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_users_week = db.query(User).filter(User.created_at >= week_ago).count()
    type_dist = db.query(Monitor.monitor_type, func.count(Monitor.id)).group_by(Monitor.monitor_type).all()
    plan_dist = db.query(User.plan, func.count(User.id)).group_by(User.plan).all()
    return {
        "success": True, "stats": {
            "total_users": total_users, "active_users": active_users,
            "new_users_week": new_users_week,
            "total_monitors": total_monitors, "active_monitors": active_monitors,
            "total_checks": total_checks,
            "total_incidents": total_incidents, "open_incidents": open_incidents,
            "monitor_types": {t: c for t, c in type_dist},
            "plan_distribution": {p: c for p, c in plan_dist},
        },
    }


@app.get("/api/admin/audit-logs", tags=["Admin"])
async def admin_audit_logs(admin: User = Depends(require_admin), db: Session = Depends(get_db),
                           page: int = Query(1, ge=1), limit: int = Query(50)):
    total = db.query(AuditLog).count()
    logs = db.query(AuditLog).order_by(desc(AuditLog.created_at)).offset((page - 1) * limit).limit(limit).all()
    return {"success": True, "logs": [l.to_dict() for l in logs], "total": total}


@app.get("/api/admin/monitors", tags=["Admin"])
async def admin_all_monitors(admin: User = Depends(require_admin), db: Session = Depends(get_db),
                             page: int = Query(1, ge=1), limit: int = Query(50)):
    total = db.query(Monitor).count()
    monitors = db.query(Monitor).options(joinedload(Monitor.owner)).order_by(desc(Monitor.created_at)).offset((page - 1) * limit).limit(limit).all()
    result = []
    for m in monitors:
        md = m.to_dict()
        md["owner_username"] = m.owner.username if m.owner else "?"
        result.append(md)
    return {"success": True, "monitors": result, "total": total}


# =============================================================================
# SECTION 21: ALERT CONTACTS & STATUS PAGES
# =============================================================================

@app.get("/api/alert-contacts", tags=["Alerts"])
async def list_contacts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contacts = db.query(AlertContact).filter(AlertContact.user_id == user.id).all()
    return {"success": True, "contacts": [c.to_dict() for c in contacts]}


@app.post("/api/alert-contacts", tags=["Alerts"])
async def create_contact(data: AlertContactSchema, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = AlertContact(user_id=user.id, name=data.name, alert_type=data.alert_type, value=data.value)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"success": True, "contact": c.to_dict()}


@app.delete("/api/alert-contacts/{cid}", tags=["Alerts"])
async def delete_contact(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(AlertContact).filter(AlertContact.id == cid, AlertContact.user_id == user.id).first()
    if not c:
        raise HTTPException(404, "Not found")
    db.delete(c)
    db.commit()
    return {"success": True}


@app.get("/api/status-pages", tags=["Status Pages"])
async def list_status_pages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pages = db.query(StatusPage).filter(StatusPage.user_id == user.id).all()
    return {"success": True, "pages": [p.to_dict() for p in pages]}


@app.post("/api/status-pages", tags=["Status Pages"])
async def create_status_page(data: StatusPageSchema, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.query(StatusPage).filter(StatusPage.slug == data.slug).first():
        raise HTTPException(400, "Slug taken")
    page = StatusPage(user_id=user.id, slug=data.slug, title=data.title, description=data.description,
                      monitor_ids=json.dumps(data.monitor_ids) if data.monitor_ids else None, is_public=data.is_public)
    db.add(page)
    db.commit()
    db.refresh(page)
    return {"success": True, "page": page.to_dict()}


@app.get("/api/status/{slug}", tags=["Status Pages"])
async def get_public_status(slug: str, db: Session = Depends(get_db)):
    page = db.query(StatusPage).filter(StatusPage.slug == slug, StatusPage.is_public == True).first()
    if not page:
        raise HTTPException(404, "Not found")
    mids = json.loads(page.monitor_ids) if page.monitor_ids else []
    monitors = db.query(Monitor).filter(Monitor.id.in_(mids)).all() if mids else []
    thirty_ago = datetime.utcnow().date() - timedelta(days=30)
    monitor_data = []
    for m in monitors:
        daily = db.query(DailyStats).filter(DailyStats.monitor_id == m.id, DailyStats.date >= thirty_ago).order_by(asc(DailyStats.date)).all()
        monitor_data.append({
            "name": m.name, "status": m.status,
            "uptime_percentage": m.uptime_percentage,
            "last_response_time": m.last_response_time,
            "daily": [d.to_dict() for d in daily],
        })
    uptimes = [m.uptime_percentage for m in monitors if m.uptime_percentage is not None]
    overall = sum(uptimes) / len(uptimes) if uptimes else 100
    return {"success": True, "page": page.to_dict(), "monitors": monitor_data, "overall_uptime": round(overall, 2)}


# =============================================================================
# SECTION 22: HEALTH CHECK
# =============================================================================

@app.get("/api/health", tags=["System"])
async def health():
    return {"status": "healthy", "version": settings.APP_VERSION, "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# SECTION 23: WEBSOCKET
# =============================================================================

ws_clients: Dict[int, List[WebSocket]] = {}


@app.websocket("/ws/{user_id}")
async def ws_endpoint(websocket: WebSocket, user_id: int):
    await websocket.accept()
    ws_clients.setdefault(user_id, []).append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_clients[user_id].remove(websocket)
        if not ws_clients[user_id]:
            del ws_clients[user_id]


# =============================================================================
# SECTION 24: FULL FRONTEND HTML
# =============================================================================

FRONTEND_HTML = r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NeonWatch - God Level Uptime Monitoring</title>
<script src="https://cdn.tailwindcss.com"></script>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script>
tailwind.config={darkMode:'class',theme:{extend:{colors:{'neon-pink':'#F806CC','neon-purple':'#A855F7','deep-purple':'#2E0249','darker-purple':'#1A0130','mid-purple':'#570A57','neon-green':'#00FF88','neon-red':'#FF1744','neon-yellow':'#FFE500'},boxShadow:{'neon':'0 0 20px rgba(248,6,204,0.5),0 0 60px rgba(248,6,204,0.2)','neon-lg':'0 0 30px rgba(248,6,204,0.6),0 0 80px rgba(248,6,204,0.3)'},animation:{'glow-pulse':'glowPulse 2s ease-in-out infinite alternate','slide-up':'slideUp 0.5s ease-out','fade-in':'fadeIn 0.5s ease-out'},keyframes:{glowPulse:{'0%':{filter:'drop-shadow(0 0 10px #F806CC) drop-shadow(0 0 30px #A855F7)'},'100%':{filter:'drop-shadow(0 0 20px #F806CC) drop-shadow(0 0 50px #A855F7) drop-shadow(0 0 70px #F806CC)'}},slideUp:{'0%':{opacity:'0',transform:'translateY(30px)'},'100%':{opacity:'1',transform:'translateY(0)'}},fadeIn:{'0%':{opacity:'0'},'100%':{opacity:'1'}}}}}}
</script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#0D0015;color:#e2e8f0;min-height:100vh;overflow-x:hidden}
#bg-video-container{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-2;overflow:hidden}
#bg-video-container video{width:100%;height:100%;object-fit:cover}
#bg-overlay{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;background:linear-gradient(135deg,rgba(13,0,21,0.88),rgba(46,2,73,0.85),rgba(87,10,87,0.82),rgba(13,0,21,0.90));animation:gradientShift 15s ease infinite;background-size:400% 400%}
@keyframes gradientShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.glass-card{background:rgba(13,0,21,0.6);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(248,6,204,0.15);border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.4),inset 0 1px 0 rgba(255,255,255,0.05);transition:border-color 0.3s,box-shadow 0.3s}
.glass-card:hover{border-color:rgba(248,6,204,0.35)}
.logo-glow{animation:logoGlow 2s ease-in-out infinite alternate}
@keyframes logoGlow{0%{text-shadow:0 0 10px #F806CC,0 0 20px #F806CC,0 0 40px #A855F7;filter:brightness(1)}100%{text-shadow:0 0 20px #F806CC,0 0 40px #F806CC,0 0 60px #A855F7,0 0 80px #F806CC;filter:brightness(1.2)}}
.neon-btn{background:linear-gradient(135deg,#F806CC,#A855F7);border:none;color:#fff;font-weight:600;padding:10px 24px;border-radius:12px;cursor:pointer;transition:all 0.3s;box-shadow:0 0 15px rgba(248,6,204,0.3)}
.neon-btn:hover{box-shadow:0 0 25px rgba(248,6,204,0.6),0 0 50px rgba(168,85,247,0.3);transform:translateY(-2px)}
.neon-btn:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.neon-btn-outline{background:transparent;border:2px solid #F806CC;color:#F806CC;padding:10px 24px;border-radius:12px;cursor:pointer;transition:all 0.3s}
.neon-btn-outline:hover{background:rgba(248,6,204,0.15);box-shadow:0 0 20px rgba(248,6,204,0.3)}
.neon-input{background:rgba(13,0,21,0.6);border:1px solid rgba(248,6,204,0.2);color:#e2e8f0;padding:12px 16px;border-radius:12px;outline:none;transition:all 0.3s;width:100%;font-size:14px}
.neon-input:focus{border-color:#F806CC;box-shadow:0 0 15px rgba(248,6,204,0.2)}
.neon-input::placeholder{color:rgba(255,255,255,0.3)}
.neon-select{background:rgba(13,0,21,0.6);border:1px solid rgba(248,6,204,0.2);color:#e2e8f0;padding:12px 16px;border-radius:12px;outline:none;appearance:none;cursor:pointer;width:100%}
.neon-select:focus{border-color:#F806CC;box-shadow:0 0 15px rgba(248,6,204,0.2)}
.status-dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.status-up{background:#00FF88;box-shadow:0 0 10px #00FF88,0 0 20px rgba(0,255,136,0.3);animation:statusPulse 2s ease-in-out infinite}
.status-down{background:#FF1744;box-shadow:0 0 10px #FF1744,0 0 20px rgba(255,23,68,0.3);animation:statusPulse 1s ease-in-out infinite}
.status-pending{background:#FFE500;box-shadow:0 0 10px #FFE500}
.status-paused{background:#888;box-shadow:0 0 5px #888}
@keyframes statusPulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.7;transform:scale(1.2)}}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:#0D0015}::-webkit-scrollbar-thumb{background:linear-gradient(#F806CC,#A855F7);border-radius:3px}
.music-toggle{position:fixed;bottom:20px;right:20px;z-index:1000;background:rgba(13,0,21,0.8);border:1px solid rgba(248,6,204,0.3);border-radius:50%;width:50px;height:50px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all 0.3s;backdrop-filter:blur(10px)}
.music-toggle:hover{border-color:#F806CC;box-shadow:0 0 20px rgba(248,6,204,0.4)}
.monitor-card{position:relative;overflow:hidden}
.monitor-card::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%}
.monitor-card.sc-up::before{background:#00FF88;box-shadow:0 0 10px #00FF88}
.monitor-card.sc-down::before{background:#FF1744;box-shadow:0 0 10px #FF1744}
.monitor-card.sc-pending::before{background:#FFE500}
.monitor-card.sc-paused::before{background:#888}
.sidebar{background:rgba(13,0,21,0.85);backdrop-filter:blur(20px);border-right:1px solid rgba(248,6,204,0.1)}
.sidebar-link{display:flex;align-items:center;gap:12px;padding:12px 20px;border-radius:10px;color:rgba(255,255,255,0.6);transition:all 0.3s;cursor:pointer}
.sidebar-link:hover,.sidebar-link.active{background:rgba(248,6,204,0.1);color:#F806CC;border-left:3px solid #F806CC}
.spinner{border:3px solid rgba(248,6,204,0.2);border-top:3px solid #F806CC;border-radius:50%;width:40px;height:40px;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.toast{position:fixed;top:20px;right:20px;z-index:9999;padding:16px 24px;border-radius:12px;backdrop-filter:blur(20px);animation:slideInR 0.5s ease-out;max-width:400px}
.toast-success{background:rgba(0,255,136,0.15);border:1px solid rgba(0,255,136,0.3);color:#00FF88}
.toast-error{background:rgba(255,23,68,0.15);border:1px solid rgba(255,23,68,0.3);color:#FF1744}
@keyframes slideInR{0%{transform:translateX(100%);opacity:0}100%{transform:translateX(0);opacity:1}}
.toggle-switch{position:relative;width:48px;height:24px;background:rgba(255,255,255,0.1);border-radius:24px;cursor:pointer;transition:all 0.3s}
.toggle-switch.active{background:linear-gradient(135deg,#F806CC,#A855F7)}
.toggle-switch::after{content:'';position:absolute;top:2px;left:2px;width:20px;height:20px;background:#fff;border-radius:50%;transition:all 0.3s}
.toggle-switch.active::after{left:26px}
.particle{position:fixed;background:radial-gradient(circle,#F806CC,transparent);border-radius:50%;pointer-events:none;opacity:0.12;animation:floatP 20s linear infinite}
@keyframes floatP{0%{transform:translateY(100vh) rotate(0);opacity:0}10%{opacity:0.12}90%{opacity:0.12}100%{transform:translateY(-100vh) rotate(720deg);opacity:0}}
.uptime-bar{display:flex;gap:2px;height:30px;align-items:flex-end}
.uptime-bar-seg{flex:1;min-width:3px;border-radius:2px;transition:all 0.3s;cursor:pointer}
.uptime-bar-seg:hover{opacity:0.8;transform:scaleY(1.1)}
</style>
</head>
<body>
<div id="root"></div>
<div id="bg-video-container"></div>
<div id="bg-overlay"></div>
<audio id="bg-audio" loop preload="none"></audio>
<script type="text/babel">
const{useState,useEffect,useCallback,useRef}=React;
const API=window.location.origin+'/api';
const api={
  async req(m,p,b=null,t=null){
    const h={'Content-Type':'application/json'};
    if(t)h['Authorization']=`Bearer ${t}`;
    const o={method:m,headers:h};
    if(b)o.body=JSON.stringify(b);
    const r=await fetch(API+p,o);
    const d=await r.json();
    if(!r.ok)throw new Error(d.detail||'Request failed');
    return d;
  },
  get(p,t){return this.req('GET',p,null,t)},
  post(p,b,t){return this.req('POST',p,b,t)},
  put(p,b,t){return this.req('PUT',p,b,t)},
  del(p,t){return this.req('DELETE',p,null,t)}
};
function Toast({message,type,onClose}){
  useEffect(()=>{const t=setTimeout(onClose,4000);return()=>clearTimeout(t)},[]);
  return <div className={`toast toast-${type}`}><span className="font-medium">{type==='success'?'✅':'❌'} {message}</span></div>;
}
function Particles(){
  return <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
    {[...Array(12)].map((_,i)=><div key={i} className="particle" style={{width:`${Math.random()*6+2}px`,height:`${Math.random()*6+2}px`,left:`${Math.random()*100}%`,animationDelay:`${Math.random()*20}s`,animationDuration:`${Math.random()*15+15}s`}}/>)}
  </div>;
}
function Spinner({size='md'}){const s={sm:'w-5 h-5',md:'w-10 h-10',lg:'w-16 h-16'};return <div className={`spinner ${s[size]}`}/>;}
function Logo({config,size='md'}){
  const s={sm:'text-xl',md:'text-3xl',lg:'text-5xl'};
  if(config?.logo_url)return <img src={config.logo_url} alt="Logo" className="h-10 animate-glow-pulse"/>;
  return <div className={`font-black ${s[size]} logo-glow flex items-center gap-2`}><span className="text-neon-pink">⚡</span><span className="bg-gradient-to-r from-neon-pink via-neon-purple to-purple-400 bg-clip-text text-transparent">{config?.site_name||'NeonWatch'}</span></div>;
}
function StatusDot({status}){const c={up:'status-up',down:'status-down',pending:'status-pending',paused:'status-paused'};return <span className={`status-dot ${c[status]||'status-pending'}`}/>;}
function MusicToggle({url}){
  const[playing,setPlaying]=useState(false);
  const toggle=()=>{const a=document.getElementById('bg-audio');if(!a||!url)return;if(playing)a.pause();else{a.src=url;a.play().catch(()=>{});}setPlaying(!playing);};
  if(!url)return null;
  return <button onClick={toggle} className="music-toggle" title={playing?'Pause':'Play'}><span className="text-neon-pink text-xl">{playing?'🔊':'🔇'}</span></button>;
}
function StatCard({icon,label,value,subtext}){
  return <div className="glass-card p-5 animate-slide-up"><div className="flex items-center justify-between mb-2"><span className="text-2xl">{icon}</span><span className="text-xs px-2 py-1 rounded-full bg-neon-pink/10 text-neon-pink">{subtext}</span></div><p className="text-3xl font-bold bg-gradient-to-r from-neon-pink to-neon-purple bg-clip-text text-transparent">{value}</p><p className="text-sm text-white/50 mt-1">{label}</p></div>;
}
function MonitorCard({monitor:m,onClick}){
  return <div onClick={()=>onClick(m)} className={`glass-card monitor-card sc-${m.status} p-5 cursor-pointer hover:scale-[1.02] transition-all duration-300 animate-fade-in`}>
    <div className="flex items-center justify-between mb-3"><div className="flex items-center gap-3"><StatusDot status={m.status}/><h3 className="font-semibold text-white truncate max-w-[200px]">{m.name}</h3></div><span className="text-xs px-2 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase font-mono">{m.monitor_type}</span></div>
    <p className="text-xs text-white/40 truncate mb-3 font-mono">{m.url}</p>
    <div className="grid grid-cols-3 gap-2 text-center"><div><p className="text-lg font-bold text-neon-green">{m.uptime_percentage?.toFixed(2)||'0'}%</p><p className="text-xs text-white/40">Uptime</p></div><div><p className="text-lg font-bold text-neon-purple">{m.last_response_time?.toFixed(0)||'-'}ms</p><p className="text-xs text-white/40">Response</p></div><div><p className="text-lg font-bold text-white/80">{m.total_checks||0}</p><p className="text-xs text-white/40">Checks</p></div></div>
  </div>;
}
function CreateModal({onClose,onCreated,token}){
  const[f,sF]=useState({name:'',url:'',monitor_type:'http',check_interval:300,timeout:30,expected_status_code:200,keyword:'',port:'',alert_on_down:true,alert_on_recovery:true,alert_threshold:1});
  const[loading,setL]=useState(false);const[error,setE]=useState('');
  const submit=async(e)=>{e.preventDefault();setL(true);setE('');try{const p={...f};if(p.port)p.port=parseInt(p.port);else delete p.port;if(!p.keyword)delete p.keyword;const d=await api.post('/monitors',p,token);onCreated(d.monitor);onClose();}catch(err){setE(err.message);}setL(false);};
  return <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}><div className="glass-card p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto animate-slide-up" onClick={e=>e.stopPropagation()}>
    <div className="flex justify-between items-center mb-6"><h2 className="text-2xl font-bold text-neon-pink">➕ New Monitor</h2><button onClick={onClose} className="text-white/50 hover:text-white text-2xl">&times;</button></div>
    <form onSubmit={submit} className="space-y-4">
      {error&&<div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">{error}</div>}
      <div><label className="text-sm text-white/60 mb-1 block">Name</label><input className="neon-input" value={f.name} onChange={e=>sF({...f,name:e.target.value})} placeholder="My Website" required/></div>
      <div><label className="text-sm text-white/60 mb-1 block">URL / Host</label><input className="neon-input" value={f.url} onChange={e=>sF({...f,url:e.target.value})} placeholder="https://example.com" required/></div>
      <div className="grid grid-cols-2 gap-4">
        <div><label className="text-sm text-white/60 mb-1 block">Type</label><select className="neon-select" value={f.monitor_type} onChange={e=>sF({...f,monitor_type:e.target.value})}><option value="http">HTTP(S)</option><option value="ping">Ping</option><option value="port">Port</option><option value="keyword">Keyword</option></select></div>
        <div><label className="text-sm text-white/60 mb-1 block">Interval</label><select className="neon-select" value={f.check_interval} onChange={e=>sF({...f,check_interval:parseInt(e.target.value)})}><option value="60">1 min</option><option value="180">3 min</option><option value="300">5 min</option><option value="600">10 min</option><option value="1800">30 min</option></select></div>
      </div>
      {f.monitor_type==='keyword'&&<div><label className="text-sm text-white/60 mb-1 block">Keyword</label><input className="neon-input" value={f.keyword} onChange={e=>sF({...f,keyword:e.target.value})} placeholder="Expected keyword"/></div>}
      {f.monitor_type==='port'&&<div><label className="text-sm text-white/60 mb-1 block">Port</label><input type="number" className="neon-input" value={f.port} onChange={e=>sF({...f,port:e.target.value})} placeholder="443"/></div>}
      <button type="submit" className="neon-btn w-full py-3" disabled={loading}>{loading?'Creating...':'🚀 Create Monitor'}</button>
    </form>
  </div></div>;
}
function MonitorDetail({monitorId,token,onBack}){
  const[data,setData]=useState(null);const[loading,setL]=useState(true);
  useEffect(()=>{api.get(`/monitors/${monitorId}`,token).then(d=>{setData(d);setL(false)}).catch(()=>setL(false))},[monitorId]);
  const triggerCheck=async()=>{try{await api.post(`/monitors/${monitorId}/check`,{},token);setTimeout(()=>api.get(`/monitors/${monitorId}`,token).then(setData),3000)}catch(e){}};
  if(loading)return <div className="flex justify-center py-20"><Spinner/></div>;
  if(!data)return <div className="text-center py-20 text-white/50">Not found</div>;
  const m=data.monitor,logs=data.logs||[];
  return <div className="space-y-6 animate-fade-in">
    <div className="flex items-center gap-4 flex-wrap"><button onClick={onBack} className="neon-btn-outline px-4 py-2">← Back</button><StatusDot status={m.status}/><h1 className="text-2xl font-bold">{m.name}</h1><span className="text-xs px-3 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase">{m.monitor_type}</span><button onClick={triggerCheck} className="neon-btn ml-auto">⚡ Check Now</button></div>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"><StatCard icon="📊" label="Uptime" value={`${m.uptime_percentage?.toFixed(2)||0}%`} subtext="overall"/><StatCard icon="⚡" label="Response" value={`${m.last_response_time?.toFixed(0)||'-'}ms`} subtext="last"/><StatCard icon="✅" label="Total Checks" value={m.total_checks||0} subtext="all time"/><StatCard icon="🔴" label="Failures" value={m.total_down||0} subtext="total"/></div>
    <div className="glass-card p-5"><h3 className="text-lg font-semibold text-neon-pink mb-2">URL</h3><p className="font-mono text-sm text-white/60 break-all">{m.url}</p></div>
    {data.daily_stats&&data.daily_stats.length>0&&<div className="glass-card p-5"><h3 className="text-lg font-semibold text-neon-pink mb-4">30-Day Uptime</h3><div className="uptime-bar">{data.daily_stats.map((d,i)=>{const u=d.uptime_percentage||100;const c=u>=99.5?'#00FF88':u>=95?'#FFE500':'#FF1744';return <div key={i} className="uptime-bar-seg" title={`${d.date}: ${u.toFixed(2)}%`} style={{height:`${Math.max(u*0.3,5)}px`,background:c}}/>;})}</div></div>}
    <div className="glass-card p-5"><h3 className="text-lg font-semibold text-neon-pink mb-4">Recent Logs</h3><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-white/50 border-b border-white/10"><th className="py-2 text-left">Status</th><th className="py-2 text-left">Response</th><th className="py-2 text-left">Code</th><th className="py-2 text-left">Error</th><th className="py-2 text-left">Time</th></tr></thead><tbody>{logs.slice(0,30).map(l=><tr key={l.id} className="border-b border-white/5 hover:bg-white/5"><td className="py-2"><StatusDot status={l.status}/></td><td className="py-2 text-neon-purple">{l.response_time?.toFixed(0)||'-'}ms</td><td className="py-2">{l.status_code||'-'}</td><td className="py-2 text-red-400 truncate max-w-[200px]">{l.error_message||'-'}</td><td className="py-2 text-white/40 font-mono text-xs">{new Date(l.created_at).toLocaleString()}</td></tr>)}</tbody></table></div></div>
  </div>;
}
function DashboardPage({token,user}){
  const[dash,setDash]=useState(null);const[loading,setL]=useState(true);const[showCreate,setSC]=useState(false);const[selected,setSel]=useState(null);
  const load=async()=>{try{const d=await api.get('/dashboard',token);setDash(d)}catch(e){}setL(false)};
  useEffect(()=>{load();const i=setInterval(load,30000);return()=>clearInterval(i)},[]);
  if(selected)return <MonitorDetail monitorId={selected.id} token={token} onBack={()=>{setSel(null);load();}}/>;
  if(loading)return <div className="flex justify-center py-20"><Spinner/></div>;
  const ov=dash?.overview||{};
  return <div className="space-y-6 animate-fade-in">
    <div className="flex items-center justify-between flex-wrap gap-4"><div><h1 className="text-3xl font-bold bg-gradient-to-r from-neon-pink to-neon-purple bg-clip-text text-transparent">Dashboard</h1><p className="text-white/40 mt-1">Welcome, {user.full_name||user.username}! 👋</p></div><button onClick={()=>setSC(true)} className="neon-btn">➕ Add Monitor</button></div>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"><StatCard icon="📡" label="Total Monitors" value={ov.total_monitors||0} subtext="active"/><StatCard icon="✅" label="UP" value={ov.up||0} subtext={`${ov.down||0} down`}/><StatCard icon="📊" label="Avg Uptime" value={`${ov.avg_uptime?.toFixed(2)||100}%`} subtext="overall"/><StatCard icon="⚡" label="Avg Response" value={`${ov.avg_response_time?.toFixed(0)||0}ms`} subtext="latest"/></div>
    {dash?.monitors?.length>0?<div><h2 className="text-xl font-semibold mb-4 text-white/80">Your Monitors</h2><div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{dash.monitors.map(m=><MonitorCard key={m.id} monitor={m} onClick={setSel}/>)}</div></div>:<div className="glass-card p-12 text-center"><p className="text-5xl mb-4">📡</p><h3 className="text-2xl font-bold text-white/80 mb-2">No monitors yet</h3><p className="text-white/40 mb-6">Create your first monitor</p><button onClick={()=>setSC(true)} className="neon-btn">Create Monitor</button></div>}
    {showCreate&&<CreateModal token={token} onClose={()=>setSC(false)} onCreated={()=>load()}/>}
  </div>;
}
function AdminConfigPage({token}){
  const[config,setC]=useState(null);const[loading,setL]=useState(true);const[saving,setSv]=useState(false);const[toast,setT]=useState(null);
  useEffect(()=>{api.get('/site-config',token).then(d=>{setC(d.config);setL(false)})},[]);
  const save=async()=>{setSv(true);try{const d=await api.put('/site-config',config,token);setC(d.config);setT({message:'Saved!',type:'success'});const vc=document.querySelector('#bg-video-container');if(config.bg_video_url&&vc)vc.innerHTML=`<video autoplay muted loop playsinline><source src="${config.bg_video_url}" type="video/mp4"></video>`;}catch(e){setT({message:e.message,type:'error'})}setSv(false)};
  if(loading)return <div className="flex justify-center py-20"><Spinner/></div>;
  const F=({label,field,type='text',ph})=><div><label className="text-sm text-white/60 mb-1 block">{label}</label>{type==='textarea'?<textarea className="neon-input min-h-[80px]" value={config[field]||''} onChange={e=>setC({...config,[field]:e.target.value})} placeholder={ph}/>:type==='checkbox'?<div className={`toggle-switch ${config[field]?'active':''}`} onClick={()=>setC({...config,[field]:!config[field]})}/>:<input type={type} className="neon-input" value={config[field]||''} onChange={e=>setC({...config,[field]:type==='number'?parseFloat(e.target.value):e.target.value})} placeholder={ph}/>}</div>;
  return <div className="space-y-6 animate-fade-in">
    {toast&&<Toast {...toast} onClose={()=>setT(null)}/>}
    <div className="flex items-center justify-between"><h1 className="text-3xl font-bold text-neon-pink">⚙️ Site Config</h1><button onClick={save} className="neon-btn" disabled={saving}>{saving?'Saving...':'💾 Save All'}</button></div>
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="glass-card p-6 space-y-4"><h3 className="text-xl font-semibold text-neon-purple">🏷️ Branding</h3><F label="Site Name" field="site_name" ph="NeonWatch"/><F label="Tagline" field="site_tagline" ph="God-Level Monitoring"/><F label="Logo URL" field="logo_url" ph="https://..."/><F label="Footer" field="footer_text" ph="© 2024..."/></div>
      <div className="glass-card p-6 space-y-4"><h3 className="text-xl font-semibold text-neon-purple">🎬 Media</h3><F label="Background Video URL (mp4/webm)" field="bg_video_url" ph="https://...video.mp4"/><F label="Background Music URL (mp3)" field="bg_music_url" ph="https://...music.mp3"/><F label="OG Image" field="og_image_url" ph="https://..."/></div>
      <div className="glass-card p-6 space-y-4"><h3 className="text-xl font-semibold text-neon-purple">🎨 Colors</h3><div className="grid grid-cols-2 gap-4"><F label="Primary" field="primary_color_theme" ph="#F806CC"/><F label="Secondary" field="secondary_color_theme" ph="#2E0249"/><F label="Accent" field="accent_color" ph="#A855F7"/><F label="Glow" field="glow_color" ph="#F806CC"/></div></div>
      <div className="glass-card p-6 space-y-4"><h3 className="text-xl font-semibold text-neon-purple">🔧 Features</h3><div className="space-y-3"><div className="flex items-center justify-between"><span className="text-white/70">Particles</span><F field="enable_particles" type="checkbox"/></div><div className="flex items-center justify-between"><span className="text-white/70">Animations</span><F field="enable_animations" type="checkbox"/></div><div className="flex items-center justify-between"><span className="text-white/70">Maintenance</span><F field="maintenance_mode" type="checkbox"/></div><div className="flex items-center justify-between"><span className="text-white/70">Signup</span><F field="signup_enabled" type="checkbox"/></div></div><F label="Max Free Monitors" field="max_free_monitors" type="number" ph="10"/></div>
    </div>
  </div>;
}
function AdminUsersPage({token}){
  const[users,setU]=useState([]);const[loading,setL]=useState(true);const[search,setS]=useState('');const[toast,setT]=useState(null);
  const load=async()=>{try{const d=await api.get(`/admin/users?search=${search}&limit=100`,token);setU(d.users)}catch(e){}setL(false)};
  useEffect(()=>{load()},[search]);
  const ban=async(id)=>{try{await api.post(`/admin/users/${id}/ban`,{},token);setT({message:'Banned',type:'success'});load()}catch(e){setT({message:e.message,type:'error'})}};
  const unban=async(id)=>{try{await api.post(`/admin/users/${id}/unban`,{},token);setT({message:'Unbanned',type:'success'});load()}catch(e){setT({message:e.message,type:'error'})}};
  return <div className="space-y-6 animate-fade-in">{toast&&<Toast {...toast} onClose={()=>setT(null)}/>}<h1 className="text-3xl font-bold text-neon-pink">👥 Users</h1><input className="neon-input max-w-md" value={search} onChange={e=>setS(e.target.value)} placeholder="🔍 Search..."/>{loading?<Spinner/>:<div className="glass-card overflow-hidden overflow-x-auto"><table className="w-full text-sm"><thead><tr className="bg-neon-pink/5 text-neon-pink"><th className="p-3 text-left">User</th><th className="p-3 text-left">Email</th><th className="p-3 text-left">Role</th><th className="p-3 text-left">Plan</th><th className="p-3 text-left">Monitors</th><th className="p-3 text-left">Status</th><th className="p-3 text-left">Actions</th></tr></thead><tbody>{users.map(u=><tr key={u.id} className="border-b border-white/5 hover:bg-white/5"><td className="p-3 font-semibold">{u.username}</td><td className="p-3 text-white/60">{u.email}</td><td className="p-3"><span className="px-2 py-1 rounded-full text-xs bg-neon-purple/20 text-neon-purple">{u.role}</span></td><td className="p-3 text-white/60">{u.plan}</td><td className="p-3">{u.monitor_count}</td><td className="p-3">{u.is_banned?<span className="text-neon-red">Banned</span>:<span className="text-neon-green">Active</span>}</td><td className="p-3">{u.is_banned?<button onClick={()=>unban(u.id)} className="text-neon-green hover:underline text-xs">Unban</button>:<button onClick={()=>ban(u.id)} className="text-neon-red hover:underline text-xs">Ban</button>}</td></tr>)}</tbody></table></div>}</div>;
}
function AdminStatsPage({token}){
  const[stats,setS]=useState(null);const[loading,setL]=useState(true);
  useEffect(()=>{api.get('/admin/stats',token).then(d=>{setS(d.stats);setL(false)})},[]);
  if(loading)return <div className="flex justify-center py-20"><Spinner/></div>;
  return <div className="space-y-6 animate-fade-in"><h1 className="text-3xl font-bold text-neon-pink">📊 System Stats</h1><div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"><StatCard icon="👥" label="Users" value={stats.total_users} subtext={`${stats.new_users_week} new`}/><StatCard icon="📡" label="Monitors" value={stats.total_monitors} subtext={`${stats.active_monitors} active`}/><StatCard icon="✅" label="Total Checks" value={stats.total_checks?.toLocaleString()} subtext="all time"/><StatCard icon="🔴" label="Incidents" value={stats.total_incidents} subtext={`${stats.open_incidents} open`}/></div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6"><div className="glass-card p-6"><h3 className="text-lg font-semibold text-neon-purple mb-4">Monitor Types</h3>{Object.entries(stats.monitor_types||{}).map(([t,c])=><div key={t} className="flex justify-between py-2 border-b border-white/5"><span className="text-white/70 uppercase">{t}</span><span className="text-neon-pink font-bold">{c}</span></div>)}</div><div className="glass-card p-6"><h3 className="text-lg font-semibold text-neon-purple mb-4">Plans</h3>{Object.entries(stats.plan_distribution||{}).map(([p,c])=><div key={p} className="flex justify-between py-2 border-b border-white/5"><span className="text-white/70 uppercase">{p}</span><span className="text-neon-pink font-bold">{c}</span></div>)}</div></div>
  </div>;
}
function SettingsPage({token,user,onUpdate}){
  const[f,sF]=useState({full_name:user.full_name||'',notification_email:user.notification_email||'',webhook_url:user.webhook_url||'',discord_webhook:user.discord_webhook||'',slack_webhook:user.slack_webhook||'',timezone:user.timezone||'UTC'});
  const[toast,setT]=useState(null);const[saving,setSv]=useState(false);
  const save=async()=>{setSv(true);try{const d=await api.put('/auth/me',f,token);onUpdate(d.user);setT({message:'Saved!',type:'success'})}catch(e){setT({message:e.message,type:'error'})}setSv(false)};
  return <div className="space-y-6 animate-fade-in max-w-2xl">{toast&&<Toast {...toast} onClose={()=>setT(null)}/>}<h1 className="text-3xl font-bold text-neon-pink">⚙️ Settings</h1>
    <div className="glass-card p-6 space-y-4"><h3 className="text-lg font-semibold text-neon-purple">Profile</h3><div><label className="text-sm text-white/60 mb-1 block">Full Name</label><input className="neon-input" value={f.full_name} onChange={e=>sF({...f,full_name:e.target.value})}/></div><div><label className="text-sm text-white/60 mb-1 block">Timezone</label><input className="neon-input" value={f.timezone} onChange={e=>sF({...f,timezone:e.target.value})}/></div></div>
    <div className="glass-card p-6 space-y-4"><h3 className="text-lg font-semibold text-neon-purple">Alerts</h3><div><label className="text-sm text-white/60 mb-1 block">Email</label><input className="neon-input" value={f.notification_email} onChange={e=>sF({...f,notification_email:e.target.value})} placeholder="alerts@example.com"/></div><div><label className="text-sm text-white/60 mb-1 block">Webhook</label><input className="neon-input" value={f.webhook_url} onChange={e=>sF({...f,webhook_url:e.target.value})}/></div><div><label className="text-sm text-white/60 mb-1 block">Discord</label><input className="neon-input" value={f.discord_webhook} onChange={e=>sF({...f,discord_webhook:e.target.value})}/></div><div><label className="text-sm text-white/60 mb-1 block">Slack</label><input className="neon-input" value={f.slack_webhook} onChange={e=>sF({...f,slack_webhook:e.target.value})}/></div></div>
    <div className="glass-card p-6 space-y-4"><h3 className="text-lg font-semibold text-neon-purple">API</h3><div><label className="text-sm text-white/60 mb-1 block">API Key</label><input className="neon-input font-mono" value={user.api_key} readOnly/></div><div className="flex items-center gap-3"><span className="px-3 py-1 rounded-full bg-neon-purple/20 text-neon-purple uppercase font-semibold">{user.plan}</span><span className="text-white/40">({user.max_monitors} monitors max)</span></div></div>
    <button onClick={save} className="neon-btn w-full py-3" disabled={saving}>{saving?'Saving...':'💾 Save'}</button>
  </div>;
}
function Sidebar({currentPage,setPage,user,onLogout,siteConfig}){
  const isAdmin=user.role==='admin'||user.role==='superadmin';
  const links=[{id:'dashboard',label:'Dashboard',icon:'📊'},{id:'monitors',label:'Monitors',icon:'📡'},{id:'settings',label:'Settings',icon:'⚙️'}];
  const adminLinks=[{id:'admin-stats',label:'System Stats',icon:'📈'},{id:'admin-users',label:'Users',icon:'👥'},{id:'admin-config',label:'Site Config',icon:'🎨'}];
  return <div className="sidebar w-64 min-h-screen p-4 flex flex-col shrink-0 hidden md:flex">
    <div className="mb-8 px-2"><Logo config={siteConfig} size="sm"/></div>
    <nav className="flex-1 space-y-1">{links.map(l=><div key={l.id} className={`sidebar-link ${currentPage===l.id?'active':''}`} onClick={()=>setPage(l.id)}><span className="text-xl">{l.icon}</span><span>{l.label}</span></div>)}{isAdmin&&<><div className="mt-6 mb-2 px-4 text-xs text-neon-pink/60 uppercase tracking-wider font-semibold">Admin</div>{adminLinks.map(l=><div key={l.id} className={`sidebar-link ${currentPage===l.id?'active':''}`} onClick={()=>setPage(l.id)}><span className="text-xl">{l.icon}</span><span>{l.label}</span></div>)}</>}</nav>
    <div className="mt-auto pt-4 border-t border-white/10"><div className="px-4 py-2"><p className="text-sm font-semibold text-white/80">{user.full_name||user.username}</p><p className="text-xs text-white/40">{user.email}</p><span className="text-xs px-2 py-0.5 rounded-full bg-neon-purple/20 text-neon-purple mt-1 inline-block">{user.role}</span></div><div className="sidebar-link mt-2 text-red-400" onClick={onLogout}><span>🚪</span><span>Logout</span></div></div>
  </div>;
}
function LoginPage({onLogin,switchTo}){
  const[login,setLogin]=useState('');const[pw,setPw]=useState('');const[err,setErr]=useState('');const[ld,setLd]=useState(false);
  const submit=async(e)=>{e.preventDefault();setLd(true);setErr('');try{const d=await api.post('/auth/login',{login,password:pw});onLogin(d.token,d.user)}catch(e){setErr(e.message)}setLd(false)};
  return <div className="min-h-screen flex items-center justify-center p-4"><div className="glass-card p-8 w-full max-w-md animate-slide-up"><div className="text-center mb-8"><Logo size="lg"/><p className="text-white/50 mt-2">Sign in to your dashboard</p></div><form onSubmit={submit} className="space-y-5">{err&&<div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">{err}</div>}<div><label className="text-sm text-white/60 mb-1 block">Username or Email</label><input className="neon-input" value={login} onChange={e=>setLogin(e.target.value)} placeholder="admin" required/></div><div><label className="text-sm text-white/60 mb-1 block">Password</label><input type="password" className="neon-input" value={pw} onChange={e=>setPw(e.target.value)} placeholder="••••••••" required/></div><button type="submit" className="neon-btn w-full py-3 text-lg" disabled={ld}>{ld?'Signing in...':'⚡ Sign In'}</button></form><p className="text-center text-white/40 mt-6 text-sm">No account? <span onClick={switchTo} className="text-neon-pink cursor-pointer hover:underline">Register</span></p></div></div>;
}
function RegisterPage({onLogin,switchTo}){
  const[f,sF]=useState({username:'',email:'',password:'',full_name:''});const[err,setErr]=useState('');const[ld,setLd]=useState(false);
  const submit=async(e)=>{e.preventDefault();setLd(true);setErr('');try{const d=await api.post('/auth/register',f);onLogin(d.token,d.user)}catch(e){setErr(e.message)}setLd(false)};
  return <div className="min-h-screen flex items-center justify-center p-4"><div className="glass-card p-8 w-full max-w-md animate-slide-up"><div className="text-center mb-8"><Logo size="lg"/><p className="text-white/50 mt-2">Create your account</p></div><form onSubmit={submit} className="space-y-4">{err&&<div className="bg-red-500/10 border border-red-500/30 text-red-400 p-3 rounded-xl text-sm">{err}</div>}<input className="neon-input" value={f.full_name} onChange={e=>sF({...f,full_name:e.target.value})} placeholder="Full Name"/><input className="neon-input" value={f.username} onChange={e=>sF({...f,username:e.target.value})} placeholder="Username" required/><input type="email" className="neon-input" value={f.email} onChange={e=>sF({...f,email:e.target.value})} placeholder="Email" required/><input type="password" className="neon-input" value={f.password} onChange={e=>sF({...f,password:e.target.value})} placeholder="Password (min 8)" required/><button type="submit" className="neon-btn w-full py-3 text-lg" disabled={ld}>{ld?'Creating...':'🚀 Register'}</button></form><p className="text-center text-white/40 mt-6 text-sm">Have an account? <span onClick={switchTo} className="text-neon-pink cursor-pointer hover:underline">Sign In</span></p></div></div>;
}
function App(){
  const[token,setToken]=useState(localStorage.getItem('nw_token'));
  const[user,setUser]=useState(null);
  const[page,setPage]=useState('dashboard');
  const[authPage,setAP]=useState('login');
  const[siteConfig,setSC]=useState(null);
  const[loading,setLoading]=useState(true);

  useEffect(()=>{api.get('/site-config').then(d=>{setSC(d.config);document.title=d.config.meta_title||d.config.site_name||'NeonWatch';const vc=document.getElementById('bg-video-container');if(d.config.bg_video_url&&vc)vc.innerHTML=`<video autoplay muted loop playsinline><source src="${d.config.bg_video_url}" type="video/mp4"></video>`;const au=document.getElementById('bg-audio');if(d.config.bg_music_url&&au)au.src=d.config.bg_music_url;}).catch(()=>{})},[]);

  useEffect(()=>{if(token){api.get('/auth/me',token).then(d=>{setUser(d.user);setLoading(false)}).catch(()=>{localStorage.removeItem('nw_token');setToken(null);setLoading(false)})}else setLoading(false)},[token]);

  const handleLogin=(t,u)=>{localStorage.setItem('nw_token',t);setToken(t);setUser(u)};
  const handleLogout=()=>{localStorage.removeItem('nw_token');setToken(null);setUser(null);setPage('dashboard')};

  if(loading)return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg"/></div>;
  if(!token||!user)return <div><Particles/>{authPage==='login'?<LoginPage onLogin={handleLogin} switchTo={()=>setAP('register')}/>:<RegisterPage onLogin={handleLogin} switchTo={()=>setAP('login')}/>}<MusicToggle url={siteConfig?.bg_music_url}/></div>;

  const renderPage=()=>{switch(page){case 'dashboard':case 'monitors':return <DashboardPage token={token} user={user}/>;case 'settings':return <SettingsPage token={token} user={user} onUpdate={setUser}/>;case 'admin-stats':return <AdminStatsPage token={token}/>;case 'admin-users':return <AdminUsersPage token={token}/>;case 'admin-config':return <AdminConfigPage token={token}/>;default:return <DashboardPage token={token} user={user}/>}};

  return <div className="flex min-h-screen"><Particles/><Sidebar currentPage={page} setPage={setPage} user={user} onLogout={handleLogout} siteConfig={siteConfig}/><main className="flex-1 p-4 md:p-8 overflow-y-auto relative z-10 min-h-screen">{renderPage()}</main><MusicToggle url={siteConfig?.bg_music_url}/></div>;
}
const root=ReactDOM.createRoot(document.getElementById('root'));
root.render(<App/>);
</script>
</body></html>"""


# =============================================================================
# SECTION 25: SERVE FRONTEND
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_root():
    return HTMLResponse(content=FRONTEND_HTML)


# Catch-all for SPA client-side routing
@app.get("/{path:path}", response_class=HTMLResponse)
async def serve_spa(path: str):
    """Catch-all: serve SPA for any non-API route."""
    if path.startswith("api/") or path.startswith("ws/"):
        raise HTTPException(404, "Not found")
    return HTMLResponse(content=FRONTEND_HTML)


# =============================================================================
# SECTION 26: ERROR HANDLERS
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "detail": exc.detail})


@app.exception_handler(Exception)
async def general_exc_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"success": False, "detail": "Internal server error"})


# =============================================================================
# SECTION 27: MAIN
# =============================================================================

def main():
    import uvicorn
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║  ⚡ NEONWATCH - GOD LEVEL UPTIME MONITORING ⚡            ║
    ║  🌐 http://localhost:8000                                 ║
    ║  📚 http://localhost:8000/docs                            ║
    ║  🔐 admin / admin123456                                   ║
    ║  🎨 Neon Pink & Purple Theme 💜💖                          ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    uvicorn.run("monitoring:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()