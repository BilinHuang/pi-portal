"""Pydantic schemas for API request validation and response serialization."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class ActivateCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


class ActivateCodeResponse(BaseModel):
    success: bool
    message: str
    unlocked_tiers: List[str]
    unlocked_services: List[str]
    remaining_uses: Optional[int] = None


class AuthStatusResponse(BaseModel):
    is_authenticated: bool
    is_guest_activated: bool
    username: Optional[str] = None
    role: str = "guest"
    unlocked_tiers: List[str]
    unlocked_services: List[str]
    client_ip: str


class ServiceCardSchema(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    icon: str
    status: str  # 'active' | 'disabled' | 'offline' | 'wip'
    status_label: str
    status_badge_class: str
    is_available: bool
    launch_url: str
    target_url: str
    open_in_new_tab: bool


class TierGroupSchema(BaseModel):
    group_id: str
    label: str
    subtitle: str
    services: List[ServiceCardSchema]


class DashboardServicesResponse(BaseModel):
    groups: List[TierGroupSchema]
    total_visible_services: int


# Admin Schemas
class CreateActivationCodeRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    description: str = Field(default="", max_length=200)
    grant_tier: Optional[str] = Field(default=None, max_length=64)
    grant_service_slug: Optional[str] = Field(default=None, max_length=64)
    max_uses: int = Field(default=1, ge=-1)


class ActivationCodeItemSchema(BaseModel):
    id: int
    code: str
    description: str
    grant_tier: Optional[str]
    grant_service_slug: Optional[str]
    max_uses: int
    used_count: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CreateServiceRequest(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    icon: str = Field(default="⚡", max_length=64)
    tier: str = Field(..., pattern=r"^(6\+|9\+|12\+|15\+|18\+)$")
    target_url: str = Field(..., min_length=1, max_length=500)
    status: str = Field(default="active", pattern=r"^(active|disabled|offline|wip)$")
    open_in_new_tab: bool = True
    sort_order: int = 0


class UpdateServiceStatusRequest(BaseModel):
    status: str = Field(..., pattern=r"^(active|disabled|offline|wip)$")
