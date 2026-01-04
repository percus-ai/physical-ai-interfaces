"""Calibration API models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MotorCalibrationModel(BaseModel):
    """Calibration data for a single motor."""

    name: str = Field(..., description="Motor name")
    homing_offset: int = Field(0, description="Homing offset")
    drive_mode: int = Field(0, description="Drive mode")
    min_position: int = Field(0, description="Minimum position")
    max_position: int = Field(4095, description="Maximum position")


class CalibrationDataModel(BaseModel):
    """Calibration data for an arm."""

    arm_id: str = Field(..., description="Arm identifier")
    arm_type: str = Field(..., description="Arm type (e.g., so101)")
    motors: Dict[str, MotorCalibrationModel] = Field(
        default_factory=dict, description="Motor calibrations"
    )
    created_at: Optional[str] = Field(None, description="Creation timestamp")


class CalibrationListResponse(BaseModel):
    """Response for calibration list endpoint."""

    calibrations: List[CalibrationDataModel]
    total: int


class CalibrationStartRequest(BaseModel):
    """Request to start calibration session."""

    arm_type: str = Field(..., description="Arm type: so101_leader, so101_follower")
    port: str = Field(..., description="Serial port for the arm")
    arm_id: Optional[str] = Field(None, description="Arm identifier (auto-generated if not provided)")


class CalibrationSession(BaseModel):
    """Calibration session information."""

    session_id: str = Field(..., description="Session ID")
    arm_id: str = Field(..., description="Arm identifier")
    arm_type: str = Field(..., description="Arm type")
    port: str = Field(..., description="Serial port")
    status: str = Field(..., description="Session status: pending, in_progress, completed, failed")
    started_at: str = Field(..., description="Session start time")
    motors_to_calibrate: List[str] = Field(default_factory=list, description="Motors to calibrate")
    calibrated_motors: List[str] = Field(default_factory=list, description="Calibrated motors")
    current_motor: Optional[str] = Field(None, description="Current motor being calibrated")


class CalibrationStartResponse(BaseModel):
    """Response for calibration start endpoint."""

    session: CalibrationSession
    message: str


class RecordPositionRequest(BaseModel):
    """Request to record motor position."""

    motor_name: str = Field(..., description="Motor name")
    position_type: str = Field(..., description="Position type: min, max, home")


class RecordPositionResponse(BaseModel):
    """Response for record position endpoint."""

    motor_name: str
    position_type: str
    position: int = Field(..., description="Recorded position value")
    success: bool
    message: str


class CalibrationCompleteRequest(BaseModel):
    """Request to complete calibration."""

    save: bool = Field(True, description="Save calibration to file")


class CalibrationCompleteResponse(BaseModel):
    """Response for calibration complete endpoint."""

    session_id: str
    arm_id: str
    success: bool
    message: str
    calibration: Optional[CalibrationDataModel] = None


class CalibrationUpdateRequest(BaseModel):
    """Request to update calibration."""

    motors: Dict[str, MotorCalibrationModel] = Field(
        ..., description="Updated motor calibrations"
    )


class CalibrationImportRequest(BaseModel):
    """Request to import calibration."""

    calibration: CalibrationDataModel = Field(..., description="Calibration data to import")


class CalibrationExportResponse(BaseModel):
    """Response for calibration export endpoint."""

    arm_id: str
    arm_type: str
    calibration: CalibrationDataModel
    export_path: Optional[str] = Field(None, description="Exported file path")


class CalibrationSessionsResponse(BaseModel):
    """Response for calibration sessions list endpoint."""

    sessions: List[CalibrationSession]
    total: int
