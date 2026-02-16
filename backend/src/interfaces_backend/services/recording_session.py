"""Recording session manager."""

from __future__ import annotations

import asyncio
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
        self._completion_watchers: dict[str, asyncio.Task[None]] = {}

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
        self._start_completion_watcher(state.id)
        return state

    async def stop(self, session_id: str, **kwargs: Any) -> SessionState:
        state = self._get_or_raise(session_id)
        self._cancel_completion_watcher(session_id)
        save_current = kwargs.get("save_current", True)
        cancel = kwargs.get("cancel", False)

        recorder_result: dict = {}
        if state.extras.get("recording_started"):
            recorder_status = kwargs.get("recorder_status")
            if recorder_status is None:
                try:
                    recorder_status = self._recorder.status()
                except HTTPException as exc:
                    if exc.status_code != 503:
                        raise
                    recorder_status = None

            if recorder_status is None:
                recorder_result = self._recorder.stop(save_current=save_current)
                if not cancel and not recorder_result.get("success", False):
                    raise HTTPException(
                        status_code=500,
                        detail=recorder_result.get("error") or "Recorder stop failed",
                    )
            else:
                recorder_state = str(recorder_status.get("state") or "").strip().lower()
                recorder_dataset_id = str(recorder_status.get("dataset_id") or "").strip()
                recorder_active = recorder_dataset_id == state.id and recorder_state in {
                    "warming",
                    "recording",
                    "paused",
                    "resetting",
                }
                if recorder_active:
                    recorder_result = self._recorder.stop(save_current=save_current)
                    if not cancel and not recorder_result.get("success", False):
                        raise HTTPException(
                            status_code=500,
                            detail=recorder_result.get("error") or "Recorder stop failed",
                        )
                else:
                    recorder_result = {
                        "success": True,
                        "message": "Recorder already finalized",
                        "status": recorder_status,
                    }

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

    def _start_completion_watcher(self, session_id: str) -> None:
        task = self._completion_watchers.get(session_id)
        if task is not None and not task.done():
            return
        self._completion_watchers[session_id] = asyncio.create_task(
            self._watch_completion(session_id)
        )

    def _cancel_completion_watcher(self, session_id: str) -> None:
        task = self._completion_watchers.get(session_id)
        if task is None:
            return
        current = asyncio.current_task()
        if task is current:
            return
        if not task.done():
            task.cancel()
        self._completion_watchers.pop(session_id, None)

    async def _watch_completion(self, session_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(2.0)
                if self.status(session_id) is None:
                    return
                try:
                    recorder_status = await asyncio.to_thread(self._recorder.status)
                except HTTPException as exc:
                    if exc.status_code == 503:
                        continue
                    logger.warning(
                        "recording session %s completion watcher error: %s",
                        session_id,
                        exc.detail,
                    )
                    continue

                recorder_state = str(recorder_status.get("state") or "").strip().lower()
                recorder_dataset_id = str(recorder_status.get("dataset_id") or "").strip()
                if recorder_state != "completed" or recorder_dataset_id != session_id:
                    continue

                logger.info("recording session %s completed; finalizing upload", session_id)
                try:
                    await self.stop(
                        session_id,
                        save_current=False,
                        recorder_status=recorder_status,
                    )
                except HTTPException as exc:
                    if exc.status_code != 404:
                        logger.error(
                            "recording session %s auto-finalize failed: %s",
                            session_id,
                            exc.detail,
                        )
                return
        except asyncio.CancelledError:
            return
        finally:
            task = self._completion_watchers.get(session_id)
            if task is asyncio.current_task():
                self._completion_watchers.pop(session_id, None)


# -- singleton ----------------------------------------------------------------

_manager: RecordingSessionManager | None = None
_lock = threading.Lock()


def get_recording_session_manager() -> RecordingSessionManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = RecordingSessionManager()
    return _manager
