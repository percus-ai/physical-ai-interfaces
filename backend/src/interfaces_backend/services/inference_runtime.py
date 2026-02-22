"""Inference worker runtime manager for backend control plane."""

from __future__ import annotations

import atexit
from collections import deque
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import zmq

from interfaces_backend.models.inference import (
    GpuHostStatus,
    InferenceDeviceCompatibilityResponse,
    InferenceDeviceInfo,
    InferenceModelInfo,
    InferenceRunnerStatus,
    InferenceRunnerStatusResponse,
)
from interfaces_backend.utils.torch_info import get_torch_info
from percus_ai.environment.env_manager import EnvironmentManager
from percus_ai.observability import ArmId, CommOverheadReporter, EventStatus, PointId, resolve_ids
from percus_ai.storage.paths import get_models_dir, get_project_root

_PROTOCOL_NAME = "infer_v2"
_PROTOCOL_VERSION = 3
_IPC_BASE_DIR = Path("/tmp/percus_infer")
_DEFAULT_BRIDGE_ENDPOINT = os.environ.get("INFERENCE_BRIDGE_ZMQ_ENDPOINT", "tcp://127.0.0.1:5556")
_CTRL_TIMEOUT_MS = int(os.environ.get("INFERENCE_CTRL_TIMEOUT_MS", "1200"))
_START_SESSION_TIMEOUT_MS = int(os.environ.get("INFERENCE_START_SESSION_TIMEOUT_MS", "120000"))
_STARTUP_TIMEOUT_S = float(os.environ.get("INFERENCE_STARTUP_TIMEOUT_S", "20.0"))
_ACTION_HZ = float(os.environ.get("INFERENCE_ACTION_HZ", "30.0"))
_COMM_REPORTER = CommOverheadReporter("backend")


def _now_ns() -> int:
    return time.time_ns()


def _sum_dir_size_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _resolve_model_config_path(model_dir: Path) -> Optional[Path]:
    root_cfg = model_dir / "config.json"
    if root_cfg.exists():
        return root_cfg
    pretrained_cfg = model_dir / "pretrained_model" / "config.json"
    if pretrained_cfg.exists():
        return pretrained_cfg
    nested = sorted(model_dir.glob("**/config.json"))
    return nested[0] if nested else None


def _read_policy_type(config_path: Path) -> Optional[str]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("type")
    return value if isinstance(value, str) and value else None


class InferenceRuntimeManager:
    """Controls lifecycle of a single inference worker process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ctx = zmq.Context.instance()

        self._worker_proc: Optional[subprocess.Popen] = None
        self._worker_log: Optional[Any] = None

        self._ctrl_socket: Optional[zmq.Socket] = None
        self._event_socket: Optional[zmq.Socket] = None
        self._ctrl_endpoint: Optional[str] = None
        self._event_endpoint: Optional[str] = None
        self._ipc_dir: Optional[Path] = None

        self._event_thread: Optional[threading.Thread] = None
        self._event_stop = threading.Event()

        self._session_id: Optional[str] = None
        self._task: Optional[str] = None
        self._model_id: Optional[str] = None
        self._model_path: Optional[Path] = None
        self._policy_type: Optional[str] = None

        self._runner_state = "idle"
        self._queue_length = 0
        self._last_error: Optional[str] = None
        self._last_event: Optional[dict[str, Any]] = None
        self._event_history: deque[dict[str, Any]] = deque(maxlen=200)
        self._request_seq = 0
        self._worker_log_path: Optional[Path] = None
        self._worker_trace_path: Optional[Path] = None
        self._event_log_path: Optional[Path] = None

        atexit.register(self.shutdown)

    # --------------------------------------------------------------------- #
    # Read-only helpers
    # --------------------------------------------------------------------- #
    def is_active(self) -> bool:
        with self._lock:
            return self._runner_state in {"starting", "handshaking", "ready", "running"}

    def list_models(self) -> list[InferenceModelInfo]:
        with self._lock:
            active_model_id = self._model_id if self.is_active() else None

        models_dir = get_models_dir()
        if not models_dir.exists():
            return []

        models: list[InferenceModelInfo] = []
        for model_dir in sorted(models_dir.iterdir()):
            if not model_dir.is_dir():
                continue
            config_path = _resolve_model_config_path(model_dir)
            policy_type = _read_policy_type(config_path) if config_path else None
            size_mb = _sum_dir_size_bytes(model_dir) / (1024 * 1024)
            model_id = model_dir.name
            models.append(
                InferenceModelInfo(
                    model_id=model_id,
                    name=model_id,
                    policy_type=policy_type,
                    source="local",
                    size_mb=round(size_mb, 2),
                    is_loaded=(model_id == active_model_id),
                    is_local=True,
                )
            )
        return models

    def get_device_compatibility(self) -> InferenceDeviceCompatibilityResponse:
        info = get_torch_info(use_cache=False)
        devices = [InferenceDeviceInfo(device="cpu", available=True)]
        recommended = "cpu"

        if info.get("cuda_available"):
            devices.insert(
                0,
                InferenceDeviceInfo(
                    device="cuda:0",
                    available=True,
                    memory_total_mb=info.get("cuda_memory_total"),
                    memory_free_mb=info.get("cuda_memory_free"),
                ),
            )
            recommended = "cuda:0"
        elif info.get("mps_available"):
            devices.insert(0, InferenceDeviceInfo(device="mps", available=True))
            recommended = "mps"

        return InferenceDeviceCompatibilityResponse(devices=devices, recommended=recommended)

    def get_status(self) -> InferenceRunnerStatusResponse:
        self._refresh_state_from_worker()

        with self._lock:
            proc = self._worker_proc
            pid = proc.pid if proc else None
            proc_alive = proc is not None and proc.poll() is None

            runner_active = self._runner_state in {"starting", "handshaking", "ready", "running"}
            runner = InferenceRunnerStatus(
                active=runner_active,
                session_id=self._session_id,
                task=self._task,
                queue_length=self._queue_length,
                last_error=self._last_error,
            )

            if proc_alive and runner_active:
                gpu_status = "running"
            elif proc_alive:
                gpu_status = "idle"
            elif self._last_error:
                gpu_status = "error"
            else:
                gpu_status = "stopped"

            gpu_host = GpuHostStatus(
                status=gpu_status,
                session_id=self._session_id,
                pid=pid,
                last_error=self._last_error,
            )

        return InferenceRunnerStatusResponse(runner_status=runner, gpu_host_status=gpu_host)

    def get_diagnostics(self) -> dict[str, Any]:
        self._refresh_state_from_worker()
        with self._lock:
            session_id = self._session_id
            state = self._runner_state
            task = self._task
            ctrl_endpoint = self._ctrl_endpoint
            event_endpoint = self._event_endpoint
            bridge_endpoint = _DEFAULT_BRIDGE_ENDPOINT
            worker_log_path = str(self._worker_log_path) if self._worker_log_path else None
            worker_trace_path = str(self._worker_trace_path) if self._worker_trace_path else None
            event_log_path = str(self._event_log_path) if self._event_log_path else None
            recent_events = list(self._event_history)
            last_error = self._last_error
            proc = self._worker_proc
            pid = proc.pid if proc else None
            alive = proc is not None and proc.poll() is None

        checks = [
            {
                "key": "worker_process_alive",
                "description": "worker process is alive",
                "ok": bool(alive),
                "detail": f"pid={pid}" if pid else "no process",
            },
            {
                "key": "worker_state_running",
                "description": "worker state is running",
                "ok": state == "running",
                "detail": state,
            },
            {
                "key": "last_error_empty",
                "description": "last_error is empty",
                "ok": not bool(last_error),
                "detail": last_error or "",
            },
            {
                "key": "control_endpoint_ready",
                "description": "control IPC endpoint is configured",
                "ok": bool(ctrl_endpoint),
                "detail": ctrl_endpoint or "",
            },
            {
                "key": "event_endpoint_ready",
                "description": "event IPC endpoint is configured",
                "ok": bool(event_endpoint),
                "detail": event_endpoint or "",
            },
        ]

        return {
            "session_id": session_id,
            "state": state,
            "task": task,
            "control": {
                "ctrl_endpoint": ctrl_endpoint,
                "event_endpoint": event_endpoint,
                "bridge_endpoint": bridge_endpoint,
            },
            "logs": {
                "worker_log_path": worker_log_path,
                "worker_trace_path": worker_trace_path,
                "event_log_path": event_log_path,
                "bridge_trace_path": os.environ.get("INFERENCE_BRIDGE_TRACE_LOG_PATH", ""),
            },
            "recent_events": recent_events,
            "checks": checks,
        }

    # --------------------------------------------------------------------- #
    # Lifecycle control
    # --------------------------------------------------------------------- #
    def start(
        self,
        model_id: str,
        device: Optional[str],
        task: Optional[str],
        policy_options: Optional[dict[str, Any]] = None,
        joint_names: Optional[list[str]] = None,
        camera_key_aliases: Optional[dict[str, str]] = None,
        bridge_stream_config: Optional[dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, float, str, Optional[dict[str, Any]]], None]] = None,
    ) -> str:
        with self._lock:
            if self._worker_proc and self._worker_proc.poll() is None:
                raise RuntimeError("Inference worker already running")

        model_dir = get_models_dir() / model_id
        if not model_dir.exists():
            raise FileNotFoundError(f"Model not found: {model_id}")

        config_path = _resolve_model_config_path(model_dir)
        if not config_path:
            raise RuntimeError(f"config.json not found under model: {model_id}")
        model_runtime_dir = config_path.parent

        policy_type = _read_policy_type(config_path)
        if not policy_type:
            raise RuntimeError(f"Policy type is missing in {config_path}")
        policy_type_normalized = policy_type.lower()

        raw_policy_options = policy_options or {}
        if not isinstance(raw_policy_options, dict):
            raise RuntimeError("policy_options must be an object")
        policy_options_normalized: dict[str, dict[str, Any]] = {}
        for policy_key, options in raw_policy_options.items():
            normalized_policy_key = str(policy_key or "").strip().lower()
            if not normalized_policy_key:
                continue
            if normalized_policy_key not in {"pi0", "pi05"}:
                raise RuntimeError(f"Unsupported policy_options key: {normalized_policy_key}")
            if options is None:
                continue
            if not isinstance(options, dict):
                raise RuntimeError(f"policy_options.{normalized_policy_key} must be an object")
            policy_options_normalized[normalized_policy_key] = dict(options)

        if policy_options_normalized and set(policy_options_normalized.keys()) != {policy_type_normalized}:
            raise RuntimeError(
                f"policy_options must target active policy '{policy_type_normalized}'"
            )
        active_policy_options = policy_options_normalized.get(policy_type_normalized, {})

        denoising_steps_value: Optional[int] = None
        denoising_steps = active_policy_options.get("denoising_steps")
        if denoising_steps is not None:
            try:
                denoising_steps_value = int(denoising_steps)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "policy_options.<policy>.denoising_steps must be an integer"
                ) from exc
            if denoising_steps_value < 1:
                raise RuntimeError("policy_options.<policy>.denoising_steps must be >= 1")
            if policy_type_normalized not in {"pi0", "pi05"}:
                raise RuntimeError("denoising_steps is only supported for pi0/pi05")

        compatibility = self.get_device_compatibility()
        selected_device = (device or compatibility.recommended or "cpu").strip()
        available = {item.device for item in compatibility.devices if item.available}
        if selected_device not in available:
            raise RuntimeError(f"Device '{selected_device}' is not available")

        repo_root = get_project_root()
        run_in_env = repo_root / "features" / "percus_ai" / "environment" / "run_in_env.sh"
        if not run_in_env.exists():
            raise RuntimeError(f"run_in_env.sh not found: {run_in_env}")

        env_manager = EnvironmentManager(repo_root)
        env_name = env_manager.get_env_for_policy(policy_type)

        session_id = uuid.uuid4().hex
        ipc_dir = _IPC_BASE_DIR / session_id
        ipc_dir.mkdir(parents=True, exist_ok=True)
        ctrl_endpoint = f"ipc://{ipc_dir / 'ctrl.sock'}"
        event_endpoint = f"ipc://{ipc_dir / 'evt.sock'}"

        worker_cmd = [
            str(run_in_env),
            env_name,
            "python",
            "-m",
            "percus_ai.inference.worker_main",
            "--session-id",
            session_id,
            "--ctrl-endpoint",
            ctrl_endpoint,
            "--event-endpoint",
            event_endpoint,
            "--bridge-endpoint",
            _DEFAULT_BRIDGE_ENDPOINT,
            "--protocol",
            _PROTOCOL_NAME,
            "--version",
            str(_PROTOCOL_VERSION),
        ]

        log_path = ipc_dir / "worker.log"
        worker_trace_path = ipc_dir / "worker_trace.jsonl"
        event_log_path = ipc_dir / "events.jsonl"
        if progress_callback is not None:
            progress_callback("launch_worker", 88.0, "推論ワーカーを起動しています...", None)
        worker_cmd += [
            "--trace-log-path",
            str(worker_trace_path),
        ]

        event_log_path.touch(exist_ok=True)
        worker_log = open(log_path, "a", encoding="utf-8")
        worker_proc = subprocess.Popen(
            worker_cmd,
            cwd=repo_root,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            text=True,
        )

        with self._lock:
            self._worker_proc = worker_proc
            self._worker_log = worker_log
            self._session_id = session_id
            self._task = task.strip() if isinstance(task, str) and task.strip() else ""
            self._model_id = model_id
            self._model_path = model_runtime_dir
            self._policy_type = policy_type
            self._ctrl_endpoint = ctrl_endpoint
            self._event_endpoint = event_endpoint
            self._ipc_dir = ipc_dir
            self._runner_state = "starting"
            self._queue_length = 0
            self._last_error = None
            self._last_event = None
            self._request_seq = 0
            self._event_history.clear()
            self._worker_log_path = log_path
            self._worker_trace_path = worker_trace_path
            self._event_log_path = event_log_path

            self._connect_ctrl_socket_locked()
            self._start_event_listener_locked()

        start_deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < start_deadline:
            if worker_proc.poll() is not None:
                with self._lock:
                    self._last_error = f"worker exited during startup (code={worker_proc.returncode})"
                    self._runner_state = "error"
                self._cleanup_worker_resources()
                raise RuntimeError("Worker exited before startup completed")

            try:
                self._send_ctrl_command("get_state", {}, timeout_ms=300, raise_on_error=False)
                break
            except Exception:
                time.sleep(0.2)
        else:
            with self._lock:
                self._last_error = "worker startup timeout"
                self._runner_state = "error"
            self._cleanup_worker_resources()
            raise RuntimeError("Timed out waiting for worker control socket")

        model_policy_options = dict(active_policy_options)
        if denoising_steps_value is not None:
            model_policy_options["denoising_steps"] = denoising_steps_value

        start_payload: dict[str, Any] = {
            "task": self._task or "",
            "model": {
                "policy_type": policy_type,
                "model_path": str(model_runtime_dir),
                "device": selected_device,
                "policy_options": model_policy_options,
            },
            "robot": {
                "joint_names": [str(name) for name in (joint_names or []) if str(name).strip()],
                "camera_key_aliases": {
                    str(src): str(dst)
                    for src, dst in (camera_key_aliases or {}).items()
                    if str(src).strip() and str(dst).strip()
                },
                "bridge_stream_config": dict(bridge_stream_config or {}),
            },
            "execution_hz": _ACTION_HZ,
            "protocol": {"name": _PROTOCOL_NAME, "version": _PROTOCOL_VERSION},
        }
        if progress_callback is not None:
            progress_callback("launch_worker", 94.0, "ワーカーとハンドシェイクしています...", None)
        try:
            self._send_ctrl_command("start_session", start_payload, timeout_ms=_START_SESSION_TIMEOUT_MS)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._runner_state = "error"
            self._cleanup_worker_resources()
            raise
        self._refresh_state_from_worker()
        if progress_callback is not None:
            progress_callback("launch_worker", 98.0, "推論ワーカーの準備が完了しました。", None)
        return session_id

    def stop(self, session_id: Optional[str] = None) -> bool:
        with self._lock:
            if session_id and self._session_id and session_id != self._session_id:
                raise RuntimeError(f"Session mismatch: requested={session_id} active={self._session_id}")
            proc = self._worker_proc
            if not proc:
                self._runner_state = "stopped"
                return False

        try:
            self._send_ctrl_command("stop_session", {}, timeout_ms=1000, raise_on_error=False)
        except Exception:
            pass

        self._cleanup_worker_resources()
        with self._lock:
            self._runner_state = "stopped"
            self._queue_length = 0
        return True

    def set_task(self, session_id: str, task: str) -> int:
        with self._lock:
            if not self._session_id or session_id != self._session_id:
                raise RuntimeError("Active session not found")
            if not self._worker_proc or self._worker_proc.poll() is not None:
                raise RuntimeError("Worker process is not running")

        payload = {"task": task}
        response = self._send_ctrl_command("set_task", payload, timeout_ms=1000)
        applied_from_step = int(response.get("applied_from_step", 0))
        with self._lock:
            self._task = task
        return applied_from_step

    def shutdown(self) -> None:
        try:
            self.stop()
        except Exception:
            return

    # --------------------------------------------------------------------- #
    # ZMQ helpers
    # --------------------------------------------------------------------- #
    def _next_request_id_locked(self) -> str:
        self._request_seq += 1
        return f"req-{self._request_seq:08d}"

    def _connect_ctrl_socket_locked(self) -> None:
        if self._ctrl_socket is not None:
            try:
                self._ctrl_socket.close(0)
            except Exception:
                pass
        if not self._ctrl_endpoint:
            raise RuntimeError("Control endpoint is not set")
        sock = self._ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self._ctrl_endpoint)
        self._ctrl_socket = sock

    def _send_ctrl_command(
        self,
        command_type: str,
        payload: dict[str, Any],
        timeout_ms: int = _CTRL_TIMEOUT_MS,
        raise_on_error: bool = True,
    ) -> dict[str, Any]:
        session_id, trace_id = resolve_ids(self._session_id, None)
        payload_size = len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        timer = _COMM_REPORTER.timed(
            point_id=PointId.CP_03,
            session_id=session_id,
            trace_id=trace_id,
            arm=ArmId.NONE,
            payload_bytes=payload_size,
            tags={"command_type": command_type, "timeout_ms": timeout_ms},
        )
        with self._lock:
            if not self._ctrl_socket:
                timer.error("control socket is not connected")
                raise RuntimeError("Control socket is not connected")
            request_id = self._next_request_id_locked()
            request = {
                "type": command_type,
                "session_id": session_id,
                "trace_id": trace_id,
                "request_id": request_id,
                "timestamp_ns": _now_ns(),
                "payload": payload,
            }
            self._ctrl_socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
            self._ctrl_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
            try:
                self._ctrl_socket.send_json(request)
                response = self._ctrl_socket.recv_json()
            except Exception as exc:
                self._connect_ctrl_socket_locked()
                timer.error(str(exc))
                raise RuntimeError(f"control command '{command_type}' failed: {exc}") from exc

        if not isinstance(response, dict):
            timer.error("invalid response type")
            raise RuntimeError(f"Invalid control response for '{command_type}'")

        ok = bool(response.get("ok", False))
        response_payload = response.get("payload")
        if not isinstance(response_payload, dict):
            response_payload = {}

        if not ok and raise_on_error:
            detail = response_payload.get("error") or response.get("message") or "unknown error"
            timer.error(str(detail), extra_tags={"ok": ok})
            raise RuntimeError(f"Worker rejected '{command_type}': {detail}")

        timer.success(extra_tags={"ok": ok, "response_type": str(response.get("type") or "")})
        return response_payload

    def _start_event_listener_locked(self) -> None:
        self._event_stop.clear()

        if self._event_socket is not None:
            try:
                self._event_socket.close(0)
            except Exception:
                pass
            self._event_socket = None

        if not self._event_endpoint:
            return

        sock = self._ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        sock.connect(self._event_endpoint)
        self._event_socket = sock

        thread = threading.Thread(target=self._event_loop, name="inference-event-listener", daemon=True)
        self._event_thread = thread
        thread.start()

    def _event_loop(self) -> None:
        while not self._event_stop.is_set():
            sock = self._event_socket
            if sock is None:
                return

            try:
                if sock.poll(200) == 0:
                    continue
                event = sock.recv_json(flags=zmq.NOBLOCK)
            except Exception:
                continue

            if not isinstance(event, dict):
                continue

            severity = str(event.get("severity") or "")
            code = str(event.get("code") or "")
            message = str(event.get("message") or "")
            detail = event.get("detail")
            raw_timestamp = event.get("timestamp_ns")
            try:
                event_timestamp_ns = int(raw_timestamp) if raw_timestamp is not None else _now_ns()
            except Exception:
                event_timestamp_ns = _now_ns()
            event_session_hint = str(event.get("session_id") or "").strip() or self._session_id
            event_trace_hint = str(event.get("trace_id") or "").strip() or None
            session_id, trace_id = resolve_ids(event_session_hint, event_trace_hint)
            status = EventStatus.OK
            if severity in {"warn", "error", "fatal"}:
                status = EventStatus.ERROR
            _COMM_REPORTER.export(
                point_id=PointId.CP_04,
                session_id=session_id,
                trace_id=trace_id,
                arm=ArmId.NONE,
                status=status,
                latency_ns=max(_now_ns() - event_timestamp_ns, 0),
                payload_bytes=len(json.dumps(event, ensure_ascii=True).encode("utf-8")),
                tags={
                    "event_type": str(event.get("type") or ""),
                    "severity": severity,
                    "code": code,
                },
            )

            with self._lock:
                self._last_event = event
                self._event_history.append(event)
                if severity in {"error", "fatal"}:
                    suffix = f" ({code})" if code else ""
                    if detail:
                        self._last_error = f"{message}{suffix}: {detail}"
                    else:
                        self._last_error = f"{message}{suffix}"
                if severity == "fatal":
                    self._runner_state = "error"
                event_log_path = self._event_log_path

            if event_log_path:
                try:
                    with event_log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
                except OSError:
                    pass

    # --------------------------------------------------------------------- #
    # State refresh and cleanup
    # --------------------------------------------------------------------- #
    def _refresh_state_from_worker(self) -> None:
        with self._lock:
            proc = self._worker_proc
            session_id = self._session_id
            proc_alive = proc is not None and proc.poll() is None

        if not session_id or not proc:
            return

        if not proc_alive:
            with self._lock:
                if self._runner_state not in {"stopped", "error"}:
                    self._runner_state = "error"
                    if not self._last_error:
                        self._last_error = f"worker exited unexpectedly (code={proc.returncode})"
            return

        try:
            state = self._send_ctrl_command("get_state", {}, timeout_ms=500, raise_on_error=False)
        except Exception:
            return

        with self._lock:
            worker_state = state.get("state")
            if isinstance(worker_state, str) and worker_state:
                self._runner_state = worker_state
            worker_task = state.get("task")
            if isinstance(worker_task, str):
                self._task = worker_task
            queue_depth = state.get("queue_depth")
            if isinstance(queue_depth, int):
                self._queue_length = max(queue_depth, 0)
            last_error = state.get("last_error")
            if isinstance(last_error, str) and last_error:
                self._last_error = last_error

    def _cleanup_worker_resources(self) -> None:
        with self._lock:
            proc = self._worker_proc
            self._worker_proc = None

        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass

        self._event_stop.set()

        with self._lock:
            if self._event_socket is not None:
                try:
                    self._event_socket.close(0)
                except Exception:
                    pass
                self._event_socket = None

            if self._ctrl_socket is not None:
                try:
                    self._ctrl_socket.close(0)
                except Exception:
                    pass
                self._ctrl_socket = None

            thread = self._event_thread
            self._event_thread = None

            if self._worker_log is not None:
                try:
                    self._worker_log.close()
                except Exception:
                    pass
                self._worker_log = None

            self._session_id = None
            self._task = None
            self._model_id = None
            self._model_path = None
            self._policy_type = None
            self._ctrl_endpoint = None
            self._event_endpoint = None
            self._ipc_dir = None
            self._queue_length = 0
            self._worker_log_path = None
            self._worker_trace_path = None
            self._event_log_path = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)


_runtime_manager: Optional[InferenceRuntimeManager] = None
_runtime_lock = threading.Lock()


def get_inference_runtime_manager() -> InferenceRuntimeManager:
    global _runtime_manager
    with _runtime_lock:
        if _runtime_manager is None:
            _runtime_manager = InferenceRuntimeManager()
    return _runtime_manager
