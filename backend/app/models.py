"""SQLAlchemy ORM models for Users, Activation Codes, Services, and Permission Grants."""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # 'admin' or 'user'
    created_at = Column(DateTime, default=utc_now, nullable=False)

    permissions = relationship(
        "PermissionGrant", back_populates="user", cascade="all, delete-orphan"
    )


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(200), nullable=True, default="")
    # Internal tier mapping: '18+', '<=15+', '*' etc.
    grant_tier = Column(String(64), nullable=True)
    # Optional specific service slug to unlock
    grant_service_slug = Column(String(64), nullable=True)
    # -1 means unlimited/infinite uses; positive integer means finite limit
    max_uses = Column(Integer, nullable=False, default=1)
    used_count = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default="")
    icon = Column(String(64), nullable=False, default="⚡")
    tier = Column(String(10), nullable=False, index=True, default="6+")
    target_url = Column(String(500), nullable=False)
    open_in_new_tab = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    # Operational state: 'active' (运行中), 'disabled' (已关闭), 'offline' (暂不可用/Mac离线), 'wip' (待开发)
    status = Column(String(20), nullable=False, default="active")
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class PermissionGrant(Base):
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    session_token = Column(String(64), nullable=True, index=True)
    unlocked_tier = Column(String(10), nullable=True)
    unlocked_service_slug = Column(String(64), nullable=True)
    source_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    user = relationship("User", back_populates="permissions")
