"""Recording API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CameraConfig(BaseModel):
    """Camera configuration for recording."""

    camera_id: str = Field(..., description="Camera identifier")
    camera_type: str = Field("opencv", description="Camera type: opencv, intelrealsense")
    index_or_path: int = Field(0, description="Camera index or device path")
    width: int = Field(640, description="Frame width")
    height: int = Field(480, description="Frame height")
    fps: int = Field(30, description="Frames per second")
    warmup_s: float = Field(5.0, description="Camera warmup time in seconds")
    color_mode: Optional[str] = Field(None, description="Color mode: rgb, bgr")
    rotation: Optional[int] = Field(None, description="Rotation degrees: 0, 90, 180, 270")


class RecordingStartRequest(BaseModel):
    """Request to start recording."""

    project_id: str = Field(..., description="Project ID for this recording")
    task_description: str = Field("", description="Task description for dataset")
    episode_name: Optional[str] = Field(None, description="Optional episode name")
    cameras: List[CameraConfig] = Field(default_factory=list, description="Camera configurations")
    leader_port: Optional[str] = Field(None, description="Leader arm port")
    follower_port: Optional[str] = Field(None, description="Follower arm port")
    leader_id: str = Field("so101_leader", description="Leader calibration ID")
    follower_id: str = Field("so101_follower", description="Follower calibration ID")
    robot_type: str = Field("so101", description="Robot type: so101, so100")
    fps: int = Field(30, description="Recording frequency in Hz")
    episode_time_s: int = Field(60, description="Episode duration in seconds")
    reset_time_s: int = Field(10, description="Reset time between episodes")
    num_episodes: int = Field(1, description="Number of episodes to record")
    username: str = Field("user", description="Username for dataset")


class RecordingSession(BaseModel):
    """Recording session information."""

    session_id: str = Field(..., description="Session ID")
    project_id: str = Field(..., description="Project ID")
    episode_name: str = Field(..., description="Episode name")
    status: str = Field("pending", description="Status: pending, recording, completed, failed, stopped")
    is_recording: bool = Field(..., description="Recording is in progress")
    started_at: str = Field(..., description="Session start time")
    frames_recorded: int = Field(0, description="Number of frames recorded")
    duration_seconds: float = Field(0.0, description="Recording duration")
    cameras: List[str] = Field(default_factory=list, description="Active camera IDs")
    output_path: Optional[str] = Field(None, description="Output file path")
    num_episodes: int = Field(1, description="Number of episodes to record")
    current_episode: int = Field(0, description="Current episode number")
    error_message: Optional[str] = Field(None, description="Error message if failed")


class RecordingStartResponse(BaseModel):
    """Response for recording start endpoint."""

    session: RecordingSession
    message: str


class RecordingStopRequest(BaseModel):
    """Request to stop recording."""

    session_id: str = Field(..., description="Session ID to stop")


class RecordingStopResponse(BaseModel):
    """Response for recording stop endpoint."""

    session_id: str
    success: bool
    message: str
    total_frames: int = Field(0, description="Total frames recorded")
    duration_seconds: float = Field(0.0, description="Total duration")
    output_path: Optional[str] = Field(None, description="Output file path")
    size_mb: float = Field(0.0, description="Output file size in MB")


class RecordingSessionsResponse(BaseModel):
    """Response for sessions list endpoint."""

    sessions: List[RecordingSession]
    total: int


class RecordingInfo(BaseModel):
    """Stored recording information."""

    recording_id: str = Field(..., description="Recording ID")
    project_id: str = Field(..., description="Project ID")
    episode_name: str = Field(..., description="Episode name")
    created_at: str = Field(..., description="Creation time")
    duration_seconds: float = Field(0.0, description="Duration")
    frames: int = Field(0, description="Total frames")
    size_mb: float = Field(0.0, description="Size in MB")
    cameras: List[str] = Field(default_factory=list, description="Camera IDs used")
    path: str = Field(..., description="Recording path")
    is_valid: bool = Field(True, description="Recording is valid")


class RecordingListResponse(BaseModel):
    """Response for recordings list endpoint."""

    recordings: List[RecordingInfo]
    total: int


class RecordingValidateResponse(BaseModel):
    """Response for recording validation endpoint."""

    recording_id: str
    is_valid: bool
    errors: List[str] = Field(default_factory=list, description="Validation errors")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Recording statistics")


class RecordingExportRequest(BaseModel):
    """Request to export recording."""

    format: str = Field("lerobot", description="Export format: lerobot, raw")
    include_video: bool = Field(True, description="Include video files")


class RecordingExportResponse(BaseModel):
    """Response for recording export endpoint."""

    recording_id: str
    success: bool
    message: str
    export_path: Optional[str] = Field(None, description="Exported file path")
    size_mb: float = Field(0.0, description="Export size in MB")
