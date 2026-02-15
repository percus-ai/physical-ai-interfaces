"""Recording session manager."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import HTTPException

from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle, get_dataset_lifecycle
from interfaces_backend.services.recorder_bridge import RecorderBridge, get_recorder_bridge
from interfaces_backend.services.session_manager import BaseSessionManager, SessionState
from interfaces_backend.services.vlabor_profiles import extract_arm_namespaces
from percus_ai.storage.naming import generate_dataset_id

logger = logging.getLogger(__name__)


class RecordingSessionManager(BaseSessionManager):
    kind = "recording"

    def __init__(
        self,
        recorder: RecorderBridge | None = None,
        dataset: DatasetLifecycle | None = None,
    ) -> None:
        super().__init__()
        self._recorder = recorder or get_recorder_bridge()
        self._dataset = dataset or get_dataset_lifecycle()

    def _generate_id(self) -> str:
        # Use dataset_id as session_id so the client API can address
        # sessions by dataset_id directly.
        return generate_dataset_id()

    async def create(self, *, profile: str | None = None, **kwargs: Any) -> SessionState:
        state = await super().create(profile=profile, **kwargs)

        cameras = self._recorder.build_cameras(state.profile.snapshot)
        if not cameras:
            raise HTTPException(status_code=400, detail="No enabled cameras in active profile")

        arm_namespaces = extract_arm_namespaces(state.profile.snapshot)

        recorder_payload: dict[str, Any] = {
            "dataset_id": state.id,
            "dataset_name": kwargs["dataset_name"],
            "task": kwargs["task"],
            "num_episodes": kwargs["num_episodes"],
            "episode_time_s": kwargs["episode_time_s"],
            "reset_time_s": kwargs["reset_time_s"],
            "cameras": cameras,
            "metadata": {
                "num_episodes": kwargs["num_episodes"],
                "episode_time_s": kwargs["episode_time_s"],
                "reset_time_s": kwargs["reset_time_s"],
                "profile_name": state.profile.name,
                "profile_snapshot": state.profile.snapshot,
            },
        }
        if arm_namespaces:
            recorder_payload["arm_namespaces"] = arm_namespaces

        state.extras["dataset_name"] = kwargs["dataset_name"]
        state.extras["task"] = kwargs["task"]
        state.extras["recorder_payload"] = recorder_payload

        await self._dataset.upsert_record(
            dataset_id=state.id,
            dataset_name=kwargs["dataset_name"],
            task=kwargs["task"],
            profile_snapshot=state.profile.snapshot,
            status="ready",
        )
        return state

    async def start(self, session_id: str, **kwargs: Any) -> SessionState:
        state = await super().start(session_id, **kwargs)

        self._recorder.ensure_running()
        payload = state.extras["recorder_payload"]
        result = self._recorder.start(payload)
        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or "Recorder start failed",
            )

        await self._dataset.upsert_record(
            dataset_id=state.id,
            dataset_name=state.extras["dataset_name"],
            task=state.extras["task"],
            profile_snapshot=state.profile.snapshot,
            status="recording",
        )
        state.extras["recording_started"] = True
        state.extras["recorder_result"] = result
        return state

    async def stop(self, session_id: str, **kwargs: Any) -> SessionState:
        state = self._get_or_raise(session_id)
        save_current = kwargs.get("save_current", True)
        cancel = kwargs.get("cancel", False)

        recorder_result: dict = {}
        if state.extras.get("recording_started"):
            recorder_result = self._recorder.stop(save_current=save_current)
            if not cancel and not recorder_result.get("success", False):
                raise HTTPException(
                    status_code=500,
                    detail=recorder_result.get("error") or "Recorder stop failed",
                )

        if not cancel:
            await self._dataset.update_stats(state.id)
            await self._dataset.auto_upload(state.id)

        state.extras["recorder_result"] = recorder_result
        return await super().stop(session_id, **kwargs)

    async def pause(self, session_id: str) -> SessionState:
        state = self._get_or_raise(session_id)
        result = self._recorder.pause()
        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or "Recorder pause failed",
            )
        state.status = "paused"
        return state

    async def resume(self, session_id: str) -> SessionState:
        state = self._get_or_raise(session_id)
        result = self._recorder.resume()
        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=result.get("error") or "Recorder resume failed",
            )
        state.status = "running"
        return state


# -- singleton ----------------------------------------------------------------

_manager: RecordingSessionManager | None = None
_lock = threading.Lock()


def get_recording_session_manager() -> RecordingSessionManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = RecordingSessionManager()
    return _manager
