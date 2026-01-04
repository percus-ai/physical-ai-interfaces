"""FastAPI server entrypoint."""

import argparse

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from interfaces_backend.api import (
    analytics_router,
    calibration_router,
    config_router,
    hardware_router,
    inference_router,
    platform_router,
    project_router,
    recording_router,
    storage_router,
    system_router,
    teleop_router,
    training_router,
    user_router,
)

app = FastAPI(
    title="Physical AI API",
    version="0.1.0",
)

# CORS for web/tauri clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(analytics_router)
app.include_router(calibration_router)
app.include_router(config_router)
app.include_router(hardware_router)
app.include_router(inference_router)
app.include_router(platform_router)
app.include_router(project_router)
app.include_router(recording_router)
app.include_router(storage_router)
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
    )


if __name__ == "__main__":
    main()
