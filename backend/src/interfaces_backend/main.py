"""FastAPI server entrypoint."""

import argparse
import logging
import os
import time
from pathlib import Path

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

from interfaces_backend.api import (
    analytics_router,
    auth_router,
    build_router,
    calibration_router,
    config_router,
    experiments_router,
    hardware_router,
    inference_router,
    gpu_host_router,
    operate_router,
    platform_router,
    profiles_router,
    recording_router,
    storage_router,
    stream_router,
    system_router,
    teleop_router,
    training_router,
    user_router,
)
from interfaces_backend.core.request_auth import build_session_from_request, is_session_expired
from percus_ai.db import reset_request_session, set_request_session

app = FastAPI(
    title="Physical AI API",
    version="0.1.0",
)
SLOW_REQUEST_THRESHOLD_MS = int(os.environ.get("PHI_SLOW_REQUEST_THRESHOLD_MS", "1000"))

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
    if session and is_session_expired(session):
        session = None
    token = set_request_session(session)
    try:
        response = await call_next(request)
    finally:
        reset_request_session(token)
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
app.include_router(gpu_host_router)
app.include_router(operate_router)
app.include_router(platform_router)
app.include_router(profiles_router)
app.include_router(recording_router)
app.include_router(storage_router)
app.include_router(stream_router)
app.include_router(system_router)
app.include_router(teleop_router)
app.include_router(training_router)
app.include_router(user_router)


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
