"""Build API router for bundled-torch building."""

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from interfaces_backend.models.build import BundledTorchStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/build", tags=["build"])

# Thread pool for running build operations
_executor = ThreadPoolExecutor(max_workers=1)


def _get_torch_builder():
    """Import TorchBuilder if available."""
    try:
        from percus_ai.environment import TorchBuilder

        return TorchBuilder
    except ImportError:
        # Try adding features path
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.environment import TorchBuilder

                return TorchBuilder
            except ImportError:
                pass
    return None


def _get_platform():
    """Import Platform if available."""
    try:
        from percus_ai.environment import Platform

        return Platform.detect()
    except ImportError:
        features_path = Path(__file__).resolve().parents[5] / "features"
        if features_path.exists() and str(features_path) not in sys.path:
            sys.path.insert(0, str(features_path))
            try:
                from percus_ai.environment import Platform

                return Platform.detect()
            except ImportError:
                pass
    return None


@router.get("/bundled-torch/status", response_model=BundledTorchStatusResponse)
async def get_bundled_torch_status():
    """Get current bundled-torch status.

    Returns information about the current bundled-torch installation,
    including whether it exists, versions, and validity.
    """
    TorchBuilder = _get_torch_builder()
    platform = _get_platform()

    is_jetson = platform.is_jetson if platform else False

    if TorchBuilder is None:
        return BundledTorchStatusResponse(
            exists=False,
            is_jetson=is_jetson,
        )

    builder = TorchBuilder()
    status = builder.get_status()

    return BundledTorchStatusResponse(
        exists=status.exists,
        pytorch_version=status.pytorch_version,
        torchvision_version=status.torchvision_version,
        pytorch_path=status.pytorch_path,
        torchvision_path=status.torchvision_path,
        is_valid=status.is_valid,
        is_jetson=is_jetson,
    )


@router.websocket("/ws/bundled-torch")
async def websocket_bundled_torch_build(websocket: WebSocket):
    """WebSocket endpoint for bundled-torch building with real-time progress.

    Client sends JSON messages:
    - {"action": "build", "pytorch_version": "v2.1.0", "torchvision_version": "v0.16.0"}
    - {"action": "status"} - Get current status
    - {"action": "clean"} - Remove bundled-torch

    Server sends progress updates:
    - {"type": "start", "step": "clone_pytorch", "message": "..."}
    - {"type": "progress", "step": "...", "percent": 45, "message": "..."}
    - {"type": "step_complete", "step": "...", "message": "..."}
    - {"type": "log", "step": "...", "line": "..."}
    - {"type": "complete", "output_path": "...", "message": "..."}
    - {"type": "error", "error": "..."}
    """
    await websocket.accept()

    try:
        while True:
            # Wait for request
            data = await websocket.receive_json()

            action = data.get("action")

            if action == "status":
                # Return current status
                TorchBuilder = _get_torch_builder()
                platform = _get_platform()

                if TorchBuilder is None:
                    await websocket.send_json({
                        "type": "status",
                        "exists": False,
                        "is_jetson": platform.is_jetson if platform else False,
                    })
                    continue

                builder = TorchBuilder()
                status = builder.get_status()
                await websocket.send_json({
                    "type": "status",
                    **status.to_dict(),
                    "is_jetson": platform.is_jetson if platform else False,
                })
                continue

            elif action == "clean":
                # Clean bundled-torch
                TorchBuilder = _get_torch_builder()
                if TorchBuilder is None:
                    await websocket.send_json({
                        "type": "error",
                        "error": "TorchBuilder not available",
                    })
                    continue

                builder = TorchBuilder()

                async def send_progress(msg: dict):
                    await websocket.send_json(msg)

                # Run clean in executor
                loop = asyncio.get_event_loop()
                progress_queue: asyncio.Queue = asyncio.Queue()
                main_loop = asyncio.get_running_loop()

                def progress_callback(progress: dict):
                    asyncio.run_coroutine_threadsafe(
                        progress_queue.put(progress),
                        main_loop
                    )

                async def run_clean():
                    try:
                        await loop.run_in_executor(
                            _executor,
                            lambda: builder.clean(callback=progress_callback)
                        )
                    except Exception as e:
                        await progress_queue.put({
                            "type": "error",
                            "error": str(e),
                        })

                clean_task = asyncio.create_task(run_clean())

                try:
                    while True:
                        try:
                            progress = await asyncio.wait_for(
                                progress_queue.get(), timeout=1.0
                            )
                            await websocket.send_json(progress)

                            if progress.get("type") in ("complete", "error"):
                                break
                        except asyncio.TimeoutError:
                            if clean_task.done():
                                break
                except Exception as e:
                    logger.error(f"Error during clean: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error": str(e),
                    })
                continue

            elif action == "build":
                # Check if Jetson
                platform = _get_platform()
                if platform and not platform.is_jetson:
                    await websocket.send_json({
                        "type": "error",
                        "error": "Bundled-torch build is only supported on Jetson. "
                                 "On other platforms, use pip install torch.",
                    })
                    continue

                TorchBuilder = _get_torch_builder()
                if TorchBuilder is None:
                    await websocket.send_json({
                        "type": "error",
                        "error": "TorchBuilder not available. "
                                 "Make sure percus_ai is installed.",
                    })
                    continue

                pytorch_version = data.get("pytorch_version")
                torchvision_version = data.get("torchvision_version")

                builder = TorchBuilder()

                # Queue for progress updates from thread
                progress_queue: asyncio.Queue = asyncio.Queue()
                main_loop = asyncio.get_running_loop()

                def progress_callback(progress: dict):
                    """Callback to put progress in queue (called from thread)."""
                    asyncio.run_coroutine_threadsafe(
                        progress_queue.put(progress),
                        main_loop
                    )

                async def run_build():
                    """Run build in thread pool."""
                    loop = asyncio.get_event_loop()

                    try:
                        await loop.run_in_executor(
                            _executor,
                            lambda: builder.build_all(
                                pytorch_version=pytorch_version,
                                torchvision_version=torchvision_version,
                                callback=progress_callback,
                            )
                        )
                    except Exception as e:
                        logger.error(f"Build failed: {e}")
                        await progress_queue.put({
                            "type": "error",
                            "error": str(e),
                        })

                # Start build task
                build_task = asyncio.create_task(run_build())

                # Forward progress updates to WebSocket
                try:
                    while True:
                        try:
                            progress = await asyncio.wait_for(
                                progress_queue.get(), timeout=1.0
                            )
                            await websocket.send_json(progress)

                            if progress.get("type") in ("complete", "error"):
                                break
                        except asyncio.TimeoutError:
                            if build_task.done():
                                # Check for any remaining items in queue
                                while not progress_queue.empty():
                                    progress = await progress_queue.get()
                                    await websocket.send_json(progress)
                                break
                except Exception as e:
                    logger.error(f"Error forwarding progress: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error": str(e),
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "error": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
            })
        except Exception:
            pass
