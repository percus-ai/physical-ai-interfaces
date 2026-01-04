"""Teleoperation API models."""

from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field


class TeleopStartRequest(BaseModel):
    """Request to start local teleoperation."""

    leader_port: str = Field(..., description="Leader arm serial port")
    follower_port: str = Field(..., description="Follower arm serial port")
    mode: str = Field("simple", description="Teleop mode: simple, visual, bimanual")
    fps: int = Field(60, ge=1, le=120, description="Control frequency in Hz")
    robot_preset: str = Field("so101", description="Robot preset: so101, so100")


class TeleopSession(BaseModel):
    """Teleoperation session information."""

    session_id: str = Field(..., description="Session ID")
    mode: str = Field(..., description="Teleop mode")
    leader_port: str = Field(..., description="Leader arm port")
    follower_port: str = Field(..., description="Follower arm port")
    fps: int = Field(..., description="Control frequency")
    is_running: bool = Field(..., description="Session is running")
    started_at: str = Field(..., description="Session start time")
    iterations: int = Field(0, description="Number of iterations")
    errors: int = Field(0, description="Error count")


class TeleopStartResponse(BaseModel):
    """Response for teleop start endpoint."""

    session: TeleopSession
    message: str


class TeleopStopRequest(BaseModel):
    """Request to stop teleoperation."""

    session_id: str = Field(..., description="Session ID to stop")


class TeleopStopResponse(BaseModel):
    """Response for teleop stop endpoint."""

    session_id: str
    success: bool
    message: str
    total_iterations: int = 0
    duration_seconds: float = 0.0


class TeleopSessionsResponse(BaseModel):
    """Response for sessions list endpoint."""

    sessions: List[TeleopSession]
    total: int


# Remote teleoperation models


class RemoteLeaderStartRequest(BaseModel):
    """Request to start remote leader server."""

    host: str = Field("0.0.0.0", description="Host to bind")
    port: int = Field(8080, ge=1024, le=65535, description="Port to bind")
    fps: int = Field(60, ge=1, le=120, description="Read frequency in Hz")
    leader_port: str = Field(..., description="Leader arm serial port")
    camera_id: Optional[int] = Field(None, description="Camera ID for video stream")


class RemoteLeaderSession(BaseModel):
    """Remote leader session information."""

    session_id: str = Field(..., description="Session ID")
    host: str = Field(..., description="Host address")
    port: int = Field(..., description="Port number")
    url: str = Field(..., description="Leader URL for followers")
    leader_port: str = Field(..., description="Leader arm port")
    camera_enabled: bool = Field(False, description="Camera streaming enabled")
    is_running: bool = Field(..., description="Server is running")
    started_at: str = Field(..., description="Session start time")
    clients_connected: int = Field(0, description="Number of connected followers")


class RemoteLeaderStartResponse(BaseModel):
    """Response for remote leader start endpoint."""

    session: RemoteLeaderSession
    message: str


class RemoteFollowerStartRequest(BaseModel):
    """Request to start remote follower client."""

    leader_url: str = Field(..., description="Leader server URL")
    follower_port: str = Field(..., description="Follower arm serial port")
    robot_preset: str = Field("so101", description="Robot preset")


class RemoteFollowerSession(BaseModel):
    """Remote follower session information."""

    session_id: str = Field(..., description="Session ID")
    leader_url: str = Field(..., description="Leader server URL")
    follower_port: str = Field(..., description="Follower arm port")
    is_connected: bool = Field(..., description="Connected to leader")
    is_running: bool = Field(..., description="Client is running")
    started_at: str = Field(..., description="Session start time")
    latency_ms: float = Field(0.0, description="Average latency in ms")
    sync_errors: int = Field(0, description="Sync error count")


class RemoteFollowerStartResponse(BaseModel):
    """Response for remote follower start endpoint."""

    session: RemoteFollowerSession
    message: str


class RemoteSessionsResponse(BaseModel):
    """Response for remote sessions list endpoint."""

    leaders: List[RemoteLeaderSession]
    followers: List[RemoteFollowerSession]
