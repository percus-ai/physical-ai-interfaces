"""Inference session manager."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import HTTPException

from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle, get_dataset_lifecycle
from interfaces_backend.services.inference_runtime import (
    InferenceRuntimeManager,
    get_inference_runtime_manager,
)
from interfaces_backend.services.recorder_bridge import RecorderBridge, get_recorder_bridge
from interfaces_backend.services.session_manager import BaseSessionManager, SessionState
from interfaces_backend.services.vlabor_profiles import (
    build_inference_camera_aliases,
    build_inference_joint_names,
    extract_arm_namespaces,
    save_session_profile_binding,
)
from percus_ai.storage.naming import generate_dataset_id

logger = logging.getLogger(__name__)


class InferenceSessionManager(BaseSessionManager):
    kind = "inference"

    def __init__(
        self,
        runtime: InferenceRuntimeManager | None = None,
        recorder: RecorderBridge | None = None,
        dataset: DatasetLifecycle | None = None,
    ) -> None:
        super().__init__()
        self._runtime = runtime or get_inference_runtime_manager()
        self._recorder = recorder or get_recorder_bridge()
        self._dataset = dataset or get_dataset_lifecycle()

    async def create(self, *, profile: str | None = None, **kwargs: Any) -> SessionState:
        state = await super().create(profile=profile, **kwargs)

        joint_names = build_inference_joint_names(state.profile.snapshot)
        if not joint_names:
            raise HTTPException(
                status_code=400,
                detail="No inference joints configured in active profile",
            )
        camera_key_aliases = build_inference_camera_aliases(state.profile.snapshot)

        # Download model from R2
        await self._dataset.ensure_model_local(kwargs["model_id"])

        # Start GPU worker
        try:
            worker_session_id = self._runtime.start(
                model_id=kwargs["model_id"],
                device=kwargs.get("device"),
                task=kwargs.get("task"),
                joint_names=joint_names,
                camera_key_aliases=camera_key_aliases,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            message = str(exc)
            if "already running" in message:
                raise HTTPException(status_code=409, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to start inference worker: {exc}"
            ) from exc

        state.extras["worker_session_id"] = worker_session_id
        state.extras["model_id"] = kwargs["model_id"]

        # Simultaneous recording (best-effort)
        self._start_simultaneous_recording(state, kwargs.get("task"))

        state.status = "running"
        return state

    async def stop(self, session_id: str, **kwargs: Any) -> SessionState:
        state = self._get_or_raise(session_id)
        worker_sid = state.extras.get("worker_session_id")

        # Stop worker
        try:
            stopped = self._runtime.stop(session_id=worker_sid or kwargs.get("session_id"))
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to stop inference worker: {exc}"
            ) from exc

        state.extras["stopped"] = stopped

        # Stop simultaneous recording and upload
        dataset_id = state.extras.get("dataset_id")
        if dataset_id:
            recording_stopped = False
            try:
                self._recorder.stop(save_current=True)
                logger.info("Stopped inference recording: dataset_id=%s", dataset_id)
                recording_stopped = True
            except Exception:
                logger.warning("Failed to stop inference recording", exc_info=True)
            if recording_stopped:
                try:
                    await self._dataset.mark_active(dataset_id)
                except Exception:
                    logger.warning(
                        "Failed to mark dataset active: dataset_id=%s",
                        dataset_id,
                        exc_info=True,
                    )
            await self._dataset.auto_upload(dataset_id)

        return await super().stop(session_id, **kwargs)

    def _start_simultaneous_recording(
        self, state: SessionState, task: str | None
    ) -> None:
        """Start recording during inference (best-effort)."""
        try:
            dataset_id = generate_dataset_id()
            cameras = self._recorder.build_cameras(state.profile.snapshot)
            arm_namespaces = extract_arm_namespaces(state.profile.snapshot)

            payload: dict[str, Any] = {
                "dataset_id": dataset_id,
                "dataset_name": f"eval-{state.id[:8]}",
                "task": task or "",
                "num_episodes": 1,
                "episode_time_s": 86400,
                "reset_time_s": 0,
                "cameras": cameras,
                "metadata": {
                    "profile_name": state.profile.name,
                    "profile_snapshot": state.profile.snapshot,
                    "session_kind": "inference",
                    "inference_session_id": state.id,
                },
            }
            if arm_namespaces:
                payload["arm_namespaces"] = arm_namespaces

            result = self._recorder.start(payload)
            if result.get("success"):
                state.extras["dataset_id"] = dataset_id
                logger.info("Started inference recording: dataset_id=%s", dataset_id)
                try:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    loop.create_task(self._persist_recording_metadata(state, dataset_id, task))
                except Exception:
                    logger.warning(
                        "Failed to persist inference dataset metadata", exc_info=True
                    )
            else:
                logger.warning("Recorder start returned failure (non-critical): %s", result)
        except Exception:
            logger.warning("Failed to start simultaneous recording (non-critical)", exc_info=True)

    async def _persist_recording_metadata(
        self, state: SessionState, dataset_id: str, task: str | None
    ) -> None:
        """Persist dataset record and profile binding for the recording."""
        await self._dataset.upsert_record(
            dataset_id=dataset_id,
            dataset_name=f"eval-{state.id[:8]}",
            task=task or "",
            profile_snapshot=state.profile.snapshot,
            status="recording",
            dataset_type="eval",
        )
        await save_session_profile_binding(
            session_kind="recording",
            session_id=dataset_id,
            profile=state.profile,
        )


# -- singleton ----------------------------------------------------------------

_manager: InferenceSessionManager | None = None
_lock = threading.Lock()


def get_inference_session_manager() -> InferenceSessionManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = InferenceSessionManager()
    return _manager
