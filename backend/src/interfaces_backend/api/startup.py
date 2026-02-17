"""Startup operations API."""

from __future__ import annotations

from fastapi import APIRouter

from interfaces_backend.models.startup import StartupOperationStatusResponse
from interfaces_backend.services.session_manager import require_user_id
from interfaces_backend.services.startup_operations import get_startup_operations_service

router = APIRouter(prefix="/api/startup", tags=["startup"])


@router.get("/operations/{operation_id}", response_model=StartupOperationStatusResponse)
async def get_operation(operation_id: str):
    user_id = require_user_id()
    return get_startup_operations_service().get(
        user_id=user_id,
        operation_id=operation_id,
    )
