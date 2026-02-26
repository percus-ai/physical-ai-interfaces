"""Inference session manager."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from fastapi import HTTPException

from interfaces_backend.models.inference import InferenceModelSyncStatus
from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle, get_dataset_lifecycle
from interfaces_backend.services.inference_recording_controller import (
    InferenceRecordingController,
)
from interfaces_backend.services.inference_runtime import (
    InferenceRuntimeManager,
    get_inference_runtime_manager,
)
from interfaces_backend.services.recording_session import (
    RecordingSessionManager,
    get_recording_session_manager,
)
from interfaces_backend.services.recorder_bridge import RecorderBridge, get_recorder_bridge
from interfaces_backend.services.session_manager import (
    BaseSessionManager,
    SessionProgressCallback,
    SessionState,
)
from interfaces_backend.services.vlabor_profiles import (
    build_inference_bridge_config,
    build_inference_camera_aliases,
    build_inference_joint_names,
    extract_arm_namespaces,
    extract_recorder_topic_suffixes,
)

logger = logging.getLogger(__name__)
_ACTIVE_RECORDER_STATES = {"warming", "recording", "paused", "resetting", "resetting_paused"}
_DEFAULT_EPISODE_TIME_S = 60.0
_DEFAULT_RESET_TIME_S = 10.0


class InferenceSessionManager(BaseSessionManager):
    kind = "inference"

    def __init__(
        self,
        runtime: InferenceRuntimeManager | None = None,
        recorder: RecorderBridge | None = None,
        dataset: DatasetLifecycle | None = None,
        recording_sessions: RecordingSessionManager | None = None,
    ) -> None:
        super().__init__()
        self._runtime = runtime or get_inference_runtime_manager()
        self._recorder = recorder or get_recorder_bridge()
        self._dataset = dataset or get_dataset_lifecycle()
        self._recording_sessions = recording_sessions or get_recording_session_manager()
        self._recording_controller = InferenceRecordingController(
            recorder=self._recorder,
            dataset=self._dataset,
            runtime=self._runtime,
        )

    def _drop_session_state(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _cleanup_failed_create(self, *, session_id: str, worker_session_id: str) -> None:
        if worker_session_id:
            try:
                self._runtime.stop(session_id=worker_session_id)
            except Exception:
                logger.warning(
                    "Failed to stop worker during create cleanup: session_id=%s worker_session_id=%s",
                    session_id,
                    worker_session_id,
                    exc_info=True,
                )
        self._drop_session_state(session_id)

    def any_active(self) -> SessionState | None:
        # Prefer the most recent active state that has a worker session.
        # This avoids selecting stale "created" entries left by past startup failures.
        with self._lock:
            active_states = [
                state for state in self._sessions.values() if state.status in ("created", "running")
            ]
        if not active_states:
            return None
        for state in reversed(active_states):
            if str(state.extras.get("worker_session_id") or "").strip():
                return state
        return active_states[-1]

    def _build_inference_recording_payload(
        self,
        *,
        dataset_id: str,
        state: SessionState,
        task: str,
        num_episodes: int,
        episode_time_s: float,
        reset_time_s: float,
    ) -> dict[str, Any]:
        profile_snapshot = state.profile.snapshot if state.profile else {}
        cameras = self._recorder.build_cameras(profile_snapshot)
        arm_namespaces = extract_arm_namespaces(profile_snapshot)
        topic_suffixes = extract_recorder_topic_suffixes(
            profile_snapshot,
            arm_namespaces=arm_namespaces,
        )
        payload: dict[str, Any] = {
            "dataset_id": dataset_id,
            "dataset_name": f"eval-{state.id[:8]}",
            "task": task,
            "num_episodes": max(int(num_episodes), 1),
            "episode_time_s": float(episode_time_s),
            "reset_time_s": float(reset_time_s),
            "cameras": cameras,
            "metadata": {
                "session_kind": "inference",
                "inference_session_id": state.id,
            },
        }
        if arm_namespaces:
            payload["arm_namespaces"] = arm_namespaces
        payload.update(topic_suffixes)
        return payload

    @staticmethod
    def _validate_inference_bridge_resolution(
        *,
        profile_name: str,
        profile_source: str,
        bridge_stream_config: dict[str, Any],
    ) -> None:
        errors: list[str] = []
        arm_namespaces = bridge_stream_config.get("arm_namespaces")
        state_topic_suffix = bridge_stream_config.get("state_topic_suffix")
        action_topic_suffix = bridge_stream_config.get("action_topic_suffix")
        camera_streams = bridge_stream_config.get("camera_streams")
        if not isinstance(arm_namespaces, list) or not arm_namespaces:
            errors.append(
                "no arm namespaces resolved (expected profile.lerobot.<arm>.namespace "
                "or profile.teleop.follower_arms[*].namespace)"
            )
        if not str(state_topic_suffix or "").strip():
            errors.append(
                "state_topic_suffix unresolved (expected profile.lerobot.<arm>.topic per target arm)"
            )
        if not str(action_topic_suffix or "").strip():
            errors.append(
                "action_topic_suffix unresolved (expected profile.lerobot.<arm>.action_topic "
                "or profile.teleop.topic_mappings[*].dst per target arm)"
            )
        if not isinstance(camera_streams, list) or not camera_streams:
            errors.append(
                "no enabled cameras resolved (expected profile.lerobot.cameras[*].topic)"
            )
        if not errors:
            return

        detail = (
            "Inference profile resolution failed. "
            f"profile={profile_name} source={profile_source}; "
            + "; ".join(errors)
        )
        raise HTTPException(status_code=400, detail=detail)

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
    def _is_recorder_active_for_dataset(
        cls,
        status: dict[str, Any] | None,
        dataset_id: str,
    ) -> bool:
        return (
            cls._recorder_state(status) in _ACTIVE_RECORDER_STATES
            and cls._recorder_dataset_id(status) == dataset_id
        )

    @staticmethod
    def _extract_denoising_steps(policy_options: Any) -> int | None:
        if not isinstance(policy_options, dict):
            return None
        for options in policy_options.values():
            if isinstance(options, dict) and options.get("denoising_steps") is not None:
                try:
                    return int(options.get("denoising_steps"))
                except (TypeError, ValueError):
                    return None
        return None

    def _register_inference_recording_session(
        self,
        *,
        state: SessionState,
        dataset_id: str,
        task_value: str,
        recording_status: dict[str, Any],
    ) -> None:
        self._recording_sessions.register_external_session(
            session_id=dataset_id,
            profile=state.profile,
            status="running",
            extras={
                "dataset_name": f"eval-{state.id[:8]}",
                "task": task_value,
                "target_total_episodes": int(recording_status.get("batch_size") or 20),
                "recording_started": True,
                "external_owner": "inference",
                "recorder_payload": self._build_inference_recording_payload(
                    dataset_id=dataset_id,
                    state=state,
                    task=task_value,
                    num_episodes=int(recording_status.get("batch_size") or 20),
                    episode_time_s=float(recording_status.get("episode_time_s") or _DEFAULT_EPISODE_TIME_S),
                    reset_time_s=float(recording_status.get("reset_time_s") or _DEFAULT_RESET_TIME_S),
                ),
            },
        )

    async def _start_recording_for_state(self, state: SessionState) -> None:
        worker_session_id = str(state.extras.get("worker_session_id") or "").strip()
        if not worker_session_id:
            raise HTTPException(status_code=400, detail="Active worker session not found")

        task_value = str(state.extras.get("task") or "").strip()
        denoising_steps = state.extras.get("denoising_steps")
        episode_time_s = float(state.extras.get("episode_time_s") or _DEFAULT_EPISODE_TIME_S)
        reset_time_s = float(state.extras.get("reset_time_s") or _DEFAULT_RESET_TIME_S)

        await self._recording_controller.start(
            session=state,
            task=task_value,
            denoising_steps=int(denoising_steps) if denoising_steps is not None else None,
            episode_time_s=episode_time_s,
            reset_time_s=reset_time_s,
        )
        dataset_id = str(state.extras.get("dataset_id") or "").strip()
        if not dataset_id:
            raise HTTPException(status_code=500, detail="Failed to prepare inference recording dataset")

        recording_status = self._recording_controller.get_status(state.id)
        self._register_inference_recording_session(
            state=state,
            dataset_id=dataset_id,
            task_value=task_value,
            recording_status=recording_status,
        )
        self._runtime.set_paused(session_id=worker_session_id, paused=False)
        state.extras["recording_started"] = True

    async def create(
        self,
        *,
        profile: str | None = None,
        progress_callback: SessionProgressCallback | None = None,
        **kwargs: Any,
    ) -> SessionState:
        state = await super().create(
            profile=profile,
            progress_callback=progress_callback,
            **kwargs,
        )
        worker_session_id = ""
        try:
            joint_names = build_inference_joint_names(state.profile.snapshot)
            if not joint_names:
                raise HTTPException(
                    status_code=400,
                    detail="No inference joints configured in active profile",
                )
            camera_key_aliases = build_inference_camera_aliases(state.profile.snapshot)
            bridge_stream_config = build_inference_bridge_config(state.profile.snapshot)
            self._validate_inference_bridge_resolution(
                profile_name=state.profile.name,
                profile_source=getattr(state.profile, "source_path", "unknown"),
                bridge_stream_config=bridge_stream_config,
            )

            # Download model from R2
            self._emit_progress(
                progress_callback,
                phase="sync_model",
                progress_percent=56.0,
                message="モデル同期を開始します...",
            )

            def _on_model_sync(status: InferenceModelSyncStatus) -> None:
                if progress_callback is None:
                    return
                status_name = str(status.status or "").strip().lower()
                phase = "sync_model"
                detail = {
                    "files_done": status.files_done,
                    "total_files": status.total_files,
                    "transferred_bytes": status.transferred_bytes,
                    "total_bytes": status.total_bytes,
                    "current_file": status.current_file,
                }
                if status_name in {"checking", "syncing"}:
                    mapped_progress = 56.0 + (float(status.progress_percent or 0.0) * 0.26 / 100.0)
                    self._emit_progress(
                        progress_callback,
                        phase=phase,
                        progress_percent=mapped_progress,
                        message=status.message or "モデルを同期中です...",
                        detail=detail,
                    )
                    return
                if status_name == "completed":
                    self._emit_progress(
                        progress_callback,
                        phase=phase,
                        progress_percent=82.0,
                        message=status.message or "モデル同期が完了しました。",
                        detail=detail,
                    )
                    return
                if status_name == "error":
                    detail["error"] = status.error
                    self._emit_progress(
                        progress_callback,
                        phase=phase,
                        progress_percent=82.0,
                        message=status.message or "モデル同期に失敗しました。",
                        detail=detail,
                    )

            await self._dataset.ensure_model_local(
                kwargs["model_id"],
                sync_status_callback=_on_model_sync,
            )

            # Start GPU worker
            self._emit_progress(
                progress_callback,
                phase="launch_worker",
                progress_percent=86.0,
                message="推論ワーカーを起動しています...",
            )
            try:
                worker_session_id = self._runtime.start(
                    model_id=kwargs["model_id"],
                    device=kwargs.get("device"),
                    task=kwargs.get("task"),
                    policy_options=kwargs.get("policy_options"),
                    joint_names=joint_names,
                    camera_key_aliases=camera_key_aliases,
                    bridge_stream_config=bridge_stream_config,
                    progress_callback=progress_callback,
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
            state.extras["bridge_stream_config"] = bridge_stream_config
            state.extras["task"] = str(kwargs.get("task") or "").strip()
            state.extras["episode_time_s"] = _DEFAULT_EPISODE_TIME_S
            state.extras["reset_time_s"] = _DEFAULT_RESET_TIME_S
            state.extras["denoising_steps"] = self._extract_denoising_steps(kwargs.get("policy_options"))
            state.extras["recording_started"] = False

            # Keep inference paused until the operator explicitly starts from ControlsView.
            self._emit_progress(
                progress_callback,
                phase="persist",
                progress_percent=96.0,
                message="推論セッション情報を保存しています...",
            )
            try:
                self._runtime.set_paused(session_id=worker_session_id, paused=True)
            except RuntimeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"Failed to pause inference worker: {exc}"
                ) from exc
            return state
        except Exception:
            self._cleanup_failed_create(session_id=state.id, worker_session_id=worker_session_id)
            raise

    async def start(self, session_id: str, **kwargs: Any) -> SessionState:
        state = self._get_or_raise(session_id)
        if not bool(state.extras.get("recording_started")):
            await self._start_recording_for_state(state)
        return await super().start(session_id, **kwargs)

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
            recorder_result: dict[str, Any] | None = None
            try:
                recorder_result = self._recorder.stop(save_current=True)
                if recorder_result.get("success", False):
                    final_status = await asyncio.to_thread(
                        self._recorder.wait_until_finalized,
                        dataset_id,
                    )
                    if self._is_recorder_active_for_dataset(final_status, dataset_id):
                        logger.warning(
                            "Inference recording stop timed out before finalize: "
                            "dataset_id=%s state=%s",
                            dataset_id,
                            self._recorder_state(final_status),
                        )
                    else:
                        logger.info("Stopped inference recording: dataset_id=%s", dataset_id)
                        recording_stopped = True
                else:
                    logger.warning(
                        "Failed to stop inference recording: dataset_id=%s result=%s",
                        dataset_id,
                        recorder_result,
                    )
            except HTTPException as exc:
                if exc.status_code == 503:
                    final_status = await asyncio.to_thread(
                        self._recorder.wait_until_finalized,
                        dataset_id,
                    )
                    if not self._is_recorder_active_for_dataset(final_status, dataset_id):
                        logger.info(
                            "Recorder stop request timed out but session is already inactive: "
                            "dataset_id=%s",
                            dataset_id,
                        )
                        recording_stopped = True
                    else:
                        logger.warning(
                            "Recorder stop request timed out and session may still be active: "
                            "dataset_id=%s state=%s",
                            dataset_id,
                            self._recorder_state(final_status),
                        )
                else:
                    logger.warning(
                        "Failed to stop inference recording: dataset_id=%s detail=%s",
                        dataset_id,
                        exc.detail,
                    )
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
            self._recording_sessions.unregister_external_session(str(dataset_id))
        self._recording_controller.unregister(session_id)
        return await super().stop(session_id, **kwargs)

    def get_active_recording_status(self) -> dict:
        active = self.any_active()
        if active is None:
            return self._recording_controller.get_status("")
        status = self._recording_controller.get_status(active.id)
        if bool(active.extras.get("recording_started")):
            return status
        status["episode_time_s"] = float(active.extras.get("episode_time_s") or _DEFAULT_EPISODE_TIME_S)
        status["reset_time_s"] = float(active.extras.get("reset_time_s") or _DEFAULT_RESET_TIME_S)
        status["denoising_steps"] = active.extras.get("denoising_steps")
        return status

    async def apply_active_settings(
        self,
        *,
        task: str | None,
        episode_time_s: float | None,
        reset_time_s: float | None,
        denoising_steps: int | None,
    ) -> dict:
        active = self.any_active()
        if active is None:
            raise HTTPException(status_code=404, detail="Active inference session not found")
        worker_session_id = str(active.extras.get("worker_session_id") or "").strip()
        if not worker_session_id:
            raise HTTPException(status_code=400, detail="Active worker session not found")
        if not bool(active.extras.get("recording_started")):
            next_task = str(active.extras.get("task") or "").strip()
            next_episode_time_s = float(active.extras.get("episode_time_s") or _DEFAULT_EPISODE_TIME_S)
            next_reset_time_s = float(active.extras.get("reset_time_s") or _DEFAULT_RESET_TIME_S)
            next_denoising_steps = active.extras.get("denoising_steps")

            if task is not None:
                normalized_task = task.strip()
                if not normalized_task:
                    raise HTTPException(status_code=400, detail="task must not be empty")
                self._runtime.set_task(session_id=worker_session_id, task=normalized_task)
                next_task = normalized_task
            if episode_time_s is not None:
                if episode_time_s <= 0:
                    raise HTTPException(status_code=400, detail="episode_time_s must be > 0")
                next_episode_time_s = float(episode_time_s)
            if reset_time_s is not None:
                if reset_time_s < 0:
                    raise HTTPException(status_code=400, detail="reset_time_s must be >= 0")
                next_reset_time_s = float(reset_time_s)
            if denoising_steps is not None:
                self._runtime.set_policy_options(
                    session_id=worker_session_id,
                    denoising_steps=int(denoising_steps),
                )
                next_denoising_steps = int(denoising_steps)

            active.extras["task"] = next_task
            active.extras["episode_time_s"] = next_episode_time_s
            active.extras["reset_time_s"] = next_reset_time_s
            active.extras["denoising_steps"] = next_denoising_steps
            return {
                "task": next_task,
                "episode_time_s": next_episode_time_s,
                "reset_time_s": next_reset_time_s,
                "denoising_steps": next_denoising_steps,
            }

        applied = await self._recording_controller.apply_settings(
            inference_session_id=active.id,
            worker_session_id=worker_session_id,
            task=task,
            episode_time_s=episode_time_s,
            reset_time_s=reset_time_s,
            denoising_steps=denoising_steps,
        )
        active.extras["task"] = str(applied.get("task") or "").strip()
        active.extras["episode_time_s"] = float(applied.get("episode_time_s") or _DEFAULT_EPISODE_TIME_S)
        active.extras["reset_time_s"] = float(applied.get("reset_time_s") or _DEFAULT_RESET_TIME_S)
        active.extras["denoising_steps"] = applied.get("denoising_steps")
        return applied

    async def decide_active_recording_continue(
        self, *, continue_recording: bool
    ) -> dict:
        active = self.any_active()
        if active is None:
            raise HTTPException(status_code=404, detail="Active inference session not found")
        if not bool(active.extras.get("recording_started")):
            raise HTTPException(status_code=409, detail="Inference session has not started yet")
        return await self._recording_controller.decide_continue(
            inference_session_id=active.id,
            continue_recording=continue_recording,
        )

    async def pause_active_recording_and_inference(self) -> dict:
        active = self.any_active()
        if active is None:
            raise HTTPException(status_code=404, detail="Active inference session not found")
        if not bool(active.extras.get("recording_started")):
            raise HTTPException(status_code=409, detail="Inference session has not started yet")
        return await self._recording_controller.set_manual_pause(
            inference_session_id=active.id,
            paused=True,
        )

    async def resume_active_recording_and_inference(self) -> dict:
        active = self.any_active()
        if active is None:
            raise HTTPException(status_code=404, detail="Active inference session not found")
        if not bool(active.extras.get("recording_started")):
            await self.start(active.id)
            return {
                "paused": False,
                "teleop_enabled": False,
                "recorder_state": "warming",
                "started": True,
            }
        return await self._recording_controller.set_manual_pause(
            inference_session_id=active.id,
            paused=False,
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
