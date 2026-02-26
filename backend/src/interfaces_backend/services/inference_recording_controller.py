"""Inference-time recording controller.

Provides a dedicated control surface for inference recording:
- fixed-size episode batch recording
- continue/stop decisions after batch completion
- immediate settings apply
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

from fastapi import HTTPException

from interfaces_backend.services.dataset_lifecycle import DatasetLifecycle
from interfaces_backend.services.inference_runtime import InferenceRuntimeManager
from interfaces_backend.services.recorder_bridge import RecorderBridge
from interfaces_backend.services.session_manager import SessionState
from interfaces_backend.services.vlabor_dashboard_bridge import (
    VlaborDashboardBridge,
    get_vlabor_dashboard_bridge,
)
from interfaces_backend.services.vlabor_profiles import (
    extract_arm_namespaces,
    extract_recorder_topic_suffixes,
    save_session_profile_binding,
)
from percus_ai.storage.naming import generate_dataset_id

logger = logging.getLogger(__name__)

_ACTIVE_RECORDER_STATES = {"warming", "recording", "paused", "resetting", "resetting_paused"}


@dataclass
class InferenceRecordingState:
    inference_session_id: str
    worker_session_id: str
    dataset_id: str
    dataset_name: str
    profile_snapshot: dict
    task: str
    episode_time_s: float
    reset_time_s: float
    denoising_steps: int | None
    batch_size: int
    target_total_episodes: int
    cameras: list[dict]
    arm_namespaces: list[str]
    topic_suffixes: dict[str, str]
    awaiting_continue_confirmation: bool = False
    manual_paused: bool = False
    inference_paused: bool = False
    teleop_enabled: bool = False
    last_recorder_state: str = ""


class InferenceRecordingController:
    def __init__(
        self,
        *,
        recorder: RecorderBridge,
        dataset: DatasetLifecycle,
        runtime: InferenceRuntimeManager,
        dashboard: VlaborDashboardBridge | None = None,
        batch_size: int = 20,
        default_episode_time_s: float = 60.0,
        default_reset_time_s: float = 10.0,
    ) -> None:
        self._recorder = recorder
        self._dataset = dataset
        self._runtime = runtime
        self._dashboard = dashboard or get_vlabor_dashboard_bridge()
        self._batch_size = max(int(batch_size), 1)
        self._default_episode_time_s = max(float(default_episode_time_s), 1.0)
        self._default_reset_time_s = max(float(default_reset_time_s), 0.0)
        self._lock = threading.RLock()
        self._states: dict[str, InferenceRecordingState] = {}
        self._monitor_tasks: dict[str, asyncio.Task[None]] = {}

    def _get_state_or_raise(self, inference_session_id: str) -> InferenceRecordingState:
        with self._lock:
            state = self._states.get(inference_session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Inference recording state not found")
        return state

    def _upsert_state(self, state: InferenceRecordingState) -> None:
        with self._lock:
            self._states[state.inference_session_id] = state

    def _start_monitor_loop(self, inference_session_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        with self._lock:
            existing = self._monitor_tasks.get(inference_session_id)
            if existing and not existing.done():
                return
            task = loop.create_task(self._monitor_loop(inference_session_id))
            self._monitor_tasks[inference_session_id] = task

    def _cancel_monitor_loop(self, inference_session_id: str) -> None:
        with self._lock:
            task = self._monitor_tasks.pop(inference_session_id, None)
        if task is not None and not task.done():
            task.cancel()

    def unregister(self, inference_session_id: str) -> None:
        self._cancel_monitor_loop(inference_session_id)
        with self._lock:
            self._states.pop(inference_session_id, None)

    @staticmethod
    def _recorder_state(status: dict | None) -> str:
        if not isinstance(status, dict):
            return ""
        return str(status.get("state") or "").strip().lower()

    @staticmethod
    def _recorder_dataset_id(status: dict | None) -> str:
        if not isinstance(status, dict):
            return ""
        return str(status.get("dataset_id") or "").strip()

    def _build_start_payload(self, state: InferenceRecordingState) -> dict:
        payload: dict[str, object] = {
            "dataset_id": state.dataset_id,
            "dataset_name": state.dataset_name,
            "task": state.task,
            "num_episodes": state.batch_size,
            "episode_time_s": state.episode_time_s,
            "reset_time_s": state.reset_time_s,
            "cameras": state.cameras,
            "metadata": {
                "profile_snapshot": state.profile_snapshot,
                "session_kind": "inference",
                "inference_session_id": state.inference_session_id,
                "batch_size": state.batch_size,
            },
            "arm_namespaces": state.arm_namespaces,
        }
        payload.update(state.topic_suffixes)
        return payload

    @staticmethod
    def _is_finalizing_status(status: dict | None) -> bool:
        if not isinstance(status, dict):
            return False
        if bool(status.get("is_finalizing_episode")):
            return True
        return str(status.get("phase") or "").strip().lower() == "finalizing"

    @staticmethod
    def _desired_inference_pause_state(
        *,
        recorder_state: str,
        is_finalizing: bool,
        manual_paused: bool,
    ) -> bool:
        if manual_paused:
            return True
        return is_finalizing or recorder_state in {"resetting", "resetting_paused", "paused", "completed"}

    @staticmethod
    def _desired_teleop_state(*, recorder_state: str, is_finalizing: bool) -> bool:
        return is_finalizing or recorder_state in {"resetting", "resetting_paused"}

    async def _set_control_mode(
        self,
        state: InferenceRecordingState,
        *,
        inference_paused: bool,
        teleop_enabled: bool,
        recorder_state: str,
    ) -> None:
        if state.inference_paused != inference_paused:
            self._runtime.set_paused(session_id=state.worker_session_id, paused=inference_paused)
            state.inference_paused = inference_paused
        if state.teleop_enabled != teleop_enabled:
            await self._dashboard.set_teleop_enabled(enabled=teleop_enabled)
            state.teleop_enabled = teleop_enabled
        state.last_recorder_state = recorder_state

    async def _sync_mode_from_status(self, state: InferenceRecordingState, status: dict | None) -> None:
        recorder_state = self._recorder_state(status)
        is_finalizing = self._is_finalizing_status(status)
        recorder_dataset_id = self._recorder_dataset_id(status)
        if recorder_dataset_id and recorder_dataset_id != state.dataset_id:
            return
        if state.manual_paused and recorder_state in {"warming", "resetting", "recording"}:
            # If recorder progresses to a running phase (e.g., redo -> resetting),
            # treat it as an explicit resume intent and clear manual pause.
            state.manual_paused = False
        desired_inference_paused = self._desired_inference_pause_state(
            recorder_state=recorder_state,
            is_finalizing=is_finalizing,
            manual_paused=state.manual_paused,
        )
        desired_teleop_enabled = self._desired_teleop_state(
            recorder_state=recorder_state,
            is_finalizing=is_finalizing,
        )
        await self._set_control_mode(
            state,
            inference_paused=desired_inference_paused,
            teleop_enabled=desired_teleop_enabled,
            recorder_state=recorder_state,
        )

    async def _monitor_loop(self, inference_session_id: str) -> None:
        while True:
            with self._lock:
                state = self._states.get(inference_session_id)
            if state is None:
                return
            try:
                status = self._recorder.status()
            except Exception:
                status = None
            try:
                await self._sync_mode_from_status(state, status)
            except Exception as exc:
                logger.warning("Failed to sync inference/teleop mode: %s", exc)
            await asyncio.sleep(0.3)

    async def start(
        self,
        *,
        session: SessionState,
        task: str | None,
        denoising_steps: int | None,
        episode_time_s: float | None = None,
        reset_time_s: float | None = None,
    ) -> dict | None:
        if session.profile is None:
            logger.warning("Skip inference recording: profile is not resolved")
            return None

        cameras = self._recorder.build_cameras(session.profile.snapshot)
        arm_namespaces = extract_arm_namespaces(session.profile.snapshot)
        topic_suffixes = extract_recorder_topic_suffixes(
            session.profile.snapshot,
            arm_namespaces=arm_namespaces,
        )
        if not cameras:
            logger.warning("Skip inference recording: no recorder cameras resolved")
            return None
        if not arm_namespaces:
            logger.warning("Skip inference recording: no recorder arm namespaces resolved")
            return None
        if "state_topic_suffix" not in topic_suffixes:
            logger.warning("Skip inference recording: state_topic_suffix unresolved")
            return None
        if "action_topic_suffix" not in topic_suffixes:
            logger.warning("Skip inference recording: action_topic_suffix unresolved")
            return None

        dataset_id = generate_dataset_id()
        next_state = InferenceRecordingState(
            inference_session_id=session.id,
            worker_session_id=str(session.extras.get("worker_session_id") or "").strip(),
            dataset_id=dataset_id,
            dataset_name=f"eval-{session.id[:8]}",
            profile_snapshot=session.profile.snapshot,
            task=(task or "").strip(),
            episode_time_s=max(float(episode_time_s or self._default_episode_time_s), 1.0),
            reset_time_s=max(float(reset_time_s or self._default_reset_time_s), 0.0),
            denoising_steps=denoising_steps,
            batch_size=self._batch_size,
            target_total_episodes=self._batch_size,
            cameras=cameras,
            arm_namespaces=arm_namespaces,
            topic_suffixes=topic_suffixes,
        )

        await self._dashboard.set_teleop_enabled(enabled=False)
        next_state.teleop_enabled = False

        result = self._recorder.start(self._build_start_payload(next_state))
        if not result.get("success", False):
            logger.warning("Recorder start returned failure (non-critical): %s", result)
            return None

        self._upsert_state(next_state)
        self._start_monitor_loop(session.id)
        session.extras["dataset_id"] = dataset_id
        logger.info("Started inference recording: dataset_id=%s", dataset_id)

        await self._dataset.upsert_record(
            dataset_id=dataset_id,
            dataset_name=next_state.dataset_name,
            task=next_state.task,
            profile_snapshot=next_state.profile_snapshot,
            status="recording",
            target_total_episodes=next_state.target_total_episodes,
            episode_time_s=next_state.episode_time_s,
            reset_time_s=next_state.reset_time_s,
            dataset_type="eval",
        )
        await save_session_profile_binding(
            session_kind="recording",
            session_id=dataset_id,
            profile=session.profile,
        )
        return result

    def get_status(self, inference_session_id: str) -> dict:
        with self._lock:
            state = self._states.get(inference_session_id)
        if state is None:
            return {
                "recording_dataset_id": None,
                "recording_active": False,
                "awaiting_continue_confirmation": False,
                "batch_size": self._batch_size,
                "episode_count": 0,
                "num_episodes": 0,
                "episode_time_s": 0.0,
                "reset_time_s": 0.0,
                "denoising_steps": None,
            }

        status: dict | None = None
        try:
            status = self._recorder.status()
        except Exception:
            status = None

        recorder_state = self._recorder_state(status)
        recorder_dataset_id = self._recorder_dataset_id(status)
        dataset_matches = recorder_dataset_id == state.dataset_id
        recording_active = dataset_matches and recorder_state in _ACTIVE_RECORDER_STATES

        episode_count = 0
        num_episodes = state.batch_size
        if dataset_matches and isinstance(status, dict):
            try:
                episode_count = int(status.get("episode_count") or 0)
            except (TypeError, ValueError):
                episode_count = 0
            try:
                num_episodes = int(status.get("num_episodes") or state.batch_size)
            except (TypeError, ValueError):
                num_episodes = state.batch_size

        awaiting = state.awaiting_continue_confirmation
        if dataset_matches and recorder_state == "completed":
            awaiting = True
        elif recording_active:
            awaiting = False
        state.awaiting_continue_confirmation = awaiting

        return {
            "recording_dataset_id": state.dataset_id,
            "recording_active": recording_active,
            "awaiting_continue_confirmation": awaiting,
            "batch_size": state.batch_size,
            "episode_count": episode_count,
            "num_episodes": num_episodes,
            "episode_time_s": state.episode_time_s,
            "reset_time_s": state.reset_time_s,
            "denoising_steps": state.denoising_steps,
        }

    async def apply_settings(
        self,
        *,
        inference_session_id: str,
        worker_session_id: str,
        task: str | None,
        episode_time_s: float | None,
        reset_time_s: float | None,
        denoising_steps: int | None,
    ) -> dict:
        state = self._get_state_or_raise(inference_session_id)
        effective_worker_session_id = state.worker_session_id or worker_session_id

        if task is not None:
            normalized_task = task.strip()
            if not normalized_task:
                raise HTTPException(status_code=400, detail="task must not be empty")
            self._runtime.set_task(session_id=effective_worker_session_id, task=normalized_task)
            state.task = normalized_task

        if episode_time_s is not None:
            if episode_time_s <= 0:
                raise HTTPException(status_code=400, detail="episode_time_s must be > 0")
            state.episode_time_s = float(episode_time_s)

        if reset_time_s is not None:
            if reset_time_s < 0:
                raise HTTPException(status_code=400, detail="reset_time_s must be >= 0")
            state.reset_time_s = float(reset_time_s)

        if denoising_steps is not None:
            self._runtime.set_policy_options(
                session_id=effective_worker_session_id,
                denoising_steps=int(denoising_steps),
            )
            state.denoising_steps = int(denoising_steps)

        try:
            recorder_status = self._recorder.status()
        except Exception:
            recorder_status = None
        recorder_dataset_id = self._recorder_dataset_id(recorder_status)
        recorder_state = self._recorder_state(recorder_status)
        if recorder_dataset_id == state.dataset_id and recorder_state in _ACTIVE_RECORDER_STATES:
            update_payload: dict[str, object] = {
                "task": state.task,
                "episode_time_s": state.episode_time_s,
                "reset_time_s": state.reset_time_s,
            }
            update_result = self._recorder.update(update_payload)
            if not update_result.get("success", False):
                raise HTTPException(
                    status_code=500,
                    detail=update_result.get("error")
                    or update_result.get("message")
                    or "Failed to update recorder session",
                )

        await self._dataset.upsert_record(
            dataset_id=state.dataset_id,
            dataset_name=state.dataset_name,
            task=state.task,
            profile_snapshot=state.profile_snapshot,
            status="recording",
            target_total_episodes=state.target_total_episodes,
            episode_time_s=state.episode_time_s,
            reset_time_s=state.reset_time_s,
            dataset_type="eval",
        )

        return {
            "task": state.task,
            "episode_time_s": state.episode_time_s,
            "reset_time_s": state.reset_time_s,
            "denoising_steps": state.denoising_steps,
        }

    async def set_manual_pause(
        self,
        *,
        inference_session_id: str,
        paused: bool,
    ) -> dict:
        state = self._get_state_or_raise(inference_session_id)

        try:
            recorder_status = self._recorder.status()
        except Exception:
            recorder_status = None
        recorder_state = self._recorder_state(recorder_status)
        recorder_dataset_id = self._recorder_dataset_id(recorder_status)
        if recorder_dataset_id and recorder_dataset_id != state.dataset_id:
            raise HTTPException(status_code=409, detail="Recorder dataset does not match active inference dataset")

        if paused:
            if recorder_state in {"recording", "resetting"}:
                result = self._recorder.pause()
                if not result.get("success", False):
                    raise HTTPException(
                        status_code=500,
                        detail=result.get("error") or result.get("message") or "Recorder pause failed",
                    )
            state.manual_paused = True
        else:
            state.manual_paused = False
            if recorder_state in {"paused", "resetting_paused"}:
                result = self._recorder.resume()
                if not result.get("success", False):
                    raise HTTPException(
                        status_code=500,
                        detail=result.get("error") or result.get("message") or "Recorder resume failed",
                    )

        try:
            latest_status = self._recorder.status()
        except Exception:
            latest_status = recorder_status
        await self._sync_mode_from_status(state, latest_status)
        latest_state = self._recorder_state(latest_status)
        return {
            "paused": state.inference_paused,
            "teleop_enabled": state.teleop_enabled,
            "recorder_state": latest_state,
        }

    async def decide_continue(
        self,
        *,
        inference_session_id: str,
        continue_recording: bool,
    ) -> dict:
        state = self._get_state_or_raise(inference_session_id)
        if not continue_recording:
            state.awaiting_continue_confirmation = False
            return {
                "recording_dataset_id": state.dataset_id,
                "awaiting_continue_confirmation": False,
            }

        result = self._recorder.start(self._build_start_payload(state))
        if not result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail=result.get("error")
                or result.get("message")
                or "Failed to continue inference recording",
            )

        state.awaiting_continue_confirmation = False
        state.manual_paused = False
        state.target_total_episodes += state.batch_size
        await self._dataset.upsert_record(
            dataset_id=state.dataset_id,
            dataset_name=state.dataset_name,
            task=state.task,
            profile_snapshot=state.profile_snapshot,
            status="recording",
            target_total_episodes=state.target_total_episodes,
            episode_time_s=state.episode_time_s,
            reset_time_s=state.reset_time_s,
            dataset_type="eval",
        )
        return {
            "recording_dataset_id": state.dataset_id,
            "awaiting_continue_confirmation": False,
        }
