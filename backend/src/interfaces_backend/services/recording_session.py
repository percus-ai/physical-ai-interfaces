"""Recording session manager."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle, get_dataset_lifecycle
from interfaces_backend.services.recorder_bridge import RecorderBridge, get_recorder_bridge
from interfaces_backend.services.session_manager import (
    BaseSessionManager,
    SessionProgressCallback,
    SessionState,
)
from interfaces_backend.services.vlabor_profiles import (
    extract_arm_namespaces,
    extract_recorder_topic_suffixes,
)
from percus_ai.storage.naming import generate_dataset_id

logger = logging.getLogger(__name__)
_ACTIVE_RECORDER_STATES = {"warming", "recording", "paused", "resetting", "resetting_paused"}


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

    def register_external_session(
        self,
        *,
        session_id: str,
        profile,
        status: str = "running",
        extras: dict[str, Any] | None = None,
    ) -> SessionState:
        """Register or update an externally managed recording session.

        Used by inference session flow so recording session state is visible
        through the same manager namespace.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                existing.status = status
                if profile is not None:
                    existing.profile = profile
                if status in {"running", "paused"} and not existing.started_at:
                    existing.started_at = now_iso
                if extras:
                    existing.extras.update(extras)
                return existing

            state = SessionState(
                id=session_id,
                kind=self.kind,
                status=status,
                profile=profile,
                created_at=now_iso,
                started_at=now_iso if status in {"running", "paused"} else None,
                extras=dict(extras or {}),
            )
            self._sessions[session_id] = state
            return state

    def unregister_external_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    @staticmethod
    def _validate_recorder_resolution(
        *,
        profile_name: str,
        profile_source: str,
        cameras: list[dict[str, Any]],
        arm_namespaces: list[str],
        topic_suffixes: dict[str, str],
    ) -> None:
        errors: list[str] = []
        if not cameras:
            errors.append(
                "no enabled cameras resolved (expected profile.lerobot.cameras[*].topic)"
            )
        if not arm_namespaces:
            errors.append(
                "no arm namespaces resolved (expected profile.lerobot.<arm>.namespace "
                "or profile.teleop.follower_arms[*].namespace)"
            )
        if "state_topic_suffix" not in topic_suffixes:
            errors.append(
                "state_topic_suffix unresolved (expected profile.lerobot.<arm>.topic per target arm)"
            )
        if "action_topic_suffix" not in topic_suffixes:
            errors.append(
                "action_topic_suffix unresolved (expected profile.lerobot.<arm>.action_topic "
                "or profile.teleop.topic_mappings[*].dst per target arm)"
            )
        if not errors:
            return

        detail = (
            "Recorder profile resolution failed. "
            f"profile={profile_name} source={profile_source}; "
            + "; ".join(errors)
        )
        raise HTTPException(status_code=400, detail=detail)

    async def create(
        self,
        *,
        session_id: str | None = None,
        profile: str | None = None,
        progress_callback: SessionProgressCallback | None = None,
        **kwargs: Any,
    ) -> SessionState:
        state = await super().create(
            session_id=session_id,
            profile=profile,
            progress_callback=progress_callback,
            **kwargs,
        )
        self._emit_progress(
            progress_callback,
            phase="prepare_recorder",
            progress_percent=70.0,
            message="録画ペイロードを組み立てています...",
        )

        cameras = self._recorder.build_cameras(state.profile.snapshot)
        arm_namespaces = extract_arm_namespaces(state.profile.snapshot)
        topic_suffixes = extract_recorder_topic_suffixes(
            state.profile.snapshot,
            arm_namespaces=arm_namespaces,
        )
        self._validate_recorder_resolution(
            profile_name=state.profile.name,
            profile_source=getattr(state.profile, "source_path", "unknown"),
            cameras=cameras,
            arm_namespaces=arm_namespaces,
            topic_suffixes=topic_suffixes,
        )

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
                "target_total_episodes": kwargs["target_total_episodes"],
                "episode_time_s": kwargs["episode_time_s"],
                "reset_time_s": kwargs["reset_time_s"],
                "profile_name": state.profile.name,
                "profile_snapshot": state.profile.snapshot,
            },
        }
        if arm_namespaces:
            recorder_payload["arm_namespaces"] = arm_namespaces
        recorder_payload.update(topic_suffixes)

        state.extras["dataset_name"] = kwargs["dataset_name"]
        state.extras["task"] = kwargs["task"]
        state.extras["target_total_episodes"] = kwargs["target_total_episodes"]
        state.extras["recorder_payload"] = recorder_payload

        await self._dataset.upsert_record(
            dataset_id=state.id,
            dataset_name=kwargs["dataset_name"],
            task=kwargs["task"],
            profile_snapshot=state.profile.snapshot,
            status="ready",
            target_total_episodes=kwargs["target_total_episodes"],
            episode_time_s=kwargs["episode_time_s"],
            reset_time_s=kwargs["reset_time_s"],
        )
        self._emit_progress(
            progress_callback,
            phase="persist",
            progress_percent=95.0,
            message="録画セッションを保存しました。",
        )
        return state

    async def start(self, session_id: str, **kwargs: Any) -> SessionState:
        state = await super().start(session_id, **kwargs)

        self._recorder.ensure_running()
        payload = state.extras["recorder_payload"]
        recorder_status: dict[str, Any] | None = None
        try:
            recorder_status = self._recorder.status()
        except HTTPException as exc:
            if exc.status_code != 503:
                raise

        if self._is_active_for_session(recorder_status, state.id):
            result = {
                "success": True,
                "message": "Recorder already active",
                "status": recorder_status,
            }
        elif self._is_active_for_other_session(recorder_status, state.id):
            active_dataset_id = str((recorder_status or {}).get("dataset_id") or "").strip()
            raise HTTPException(
                status_code=409,
                detail=f"Recorder already active for another session: {active_dataset_id}",
            )
        else:
            result = self._recorder.start(payload)
            if not result.get("success", False):
                if self._looks_like_already_active_error(result):
                    latest_status: dict[str, Any] | None = None
                    try:
                        latest_status = self._recorder.status()
                    except HTTPException as exc:
                        if exc.status_code != 503:
                            raise
                    if self._is_active_for_session(latest_status, state.id):
                        result = {
                            "success": True,
                            "message": "Recorder already active",
                            "status": latest_status,
                        }
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=result.get("error") or result.get("message") or "Recorder start failed",
                        )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=result.get("error") or result.get("message") or "Recorder start failed",
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

    @staticmethod
    def _recorder_state(status: dict[str, Any] | None) -> str:
        if not status:
            return ""
        return str(status.get("state") or "").strip().lower()

    @staticmethod
    def _recorder_dataset_id(status: dict[str, Any] | None) -> str:
        if not status:
            return ""
        return str(status.get("dataset_id") or "").strip()

    @classmethod
    def _is_active_for_session(cls, status: dict[str, Any] | None, session_id: str) -> bool:
        state = cls._recorder_state(status)
        dataset_id = cls._recorder_dataset_id(status)
        return state in _ACTIVE_RECORDER_STATES and dataset_id == session_id

    @classmethod
    def _is_active_for_other_session(cls, status: dict[str, Any] | None, session_id: str) -> bool:
        state = cls._recorder_state(status)
        dataset_id = cls._recorder_dataset_id(status)
        return state in _ACTIVE_RECORDER_STATES and bool(dataset_id) and dataset_id != session_id

    @staticmethod
    def _looks_like_already_active_error(result: dict[str, Any]) -> bool:
        message = str(result.get("message") or result.get("error") or "").strip().lower()
        return "already" in message and "active" in message

    async def stop(self, session_id: str, **kwargs: Any) -> SessionState:
        state = self._get_or_raise(session_id)
        self._cancel_completion_watcher(session_id)
        save_current = kwargs.get("save_current", True)
        cancel = kwargs.get("cancel", False)

        recorder_result: dict = {}
        stop_requested = False
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
                stop_requested = True
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
                    "resetting_paused",
                }
                if recorder_active:
                    recorder_result = self._recorder.stop(save_current=save_current)
                    stop_requested = True
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

        if stop_requested and recorder_result.get("success", False):
            final_status = await asyncio.to_thread(
                self._recorder.wait_until_finalized,
                state.id,
            )
            if final_status:
                recorder_result["status"] = final_status
                final_state = str(final_status.get("state") or "").strip().lower()
                final_dataset_id = str(final_status.get("dataset_id") or "").strip()
                if final_dataset_id == state.id and final_state in _ACTIVE_RECORDER_STATES:
                    detail = (
                        "Recorder stop timed out before finalize "
                        f"(state={final_state}, dataset_id={final_dataset_id})"
                    )
                    if not cancel:
                        raise HTTPException(status_code=500, detail=detail)
                    logger.warning(detail)

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
                except Exception as exc:  # noqa: BLE001 - keep watcher alive and logged
                    logger.exception(
                        "recording session %s auto-finalize crashed: %s",
                        session_id,
                        exc,
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
