"""Operate status models."""

from typing import Dict

from pydantic import BaseModel, Field


class OperateServiceStatus(BaseModel):
    name: str
    status: str = Field("unknown", description="running | stopped | error | unknown | degraded")
    message: str = Field("", description="Short status message")
    details: Dict[str, object] = Field(default_factory=dict)


class OperateStatusResponse(BaseModel):
    backend: OperateServiceStatus
    vlabor: OperateServiceStatus
    lerobot: OperateServiceStatus
    network: OperateServiceStatus
    driver: OperateServiceStatus
