"""Teleop session API models."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TeleopSessionCreateRequest(BaseModel):
    profile: Optional[str] = Field(None, description="Optional profile name for VLAbor up script")
    domain_id: Optional[int] = Field(None, ge=0, description="Optional ROS domain id")
    dev_mode: bool = Field(False, description="Use docker/vlabor/up --dev")


class TeleopSessionStartRequest(BaseModel):
    session_id: str = Field(..., min_length=1, description="Teleop session id")


class TeleopSessionStopRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Teleop session id")


class TeleopSessionActionResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    message: str
    status: Dict[str, Any] = Field(default_factory=dict)


class TeleopSessionStatusResponse(BaseModel):
    active: bool = False
    session_id: Optional[str] = None
    state: str = "stopped"
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    profile: Optional[str] = None
    domain_id: Optional[int] = None
    dev_mode: bool = False
    status: Dict[str, Any] = Field(default_factory=dict)

