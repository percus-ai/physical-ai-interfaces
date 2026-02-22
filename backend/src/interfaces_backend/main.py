"""FastAPI server entrypoint."""

import argparse
import logging
import os
import time
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv

from interfaces_backend.core.logging import setup_file_logging

# Configure logging with console and file output
setup_file_logging(app_name="backend", console_level=logging.INFO)
# Set specific loggers to INFO level
logging.getLogger("interfaces_backend").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _find_repo_root() -> Path:
    """Find repository root by looking for data/.env file."""
    current = Path.cwd()
    for _ in range(10):  # Look up to 10 levels
        # Priority: look for data/.env (indicates repo root with config)
        if (current / "data" / ".env").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: look for .git that is a directory (not file, which indicates submodule)
    current = Path.cwd()
    for _ in range(10):
        git_path = current / ".git"
        if git_path.exists() and git_path.is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd()


# Load .env from repository root data directory
_repo_root = _find_repo_root()
_env_file = _repo_root / "data" / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Fallback: try current directory
    load_dotenv()
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request

from interfaces_backend.api import (
    analytics_router,
    auth_router,
    build_router,
    calibration_router,
    config_router,
    experiments_router,
    hardware_router,
    inference_router,
    operate_router,
    platform_router,
    profiles_router,
    recording_router,
    startup_router,
    storage_router,
    stream_router,
    system_router,
    teleop_router,
    training_router,
    user_router,
    webui_blueprints_router,
)
from interfaces_backend.services.lerobot_runtime import start_lerobot
from interfaces_backend.core.request_auth import (
    build_session_from_request,
    is_session_expired,
    refresh_session_from_request,
    set_session_cookies,
)
from interfaces_backend.services.vlabor_runtime import start_vlabor_on_backend_startup
from interfaces_backend.services.vlabor_profiles import get_active_profile_spec
from percus_ai.observability import (
    ArmId,
    CommOverheadReporter,
    PointId,
    new_trace_id,
    reset_session_id,
    reset_trace_id,
    set_session_id,
    set_trace_id,
)
from percus_ai.db import reset_request_session, set_request_session

app = FastAPI(
    title="Physical AI API",
    version="0.1.0",
)
SLOW_REQUEST_THRESHOLD_MS = int(os.environ.get("PHI_SLOW_REQUEST_THRESHOLD_MS", "1000"))
_COMM_REPORTER = CommOverheadReporter("backend")


@app.on_event("startup")
async def start_vlabor_container() -> None:
    startup_logger = logging.getLogger("interfaces_backend.startup")
    try:
        active_profile = await get_active_profile_spec()
        profile_name = active_profile.name
    except Exception:
        startup_logger.warning("Could not resolve active profile; starting VLAbor without profile")
        profile_name = None
    start_vlabor_on_backend_startup(profile=profile_name, logger=startup_logger)
    lerobot_result = start_lerobot(strict=False)
    if lerobot_result.returncode != 0:
        detail = (lerobot_result.stderr or lerobot_result.stdout).strip()
        startup_logger.warning("Failed to start lerobot stack on backend startup: %s", detail)
    else:
        startup_logger.info("lerobot stack started on backend startup")


def _extract_request_session_id(request: Request) -> Optional[str]:
    header = (request.headers.get("x-session-id") or "").strip()
    if header:
        return header
    query = (request.query_params.get("session_id") or "").strip()
    if query:
        return query
    path_parts = [part for part in request.url.path.split("/") if part]
    if "sessions" in path_parts:
        index = path_parts.index("sessions")
        if index + 1 < len(path_parts):
            candidate = path_parts[index + 1].strip()
            if candidate:
                return candidate
    return None

# CORS for web/tauri clients
cors_origins = os.environ.get(
    "PHI_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
)
allowed_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_comm_cp01(request: Request, call_next):
    path = request.url.path
    method = request.method
    target = (
        path == "/api/recording"
        or path.startswith("/api/recording/")
        or path == "/api/inference"
        or path.startswith("/api/inference/")
        or path == "/api/profiles"
        or path.startswith("/api/profiles/")
    )
    if not target:
        return await call_next(request)

    trace_id = (request.headers.get("x-trace-id") or "").strip() or new_trace_id()
    session_id = _extract_request_session_id(request) or "unknown-session"
    request.state.trace_id = trace_id
    request.state.session_id = session_id

    trace_token = set_trace_id(trace_id)
    session_token = set_session_id(session_id)
    timer = _COMM_REPORTER.timed(
        point_id=PointId.CP_01,
        session_id=session_id,
        trace_id=trace_id,
        arm=ArmId.NONE,
        tags={"path": path, "method": method},
    )
    try:
        response = await call_next(request)
        timer.success(extra_tags={"status_code": response.status_code})
        response.headers["x-trace-id"] = trace_id
        return response
    except Exception as exc:
        timer.error(str(exc))
        raise
    finally:
        reset_session_id(session_token)
        reset_trace_id(trace_token)


@app.middleware("http")
async def log_slow_requests(request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
            logging.getLogger("interfaces_backend.performance").warning(
                "Slow request %s %s (exception) %.1fms",
                request.method,
                request.url.path,
                duration_ms,
            )
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
        logging.getLogger("interfaces_backend.performance").warning(
            "Slow request %s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


@app.middleware("http")
async def attach_supabase_session(request, call_next):
    session = build_session_from_request(request)
    session_refreshed = False
    if session and is_session_expired(session):
        refreshed_session = refresh_session_from_request(request)
        if refreshed_session:
            session = refreshed_session
            session_refreshed = True
        else:
            session = None
    token = set_request_session(session)
    try:
        response = await call_next(request)
    finally:
        reset_request_session(token)
    if session_refreshed and session:
        set_session_cookies(response, session)
    return response

# Include API routers
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(build_router)
app.include_router(calibration_router)
app.include_router(config_router)
app.include_router(experiments_router)
app.include_router(hardware_router)
app.include_router(inference_router)
app.include_router(operate_router)
app.include_router(platform_router)
app.include_router(profiles_router)
app.include_router(recording_router)
app.include_router(startup_router)
app.include_router(storage_router)
app.include_router(stream_router)
app.include_router(system_router)
app.include_router(teleop_router)
app.include_router(training_router)
app.include_router(user_router)
app.include_router(webui_blueprints_router)


# --- Health ---


@app.get("/health")
async def health():
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Physical AI Backend Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    uvicorn.run(
        "interfaces_backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,  # Use our logging config instead of uvicorn's default
    )


if __name__ == "__main__":
    main()
