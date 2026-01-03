"""FastAPI server entrypoint."""

import argparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="Percus Physical AI API",
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


# --- Health ---

@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Projects API (stub) ---

@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    return []


@app.post("/api/projects")
async def create_project(name: str, robot_type: str = "so101"):
    """Create a new project."""
    return {"id": "new-project-id", "name": name, "robot_type": robot_type}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project by ID."""
    return {"id": project_id, "name": "Example Project", "robot_type": "so101"}


# --- Datasets API (stub) ---

@app.get("/api/datasets")
async def list_datasets():
    """List all datasets."""
    return []


@app.get("/api/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """Get dataset by ID."""
    return {"id": dataset_id, "name": "Example Dataset", "episodes": 0}


# --- Training API (stub) ---

@app.post("/api/training/start")
async def start_training(project_id: str, policy: str = "act"):
    """Start a training job."""
    return {"job_id": "job-001", "status": "queued"}


@app.get("/api/training/status/{job_id}")
async def training_status(job_id: str):
    """Get training job status."""
    return {"job_id": job_id, "status": "running", "progress": 0}


# --- Hardware API (stub) ---

@app.get("/api/hardware/cameras")
async def list_cameras():
    """List connected cameras."""
    return []


# --- Config API ---

@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    return {"data_dir": "data/", "robot_type": "so101"}


def main():
    parser = argparse.ArgumentParser(description="Percus Backend Server")
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
