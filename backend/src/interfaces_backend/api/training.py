"""Training jobs API router."""

import asyncio
import inspect
import json
import logging
import os
import shlex
import tempfile
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Literal, Optional

from verda import VerdaClient
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse
from supabase import create_async_client
from supabase._async.client import AsyncClient

from interfaces_backend.core.request_auth import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    build_session_from_tokens,
    is_session_expired,
    refresh_session_from_refresh_token,
)
from interfaces_backend.models.training import (
    JobInfo,
    JobListResponse,
    JobDetailResponse,
    JobLogsResponse,
    JobProgressResponse,
    JobActionResponse,
    JobStatusCheckResponse,
    JobStatusUpdate,
    JobCreateRequest,
    JobCreateResponse,
    JobMetricsResponse,
    InstanceStatusResponse,
    # Checkpoint models
    CheckpointDatasetInfo,
    CheckpointInfo,
    CheckpointListResponse,
    CheckpointDetailResponse,
    CheckpointDownloadRequest,
    CheckpointDownloadResponse,
    DatasetCompatibilityCheckRequest,
    DatasetCompatibilityCheckResponse,
    # Continue training models
    JobCreateContinueRequest,
    EarlyStoppingConfig,
    ValidationConfig,
    # GPU availability
    GpuAvailabilityInfo,
    GpuAvailabilityResponse,
    VerdaStorageActionFailure,
    VerdaStorageActionRequest,
    VerdaStorageActionResult,
    VerdaStorageItem,
    VerdaStorageListResponse,
    JobReviveResponse,
    RemoteCheckpointListResponse,
    RemoteCheckpointUploadRequest,
    RemoteCheckpointUploadResponse,
)
from percus_ai.storage import get_project_root, get_models_dir
from percus_ai.db import (
    get_current_user_id,
    get_supabase_async_client,
    get_supabase_session,
    reset_request_session,
    set_request_session,
    upsert_with_owner,
)
from percus_ai.training.ssh.client import SSHConnection
from percus_ai.training.ssh.executor import RemoteExecutor, run_remote_command

logger = logging.getLogger(__name__)

_service_client: Optional[AsyncClient] = None
_service_client_lock = asyncio.Lock()


def _is_jwt_expired_error(exc: Exception) -> bool:
    text = str(exc)
    return "JWT expired" in text or "PGRST303" in text


async def _get_service_db_client() -> Optional[AsyncClient]:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not supabase_url or not service_key:
        return None

    global _service_client
    if _service_client is not None:
        return _service_client

    async with _service_client_lock:
        if _service_client is None:
            _service_client = await create_async_client(supabase_url, service_key)
        return _service_client


def _default_author_user_id() -> str:
    try:
        return get_current_user_id()
    except ValueError:
        return "unknown"


router = APIRouter(prefix="/api/training", tags=["training"])

# Thread pool for WebSocket operations
_executor = ThreadPoolExecutor(max_workers=2)

DB_TABLE = "training_jobs"

RUNNING_STATUSES = {"running", "starting", "deploying"}
RUNNING_STATUSES_WITH_PENDING = {"running", "starting", "deploying", "pending"}


def _first_dict(*values: object) -> Optional[dict]:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _extract_record(payload: object) -> Optional[dict]:
    if isinstance(payload, dict):
        record = _first_dict(payload.get("new"), payload.get("record"))
        if record:
            return record
        data = payload.get("data")
        if isinstance(data, dict):
            record = _first_dict(data.get("record"), data.get("new"))
            if record:
                return record
        record = _first_dict(payload.get("old"), payload.get("old_record"))
        if record:
            return record
        return None

    for attr in ("new", "record", "old"):
        record = getattr(payload, attr, None)
        if isinstance(record, dict):
            return record

    data = getattr(payload, "data", None) or getattr(payload, "payload", None)
    if isinstance(data, dict):
        record = _first_dict(data.get("record"), data.get("new"), data.get("old"))
        if record:
            return record

    return None


def _extract_event_type(payload: object) -> str:
    if isinstance(payload, dict):
        event_type = (
            payload.get("eventType") or payload.get("event_type") or payload.get("type")
        )
        if isinstance(event_type, str):
            return event_type.upper()
        data = payload.get("data")
        if isinstance(data, dict):
            event_type = (
                data.get("eventType") or data.get("event_type") or data.get("type")
            )
            if isinstance(event_type, str):
                return event_type.upper()

    for attr in ("event_type", "eventType", "type"):
        event_type = getattr(payload, attr, None)
        if isinstance(event_type, str):
            return event_type.upper()

    return ""


def _extract_status_update(payload: object) -> tuple[Optional[str], Optional[str]]:
    record = _extract_record(payload)
    job_id = record.get("job_id") if isinstance(record, dict) else None
    status = record.get("status") if isinstance(record, dict) else None
    if not status:
        event_type = _extract_event_type(payload)
        if event_type == "DELETE":
            status = "deleted"
    return job_id, status


def _drain_latest_status(queue: "asyncio.Queue") -> Optional[str]:
    latest_status = None
    while True:
        try:
            update = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if isinstance(update, dict):
            status = update.get("status")
            if status:
                latest_status = status
    return latest_status


async def _maybe_await(result: object) -> None:
    if inspect.isawaitable(result):
        await result


class _TrainingJobRealtimeSubscriber:
    def __init__(
        self, job_id: str, loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue"
    ) -> None:
        self.job_id = job_id
        self.loop = loop
        self.queue = queue


class TrainingJobRealtimeManager:
    def __init__(self) -> None:
        self._client = None
        self._channel = None
        self._realtime = None
        self._channel_lock = asyncio.Lock()
        self._subscribers: dict[str, _TrainingJobRealtimeSubscriber] = {}
        self._subscribers_lock = threading.Lock()

    async def subscribe(
        self,
        job_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[str, "asyncio.Queue"]:
        await self._ensure_channel()
        queue: asyncio.Queue = asyncio.Queue()
        subscriber_id = uuid.uuid4().hex
        with self._subscribers_lock:
            self._subscribers[subscriber_id] = _TrainingJobRealtimeSubscriber(
                job_id, loop, queue
            )
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._subscribers_lock:
            self._subscribers.pop(subscriber_id, None)

    async def _ensure_channel(self) -> None:
        async with self._channel_lock:
            if self._channel:
                return

            self._client = await get_supabase_async_client()
            realtime = getattr(self._client, "realtime", None) or getattr(
                self._client,
                "realtime_client",
                None,
            )
            if realtime is None:
                raise RuntimeError(
                    "Supabase Realtime client is not available (async client required)"
                )

            channel_factory = getattr(realtime, "channel", None) or getattr(
                self._client, "channel", None
            )
            if channel_factory is None or not callable(channel_factory):
                raise RuntimeError("Supabase Realtime channel API is not available")

            channel = channel_factory(DB_TABLE)
            on_changes = getattr(channel, "on_postgres_changes", None)
            if on_changes is not None and callable(on_changes):
                on_changes(
                    event="*",
                    schema="public",
                    table=DB_TABLE,
                    callback=self._handle_change,
                )
            else:
                on_method = getattr(channel, "on", None)
                if on_method is None or not callable(on_method):
                    raise RuntimeError(
                        "Supabase Realtime channel handler is not available"
                    )
                on_method(
                    "postgres_changes",
                    {"event": "*", "schema": "public", "table": DB_TABLE},
                    self._handle_change,
                )

            connect = getattr(realtime, "connect", None)
            if connect is not None and callable(connect):
                await _maybe_await(connect())

            subscribe = getattr(channel, "subscribe", None)
            if subscribe is None or not callable(subscribe):
                raise RuntimeError(
                    "Supabase Realtime channel.subscribe is not available"
                )

            await _maybe_await(subscribe())

            self._realtime = realtime
            self._channel = channel

    def _handle_change(self, payload: object) -> None:
        job_id, status = _extract_status_update(payload)
        if not job_id or not status:
            return

        with self._subscribers_lock:
            subscribers = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.job_id == job_id
            ]

        for subscriber in subscribers:
            if subscriber.loop.is_closed():
                continue
            try:
                subscriber.loop.call_soon_threadsafe(
                    subscriber.queue.put_nowait,
                    {"job_id": job_id, "status": status},
                )
            except Exception as exc:
                logger.debug("Failed to enqueue training job update: %s", exc)


_training_job_realtime_manager: Optional[TrainingJobRealtimeManager] = None


def _get_training_job_realtime_manager() -> TrainingJobRealtimeManager:
    global _training_job_realtime_manager
    if _training_job_realtime_manager is None:
        _training_job_realtime_manager = TrainingJobRealtimeManager()
    return _training_job_realtime_manager


# Remote scripts directory - contains setup_env.sh, run_training.sh, entry.py, etc.
# These scripts are deployed to remote instances for training
REMOTE_SCRIPTS_DIR = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "features"
    / "percus_ai"
    / "training"
    / "remote"
)
REPO_ROOT = REMOTE_SCRIPTS_DIR.parents[4]


# --- SSH utilities for remote deployment ---
# Uses SSHConnection from percus_ai.training.ssh.client for consistency with executor.py


def _create_ssh_connection(
    ip: str,
    user: str,
    private_key_path: str,
    timeout: int = 30,
) -> SSHConnection:
    """Create and connect an SSHConnection to the remote host.

    Args:
        ip: Remote host IP address
        user: SSH username
        private_key_path: Path to SSH private key file
        timeout: Connection timeout in seconds

    Returns:
        Connected SSHConnection instance
    """
    key_path = Path(private_key_path).expanduser()
    if not key_path.exists():
        raise RuntimeError(f"SSH鍵が見つかりません: {key_path}")
    if not key_path.is_file():
        raise RuntimeError(f"SSH鍵パスが不正です: {key_path}")
    conn = SSHConnection(host=ip, user=user, private_key_path=key_path)
    try:
        conn.connect(timeout_sec=timeout)
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    return conn


def _get_default_ssh_user() -> str:
    return (os.environ.get("VERDA_SSH_USER", "root") or "root").strip() or "root"


def _build_ssh_user_candidates(primary_user: str) -> list[str]:
    candidates: list[str] = []
    for user in (primary_user, "root", "ubuntu"):
        user_normalized = (user or "").strip()
        if user_normalized and user_normalized not in candidates:
            candidates.append(user_normalized)
    return candidates or ["root", "ubuntu"]


def _resolve_private_key_candidate_paths(raw_path: Optional[str]) -> list[Path]:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return []

    base = Path(normalized).expanduser()
    candidates: list[Path] = [base]
    if not base.is_absolute():
        candidates.append(get_project_root() / base)

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def _discover_common_private_keys() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve(strict=False))
        if key in seen:
            return
        seen.add(key)
        if path.exists() and path.is_file():
            candidates.append(path)

    for path in Path.home().glob(".ssh/id_*"):
        if path.name.endswith(".pub"):
            continue
        add(path)

    data_dir_raw = str(os.environ.get("PHYSICAL_AI_DATA_DIR") or "").strip()
    if data_dir_raw:
        for data_dir in _resolve_private_key_candidate_paths(data_dir_raw):
            if not data_dir.exists() or not data_dir.is_dir():
                continue
            for path in data_dir.glob("id_*"):
                if path.name.endswith(".pub"):
                    continue
                add(path)

    return candidates


def _build_ssh_private_key_candidates(primary_path: Optional[str]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    explicit_paths: list[str] = [
        os.environ.get("VERDA_SSH_PRIVATE_KEY"),
        primary_path,
        str(Path.home() / ".ssh" / "id_rsa"),
        str(Path.home() / ".ssh" / "id_ed25519"),
    ]
    explicit_extra = str(os.environ.get("VERDA_SSH_PRIVATE_KEYS") or "").strip()
    if explicit_extra:
        explicit_paths.extend(
            [item.strip() for item in explicit_extra.split(",") if item.strip()]
        )

    for raw in explicit_paths:
        for expanded in _resolve_private_key_candidate_paths(raw):
            key = str(expanded.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            if expanded.exists() and expanded.is_file():
                candidates.append(expanded)

    for expanded in _discover_common_private_keys():
        key = str(expanded.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(expanded)
    return candidates


def _select_preferred_ssh_private_key(primary_path: Optional[str]) -> str:
    candidates = _build_ssh_private_key_candidates(primary_path)
    if candidates:
        return str(candidates[0])
    fallback = str(primary_path or "").strip() or str(Path.home() / ".ssh" / "id_rsa")
    return str(Path(fallback).expanduser())


def _resolve_ssh_private_key_path(private_key_path: str) -> str:
    candidates = _resolve_private_key_candidate_paths(private_key_path)
    for key_path in candidates:
        if key_path.exists() and key_path.is_file():
            return str(key_path)
    display = ", ".join(str(p) for p in candidates) or private_key_path
    raise RuntimeError(
        f"SSH鍵が見つかりません: {display} "
        "(バックエンド実行環境に鍵ファイルを配置してください)"
    )


def _build_pipeline_config(request: "JobCreateRequest", job_id: str) -> dict:
    """Build TrainingPipeline JSON config from JobCreateRequest."""
    dataset = request.dataset
    policy = request.policy

    training = {k: v for k, v in request.training.model_dump().items() if v is not None}
    training.setdefault("save_checkpoint", True)

    validation = {
        k: v for k, v in request.validation.model_dump().items() if v is not None
    }
    early_stopping = {
        k: v for k, v in request.early_stopping.model_dump().items() if v is not None
    }
    if early_stopping.get("enable"):
        validation.setdefault("enable", True)
        if not training.get("save_checkpoint", True):
            training["save_checkpoint"] = True
    if validation.get("enable") and validation.get("eval_freq") is None:
        validation["eval_freq"] = training.get("save_freq") or 20_000

    config = {
        "dataset": {
            "id": dataset.id,
        },
        "policy": {
            "type": policy.type,
            "push_to_hub": False,
        },
        "training": training,
        "validation": validation or {"enable": False},
        "early_stopping": early_stopping or {"enable": False},
        "output": {
            "job_name": job_id,
        },
        "rename_map": {},
        "seed": 1000,
    }

    if policy.pretrained_path:
        config["policy"]["pretrained_path"] = policy.pretrained_path
    if policy.dtype:
        config["policy"]["dtype"] = policy.dtype
    if policy.compile_model is not None:
        config["policy"]["compile_model"] = policy.compile_model
    if policy.gradient_checkpointing is not None:
        config["policy"]["gradient_checkpointing"] = policy.gradient_checkpointing
    if policy.use_amp is not None:
        config["policy"]["use_amp"] = policy.use_amp
    if config["policy"].get("dtype") in ("bfloat16", "bf16") and config["policy"].get(
        "use_amp"
    ):
        config["policy"]["use_amp"] = False
    if dataset.video_backend:
        config["dataset"]["video_backend"] = dataset.video_backend
    if dataset.split:
        config["dataset"]["split"] = {
            "train_ratio": dataset.split.train_ratio,
            "seed": dataset.split.seed,
        }

    return config


def _load_env_file_vars() -> dict[str, str]:
    env_paths = [
        REPO_ROOT / ".env",
        REPO_ROOT / "data" / ".env",
    ]
    data: dict[str, str] = {}
    for path in env_paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data.setdefault(key.strip(), value.strip())
        except Exception:
            continue
    return data


def _generate_env_file(
    job_id: str,
    instance_id: str,
    policy_type: Optional[str],
    auto_delete: bool = True,
    supabase_access_token: Optional[str] = None,
    supabase_refresh_token: Optional[str] = None,
    supabase_user_id: Optional[str] = None,
) -> str:
    """Generate .env file content with required credentials."""
    lines = []
    env_fallback = _load_env_file_vars()

    # HuggingFace token
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if hf_token:
        lines.append(f"HF_TOKEN={hf_token}")

    # WandB API key
    wandb_key = os.environ.get("WANDB_API_KEY")
    if wandb_key:
        lines.append(f"WANDB_API_KEY={wandb_key}")

    # DataCrunch credentials
    dc_client_id = os.environ.get("DATACRUNCH_CLIENT_ID")
    dc_client_secret = os.environ.get("DATACRUNCH_CLIENT_SECRET")
    if dc_client_id:
        lines.append(f"DATACRUNCH_CLIENT_ID={dc_client_id}")
    if dc_client_secret:
        lines.append(f"DATACRUNCH_CLIENT_SECRET={dc_client_secret}")

    # R2/S3 credentials
    r2_endpoint = (
        os.environ.get("R2_ENDPOINT_URL")
        or os.environ.get("S3_ENDPOINT_URL")
        or env_fallback.get("R2_ENDPOINT_URL")
        or env_fallback.get("S3_ENDPOINT_URL")
    )
    r2_access_key = (
        os.environ.get("R2_ACCESS_KEY_ID")
        or os.environ.get("S3_ACCESS_KEY_ID")
        or env_fallback.get("R2_ACCESS_KEY_ID")
        or env_fallback.get("S3_ACCESS_KEY_ID")
    )
    r2_secret_key = (
        os.environ.get("R2_SECRET_ACCESS_KEY")
        or os.environ.get("S3_SECRET_ACCESS_KEY")
        or env_fallback.get("R2_SECRET_ACCESS_KEY")
        or env_fallback.get("S3_SECRET_ACCESS_KEY")
    )
    if r2_endpoint:
        lines.append(f"S3_ENDPOINT_URL={r2_endpoint}")
        lines.append(f"R2_ENDPOINT_URL={r2_endpoint}")
    if r2_access_key:
        lines.append(f"S3_ACCESS_KEY_ID={r2_access_key}")
        lines.append(f"R2_ACCESS_KEY_ID={r2_access_key}")
    if r2_secret_key:
        lines.append(f"S3_SECRET_ACCESS_KEY={r2_secret_key}")
        lines.append(f"R2_SECRET_ACCESS_KEY={r2_secret_key}")

    # R2/S3 bucket name
    r2_bucket = (
        os.environ.get("R2_BUCKET")
        or os.environ.get("S3_BUCKET")
        or env_fallback.get("R2_BUCKET")
        or env_fallback.get("S3_BUCKET")
    )
    if r2_bucket:
        lines.append(f"R2_BUCKET={r2_bucket}")
        lines.append(f"S3_BUCKET={r2_bucket}")

    r2_version = (
        os.environ.get("R2_VERSION")
        or os.environ.get("S3_VERSION")
        or env_fallback.get("R2_VERSION")
        or env_fallback.get("S3_VERSION")
    )
    if r2_version:
        lines.append(f"R2_VERSION={r2_version}")
        lines.append(f"S3_VERSION={r2_version}")

    # Use remote user's home to avoid path mismatch across SSH users
    lines.append("PHYSICAL_AI_DATA_DIR=$HOME/.physical-ai")

    repo_url = os.environ.get(
        "PERCUS_AI_REPO_URL",
        "https://github.com/percus-ai/physical-ai-features.git",
    )
    if repo_url:
        lines.append(f"PERCUS_AI_REPO_URL={repo_url}")
    repo_ref = os.environ.get("PERCUS_AI_REPO_REF")
    if repo_ref:
        lines.append(f"PERCUS_AI_REPO_REF={repo_ref}")

    if policy_type:
        lines.append(f"PERCUS_AI_POLICY_TYPE={policy_type}")

    # GitHub token for private repo access (physical-ai-features)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        lines.append(f"GH_TOKEN={gh_token}")

    # Supabase credentials for remote status updates
    supabase_url = os.environ.get("SUPABASE_URL") or env_fallback.get("SUPABASE_URL")
    supabase_secret_key = os.environ.get("SUPABASE_SECRET_KEY") or env_fallback.get(
        "SUPABASE_SECRET_KEY"
    )
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY") or env_fallback.get(
        "SUPABASE_ANON_KEY"
    )
    if supabase_url and (supabase_secret_key or supabase_anon_key):
        lines.append(f"SUPABASE_URL={supabase_url}")
        if supabase_secret_key:
            lines.append(f"SUPABASE_SECRET_KEY={supabase_secret_key}")
        if supabase_anon_key:
            lines.append(f"SUPABASE_ANON_KEY={supabase_anon_key}")
    if supabase_access_token:
        lines.append(f"SUPABASE_ACCESS_TOKEN={supabase_access_token}")
    if supabase_refresh_token:
        lines.append(f"SUPABASE_REFRESH_TOKEN={supabase_refresh_token}")
    if supabase_user_id:
        lines.append(f"SUPABASE_USER_ID={supabase_user_id}")

    return "\n".join(lines) + "\n"


def _generate_instance_info_env(
    job_id: str, instance_id: str, auto_delete: bool = True
) -> str:
    """Generate instance_info.env content."""
    lines = [
        f"DATACRUNCH_INSTANCE_ID={instance_id}",
        f"JOB_ID={job_id}",
        f"AUTO_DELETE_INSTANCE={'true' if auto_delete else 'false'}",
    ]
    return "\n".join(lines) + "\n"


# --- Verda/DataCrunch API utilities ---


def _extract_gpu_count(instance_type: str) -> Optional[int]:
    """Extract GPU count from instance type name.

    Instance types follow the pattern: <count><model>.<memory><suffix>
    e.g., "1H100.80S" -> 1, "8A100.80" -> 8

    Args:
        instance_type: Instance type string (e.g., "1H100.80S")

    Returns:
        GPU count as integer, or None if extraction fails
    """
    digits = []
    for ch in instance_type:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def _get_verda_client() -> Optional[VerdaClient]:
    """Get Verda/DataCrunch client (if available)."""
    client_id = os.environ.get("DATACRUNCH_CLIENT_ID")
    client_secret = os.environ.get("DATACRUNCH_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    return VerdaClient(client_id, client_secret)


def _build_verda_storage_item(volume: object, state: str) -> VerdaStorageItem:
    """Convert Verda volume to API response model."""
    return VerdaStorageItem(
        id=getattr(volume, "id", ""),
        name=getattr(volume, "name", None),
        size_gb=int(getattr(volume, "size", 0) or 0),
        status=getattr(volume, "status", "unknown"),
        state=state,
        is_os_volume=bool(getattr(volume, "is_os_volume", False)),
        volume_type=getattr(volume, "type", None),
        location=getattr(volume, "location", None),
        instance_id=getattr(volume, "instance_id", None),
        created_at=getattr(volume, "created_at", None),
        deleted_at=getattr(volume, "deleted_at", None),
    )


def _collect_verda_volumes(client: VerdaClient) -> dict[str, tuple[str, object]]:
    """Collect Verda volumes and map by ID."""
    volumes_by_id: dict[str, tuple[str, object]] = {}
    active_volumes = client.volumes.get()
    for volume in active_volumes:
        volumes_by_id[getattr(volume, "id", "")] = ("active", volume)
    trash_volumes = client.volumes.get_in_trash()
    for volume in trash_volumes:
        volumes_by_id[getattr(volume, "id", "")] = ("deleted", volume)
    return volumes_by_id


def _gpu_count_from_instance_type(instance_type: object) -> int:
    gpu = getattr(instance_type, "gpu", None) or {}
    count = gpu.get("count") or gpu.get("number_of_gpus") or gpu.get("gpu_count") or 0
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


def _select_cpu_instance_type(client: VerdaClient) -> str:
    instance_types = client.instance_types.get()
    cpu_types = [t for t in instance_types if _gpu_count_from_instance_type(t) == 0]
    if not cpu_types:
        raise HTTPException(
            status_code=503, detail="CPUインスタンスタイプが見つかりません"
        )
    cpu_types.sort(key=lambda t: getattr(t, "price_per_hour", float("inf")))
    return cpu_types[0].instance_type


def _pick_os_volume_for_instance(
    volumes_by_id: dict[str, tuple[str, object]],
    instance_id: str,
) -> Optional[tuple[str, object]]:
    candidates: list[tuple[str, object]] = []
    os_candidates: list[tuple[str, object]] = []
    for _, (state, volume) in volumes_by_id.items():
        if getattr(volume, "instance_id", None) != instance_id:
            continue
        item = (state, volume)
        candidates.append(item)
        if getattr(volume, "is_os_volume", False):
            os_candidates.append(item)
    if os_candidates:
        return os_candidates[0]
    if candidates:
        return candidates[0]
    return None


def _pick_os_volume_for_job(
    volumes_by_id: dict[str, tuple[str, object]],
    job_id: str,
) -> Optional[tuple[str, object]]:
    job_prefix = f"train-{job_id[:16]}"
    matches: list[tuple[str, object]] = []
    os_matches: list[tuple[str, object]] = []
    for _, (state, volume) in volumes_by_id.items():
        name = getattr(volume, "name", None) or ""
        if job_prefix not in name:
            continue
        item = (state, volume)
        matches.append(item)
        if getattr(volume, "is_os_volume", False):
            os_matches.append(item)
    candidates = os_matches or matches
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: getattr(item[1], "created_at", "") or "", reverse=True
    )
    return candidates[0]


def _wait_for_volume_restore(
    client: VerdaClient, volume_id: str, timeout_sec: int = 120
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
            status = getattr(volume, "status", "") or ""
            if status.lower() not in ("deleted", "deleting", "trash"):
                return
        except Exception:
            pass
        time.sleep(5)
    raise HTTPException(
        status_code=504, detail="ストレージ復活の完了待ちがタイムアウトしました"
    )


def _ensure_volume_detached(
    client: VerdaClient, volume_id: str, timeout_sec: int = 120
) -> None:
    try:
        volume = client.volumes.get_by_id(volume_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404, detail=f"ストレージ取得に失敗しました: {exc}"
        ) from exc

    if getattr(volume, "instance_id", None) is None:
        return

    try:
        client.volumes.detach(volume_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"ストレージのデタッチに失敗しました: {exc}"
        ) from exc

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
            if getattr(volume, "instance_id", None) is None:
                return
        except Exception:
            pass
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="ストレージのデタッチ完了待ちがタイムアウトしました"
    )


def _wait_for_volume_detached(
    client: VerdaClient, volume_id: str, timeout_sec: int = 180
) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            volume = client.volumes.get_by_id(volume_id)
        except Exception as exc:
            raise HTTPException(
                status_code=404, detail=f"ストレージ取得に失敗しました: {exc}"
            ) from exc
        if getattr(volume, "instance_id", None) is None:
            return
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="ストレージのデタッチ完了待ちがタイムアウトしました"
    )


def _wait_for_instance_offline(
    client: VerdaClient,
    instance_id: str,
    timeout_sec: int = 120,
    allowed_statuses: Optional[set[str]] = None,
) -> None:
    if allowed_statuses is None:
        allowed_statuses = {"offline", "discontinued", "deleted"}
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            instance = client.instances.get_by_id(instance_id)
            status = getattr(instance, "status", "") or ""
            if status in allowed_statuses:
                return
        except Exception:
            return
        time.sleep(5)

    raise HTTPException(
        status_code=504, detail="インスタンス停止の完了待ちがタイムアウトしました"
    )


def _restore_verda_volumes(client: VerdaClient, volume_ids: list[str]) -> None:
    """Restore volumes from trash via Verda API."""
    payload = {"action": "restore", "id": volume_ids}
    client._http_client.put("/volumes", json=payload)


def _chunk_list(items: list[str], chunk_size: int = 20) -> list[list[str]]:
    """Split items into smaller chunks."""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


_verda_client_local = threading.local()


def _get_thread_verda_client() -> Optional[VerdaClient]:
    """Get thread-local Verda client."""
    client = getattr(_verda_client_local, "client", None)
    if client is None:
        client = _get_verda_client()
        _verda_client_local.client = client
    return client


def _perform_verda_volume_action(
    action: str, volume_id: str, is_permanent: bool
) -> None:
    """Perform a Verda volume action for a single volume."""
    client = _get_thread_verda_client()
    if not client:
        raise RuntimeError(
            "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)"
        )

    if action == "delete":
        client.volumes.delete(volume_id, is_permanent=is_permanent)
    elif action == "restore":
        _restore_verda_volumes(client, [volume_id])
    else:
        raise ValueError(f"Unsupported action: {action}")


def _perform_verda_volume_action_batch(
    action: str,
    volume_ids: list[str],
    is_permanent: bool,
) -> None:
    """Perform a Verda volume action for a batch of volumes."""
    client = _get_thread_verda_client()
    if not client:
        raise RuntimeError(
            "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)"
        )

    if action == "delete":
        client.volumes.delete(volume_ids, is_permanent=is_permanent)
    elif action == "restore":
        _restore_verda_volumes(client, volume_ids)
    else:
        raise ValueError(f"Unsupported action: {action}")


def _check_instance_via_api(instance_id: str) -> Optional[str]:
    """Check instance status via Verda API.

    Returns:
        Instance status string or None if unavailable
    """
    client = _get_verda_client()
    if not client:
        return None

    try:
        instance = client.instances.get_by_id(instance_id)
        return instance.status
    except Exception:
        return None


async def _refresh_job_status_from_instance(job_data: dict) -> Optional[str]:
    instance_id = job_data.get("instance_id")
    if not instance_id:
        return None
    instance_status = _check_instance_via_api(instance_id)
    if instance_status is None:
        job_data["status"] = "terminated"
        job_data["termination_reason"] = "INSTANCE_NOT_FOUND"
        job_data["completed_at"] = datetime.now().isoformat()
        await _save_job(job_data)
        return instance_status
    if instance_status in ("offline", "error", "discontinued"):
        job_data["status"] = "terminated"
        job_data["termination_reason"] = "INSTANCE_TERMINATED"
        job_data["completed_at"] = datetime.now().isoformat()
        await _save_job(job_data)
        return instance_status
    return instance_status


def _find_latest_running_revive_instance(client: VerdaClient, job_id: str):
    """Find latest running revive instance for a job."""
    target_hostname = f"revive-{job_id[:8]}"
    try:
        instances = client.instances.get()
    except Exception:
        return None

    candidates = []
    for inst in instances:
        hostname = str(getattr(inst, "hostname", "") or "").strip()
        status = str(getattr(inst, "status", "") or "").strip().lower()
        ip = str(getattr(inst, "ip", "") or "").strip()
        if hostname != target_hostname:
            continue
        if status != "running":
            continue
        if not ip:
            continue
        candidates.append(inst)

    if not candidates:
        return None

    def _created_at_key(inst) -> str:
        return str(getattr(inst, "created_at", "") or "")

    return max(candidates, key=_created_at_key)


async def _refresh_job_ssh_target_if_needed(job_data: dict) -> dict:
    """Refresh job SSH target to running revived instance when stale."""
    job_id = str(job_data.get("job_id") or "").strip()
    if not job_id:
        return job_data

    instance_id = str(job_data.get("instance_id") or "").strip()
    ip = str(job_data.get("ip") or "").strip()
    if instance_id:
        current_status = _check_instance_via_api(instance_id)
    else:
        current_status = None

    stale_statuses = {"offline", "error", "discontinued", "deleted"}
    needs_refresh = (not ip) or (current_status in stale_statuses)
    if not needs_refresh:
        return job_data

    client = _get_verda_client()
    if not client:
        return job_data
    revive_instance = _find_latest_running_revive_instance(client, job_id)
    if not revive_instance:
        return job_data

    revive_id = str(getattr(revive_instance, "id", "") or "").strip()
    revive_ip = str(getattr(revive_instance, "ip", "") or "").strip()
    if not revive_id or not revive_ip:
        return job_data

    old_instance_id = instance_id or "none"
    old_ip = ip or "none"
    ssh_private_key = _select_preferred_ssh_private_key(job_data.get("ssh_private_key"))
    ssh_user = str(job_data.get("ssh_user") or "").strip() or _get_default_ssh_user()

    job_data["instance_id"] = revive_id
    job_data["ip"] = revive_ip
    job_data["ssh_user"] = ssh_user
    job_data["ssh_private_key"] = ssh_private_key
    await _save_job(job_data)
    logger.info(
        "Rebound job SSH target to revived instance: job_id=%s old_instance_id=%s old_ip=%s new_instance_id=%s new_ip=%s",
        job_id,
        old_instance_id,
        old_ip,
        revive_id,
        revive_ip,
    )
    return job_data


async def _load_job(job_id: str, include_deleted: bool = False) -> Optional[dict]:
    """Load job from DB."""
    async def _fetch_with(client: AsyncClient) -> list[dict]:
        response = await client.table(DB_TABLE).select("*").eq("job_id", job_id).execute()
        return response.data or []

    client = await get_supabase_async_client()
    try:
        records = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while loading training job %s; retrying with service key",
            job_id,
        )
        records = await _fetch_with(service_client)

    if not records:
        return None
    record = records[0]
    if not include_deleted and record.get("deleted_at"):
        return None
    return record


async def _save_job(job_data: dict) -> None:
    """Upsert job into DB."""
    job_data["updated_at"] = datetime.now().isoformat()

    fixed_fields = {
        "job_id",
        "job_name",
        "model_id",
        "policy_type",
        "dataset_id",
        "profile_instance_id",
        "profile_snapshot",
        "status",
        "failure_reason",
        "termination_reason",
        "cleanup_status",
        "deleted_at",
        "training_config",
        "author",
        "base_checkpoint",
        "notes",
        "instance_id",
        "ip",
        "mode",
        "ssh_user",
        "ssh_private_key",
        "remote_base_dir",
        "checkpoint_repo_id",
        "gpu_model",
        "gpus_per_instance",
        "exit_code",
        "completed_at",
        "created_at",
        "updated_at",
        "started_at",
        "summary",
        "early_stopping",
    }
    record = {k: job_data.get(k) for k in fixed_fields if k in job_data}
    job_id = record.get("job_id")
    if not job_id:
        raise ValueError("Missing job_id in record")

    owner_user_id = (
        str(job_data.get("owner_user_id") or "").strip()
        or str((get_supabase_session() or {}).get("user_id") or "").strip()
    )

    async def _upsert_with(client: AsyncClient) -> None:
        existing = (
            await client.table(DB_TABLE).select("job_id").eq("job_id", job_id).execute()
        ).data or []
        if existing:
            update_record = {
                k: v
                for k, v in record.items()
                if k not in {"job_id", "owner_user_id"}
            }
            if update_record:
                await client.table(DB_TABLE).update(update_record).eq("job_id", job_id).execute()
            return

        insert_record = dict(record)
        if "owner_user_id" not in insert_record or not insert_record.get("owner_user_id"):
            if not owner_user_id:
                raise ValueError("owner_user_id is required for new training job insert")
            insert_record["owner_user_id"] = owner_user_id
        await client.table(DB_TABLE).insert(insert_record).execute()

    client = await get_supabase_async_client()
    try:
        await _upsert_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while saving training job %s; retrying with service key",
            job_id,
        )
        await _upsert_with(service_client)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Async job helper called from running event loop.")


def _load_job_sync(job_id: str, include_deleted: bool = False) -> Optional[dict]:
    return _run_async(_load_job(job_id, include_deleted=include_deleted))


def _save_job_sync(job_data: dict) -> None:
    _run_async(_save_job(job_data))


def _update_cleanup_status_sync(job_id: str, status: str) -> None:
    _run_async(_update_cleanup_status(job_id, status))


def _resolve_profile_info_sync(
    dataset_id: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    return _run_async(_resolve_profile_info(dataset_id))


async def _update_cleanup_status(job_id: str, status: str) -> None:
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    job_data["cleanup_status"] = status
    await _save_job(job_data)


async def _resolve_profile_info(
    dataset_id: Optional[str],
) -> tuple[Optional[str], Optional[dict]]:
    if not dataset_id:
        return None, None

    async def _fetch_with(client: AsyncClient) -> list[dict]:
        return (
            await client.table("datasets")
            .select("profile_instance_id,profile_snapshot")
            .eq("id", dataset_id)
            .execute()
        ).data or []

    client = await get_supabase_async_client()
    try:
        rows = await _fetch_with(client)
    except Exception as exc:
        if not _is_jwt_expired_error(exc):
            raise
        service_client = await _get_service_db_client()
        if service_client is None:
            raise
        logger.warning(
            "JWT expired while resolving dataset profile info %s; retrying with service key",
            dataset_id,
        )
        rows = await _fetch_with(service_client)

    if rows:
        return rows[0].get("profile_instance_id"), rows[0].get("profile_snapshot")
    return None, None


async def _upsert_model_for_job(job_data: dict) -> None:
    model_id = job_data.get("model_id") or job_data.get("job_id")
    profile_instance_id = job_data.get("profile_instance_id")
    profile_snapshot = job_data.get("profile_snapshot")
    if not profile_instance_id:
        profile_instance_id, profile_snapshot = await _resolve_profile_info(
            job_data.get("dataset_id")
        )
    if not model_id:
        logger.warning("Model upsert skipped (model_id missing)")
        return

    training_cfg = job_data.get("training_config") or {}
    training_params = (
        training_cfg.get("training") if isinstance(training_cfg, dict) else {}
    )
    policy_type = job_data.get("policy_type")
    if not policy_type and isinstance(training_cfg, dict):
        policy = training_cfg.get("policy") or {}
        policy_type = policy.get("type")

    checkpoint_entry = None
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()
        lookup_names: list[str] = []
        for candidate in (
            str(job_data.get("job_id") or "").strip(),
            str(job_data.get("model_id") or "").strip(),
            str(model_id or "").strip(),
        ):
            if candidate and candidate not in lookup_names:
                lookup_names.append(candidate)
        for lookup_name in lookup_names:
            checkpoint_entry = checkpoint_mgr.get_job_info(lookup_name)
            if checkpoint_entry is not None:
                break
    except Exception as exc:
        logger.debug("Failed to resolve checkpoint entry for model upsert %s: %s", model_id, exc)

    now = datetime.now().isoformat()
    training_steps = training_params.get("steps")
    if checkpoint_entry is not None:
        latest_step = int(getattr(checkpoint_entry, "latest_step", 0) or 0)
        if latest_step > 0:
            training_steps = latest_step
    payload = {
        "id": model_id,
        "name": model_id,
        "dataset_id": job_data.get("dataset_id"),
        "profile_instance_id": profile_instance_id,
        "profile_snapshot": profile_snapshot,
        "policy_type": policy_type,
        "training_steps": training_steps,
        "batch_size": training_params.get("batch_size"),
        "source": "r2",
        "status": "active",
        "created_at": job_data.get("created_at") or now,
        "updated_at": now,
    }
    explicit_size = job_data.get("model_size_bytes")
    if explicit_size is not None:
        try:
            payload["size_bytes"] = max(int(explicit_size), 0)
        except (TypeError, ValueError):
            pass
    elif checkpoint_entry is not None:
        size_mb = float(getattr(checkpoint_entry, "size_mb", 0.0) or 0.0)
        if size_mb >= 0:
            payload["size_bytes"] = int(size_mb * 1024 * 1024)
    content_hash = str(job_data.get("model_content_hash") or "").strip()
    if content_hash:
        payload["content_hash"] = content_hash
    await upsert_with_owner("models", "id", payload)


async def _archive_job_metrics(job_id: str) -> bool:
    """Archive job metrics from DB to R2, then delete DB records.

    Returns True if archive succeeded or no metrics to archive.
    """
    client = await get_supabase_async_client()
    try:
        response = (
            await client.table("training_job_metrics")
            .select("job_id,split,step,ts,loss,metrics")
            .eq("job_id", job_id)
            .order("split", desc=False)
            .order("step", desc=False)
            .execute()
        )
    except Exception as exc:
        logger.warning("Failed to fetch metrics for archival (%s): %s", job_id, exc)
        return False
    metrics = response.data or []
    if not metrics:
        return True

    r2 = _get_logs_r2_sync_service()
    if not r2:
        logger.warning("R2 service unavailable; skipping metrics archival for %s", job_id)
        return False

    payload = json.dumps(metrics, ensure_ascii=False, default=str)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_metrics/{job_id}/metrics.json"
    try:
        r2.s3.client.put_object(
            Bucket=r2.bucket,
            Key=key,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("Archived %d metrics records to R2 for %s", len(metrics), job_id)
    except Exception as exc:
        logger.warning("Failed to upload metrics to R2 for %s: %s", job_id, exc)
        return False

    try:
        await client.table("training_job_metrics").delete().eq("job_id", job_id).execute()
        logger.info("Deleted archived metrics from DB for %s", job_id)
    except Exception as exc:
        logger.warning("Failed to delete archived metrics from DB for %s: %s", job_id, exc)

    return True


def _get_metrics_from_r2(job_id: str) -> Optional[list[dict]]:
    """Fetch archived metrics JSON from R2."""
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_metrics/{job_id}/metrics.json"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, list) else None
    except Exception:
        return None


async def _mark_job_completed(
    job_id: str, termination_reason: str = "REMOTE_EXIT"
) -> None:
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    if job_data.get("status") not in ("running", "starting", "deploying"):
        return
    job_data["status"] = "completed"
    job_data["termination_reason"] = termination_reason
    job_data["completed_at"] = datetime.now().isoformat()
    if not job_data.get("model_id"):
        job_data["model_id"] = job_data.get("job_id")
    await _save_job(job_data)
    await _upsert_model_for_job(job_data)
    await _archive_job_metrics(job_id)


async def _list_jobs(days: int = 365) -> list[dict]:
    """List jobs from DB.

    Args:
        days: Return jobs from past N days.
              Running/starting jobs are always included.
    """
    client = await get_supabase_async_client()
    response = (
        await client.table(DB_TABLE).select("*").is_("deleted_at", "null").execute()
    )
    jobs = response.data or []

    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = []
    for job in jobs:
        status = job.get("status")
        if status in ("running", "starting"):
            filtered.append(job)
            continue
        created_at = job.get("created_at")
        if not created_at:
            continue
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            if created >= cutoff_date:
                filtered.append(job)
        except Exception:
            continue

    filtered.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return filtered


# --- SSH utilities for job monitoring (uses SSHConnection) ---

# tmux session names for setup and training
TMUX_SETUP_SESSION_NAME = "instance_setup"
TMUX_TRAIN_SESSION_NAME = "training_run"

# Timeout constants
IP_WAIT_TIMEOUT_SEC = 900  # 15 minutes to wait for IP assignment
SSH_WAIT_TIMEOUT_SEC = 300  # 5 minutes to wait for SSH to be ready
INSTANCE_RUNNING_WAIT_TIMEOUT_SEC = 600  # 10 minutes to wait for instance running
SETUP_TIMEOUT_SEC = 3600  # Max time to run setup_env.sh
IP_POLL_INTERVAL_SEC = 15
INSTANCE_STATUS_POLL_INTERVAL_SEC = 10
SSH_CONNECT_ATTEMPT_TIMEOUT_SEC = 30
SSH_CONNECT_RETRY_INTERVAL_SEC = 10
INSTANCE_TERMINAL_STATUSES = {"offline", "error", "discontinued", "deleted"}


def _get_setup_log_file_path(job_data: dict) -> str:
    """Get the remote setup log file path for a job.

    Args:
        job_data: Job data dict containing remote_base_dir and mode

    Returns:
        Full path to the setup log file on the remote instance
    """
    mode = job_data.get("mode", "train")
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    return f"{remote_base_dir}/run/setup_env_{mode}.log"


def _get_training_log_file_path(job_data: dict) -> str:
    """Get the remote training log file path for a job.

    Args:
        job_data: Job data dict containing remote_base_dir and mode

    Returns:
        Full path to the training log file on the remote instance
    """
    mode = job_data.get("mode", "train")
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    return f"{remote_base_dir}/run/training_{mode}.log"


def _get_remote_checkpoint_root(job_data: dict) -> str:
    """Get remote checkpoints directory for a training job."""
    remote_base_dir = str(job_data.get("remote_base_dir") or "/root/.physical-ai").strip()
    job_id = str(job_data.get("job_id") or job_data.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("job_id is missing")

    training_config = job_data.get("training_config")
    if isinstance(training_config, dict):
        output_cfg = training_config.get("output")
        if isinstance(output_cfg, dict):
            output_dir = str(output_cfg.get("output_dir") or "").strip()
            if output_dir:
                if output_dir.startswith("/"):
                    return f"{output_dir.rstrip('/')}/checkpoints"
                normalized = output_dir.lstrip("./")
                return f"{remote_base_dir.rstrip('/')}/{normalized.rstrip('/')}/checkpoints"

    return f"{remote_base_dir.rstrip('/')}/outputs/train/{job_id}/checkpoints"


def _list_remote_checkpoint_dirs(job_data: dict) -> tuple[list[str], str]:
    """List numeric checkpoint directory names on remote instance."""
    checkpoint_root = _get_remote_checkpoint_root(job_data)
    conn = _get_ssh_connection_for_job(job_data, timeout=30)
    if not conn:
        raise RuntimeError("SSH接続に失敗しました。インスタンス状態を確認してください。")

    try:
        root_quoted = shlex.quote(checkpoint_root)
        command = (
            f"if [ ! -d {root_quoted} ]; then exit 3; fi; "
            f"find {root_quoted} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' "
            "| grep -E '^[0-9]+$' | sort -n"
        )
        exit_code, stdout, stderr = conn.exec_command(command, timeout=30)
        if exit_code == 3:
            raise RuntimeError(f"チェックポイントディレクトリが見つかりません: {checkpoint_root}")
        if exit_code != 0:
            msg = (stderr or stdout or "unknown error").strip()
            raise RuntimeError(f"チェックポイント一覧の取得に失敗しました: {msg}")
        names = [line.strip() for line in stdout.splitlines() if line.strip().isdigit()]
        return names, checkpoint_root
    finally:
        conn.disconnect()


def _register_job_for_checkpoint_if_needed(
    checkpoint_mgr: "CheckpointIndexManager", job_data: dict
) -> None:
    job_id = str(job_data.get("job_id") or job_data.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("job_id is missing")

    existing = checkpoint_mgr.get_job_info(job_id)
    if existing:
        return

    training_config = job_data.get("training_config")
    config = training_config if isinstance(training_config, dict) else {}
    policy_cfg = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    dataset_cfg = config.get("dataset") if isinstance(config.get("dataset"), dict) else {}

    policy_type = str(job_data.get("policy_type") or policy_cfg.get("type") or "").strip()
    dataset_id = str(job_data.get("dataset_id") or dataset_cfg.get("id") or "").strip()
    if not policy_type or not dataset_id:
        raise RuntimeError(
            "ジョブメタデータ不足のためcheckpointを登録できません。"
            "policy_type/dataset_id を確認してください。"
        )

    pretrained_path = policy_cfg.get("pretrained_path")
    author = str(job_data.get("author") or _default_author_user_id()).strip() or "unknown"
    dataset_info = _get_dataset_info_from_manifest(dataset_id)

    ok = checkpoint_mgr.register_job(
        job_name=job_id,
        policy_type=policy_type,
        dataset_id=dataset_id,
        pretrained_path=pretrained_path,
        dataset_info=dataset_info,
        author=author,
        training_config=config,
    )
    if not ok:
        raise RuntimeError("checkpoint index へのジョブ登録に失敗しました")


def _list_r2_file_objects(s3_manager: object, s3_path: str) -> list[dict]:
    objects = s3_manager.list_objects(s3_path)
    files: list[dict] = []
    for obj in objects:
        key = str(obj.get("Key") or "").strip()
        if not key or key.endswith("/"):
            continue
        files.append(obj)
    return files


def _ensure_model_artifact_in_r2_from_checkpoint(
    checkpoint_mgr: "CheckpointIndexManager",
    *,
    job_id: str,
    model_id: str,
    step: int,
) -> tuple[str, int, bool]:
    """Ensure models/{model_id} exists by copying from checkpoint pretrained_model."""
    sync = checkpoint_mgr.sync
    bucket = sync.bucket
    prefix = sync._get_prefix()
    source_prefix = f"{prefix}checkpoints/{job_id}/step_{step:06d}/pretrained_model/"
    target_prefix = f"{prefix}models/{model_id}/"
    source_path = f"s3://{bucket}/{source_prefix}"
    target_path = f"s3://{bucket}/{target_prefix}"

    existing_target_files = _list_r2_file_objects(sync.s3, target_path)
    if existing_target_files:
        size_bytes = sum(max(int(obj.get("Size") or 0), 0) for obj in existing_target_files)
        return target_path.rstrip("/"), size_bytes, False

    source_files = _list_r2_file_objects(sync.s3, source_path)
    if not source_files:
        raise RuntimeError(
            f"モデル生成元が見つかりません: {source_path} (pretrained_model が必要です)"
        )

    for obj in source_files:
        source_key = str(obj.get("Key") or "").strip()
        if not source_key.startswith(source_prefix):
            continue
        relative = source_key[len(source_prefix):].lstrip("/")
        if not relative:
            continue
        target_key = f"{target_prefix}{relative}"
        sync.s3.client.copy(
            {"Bucket": bucket, "Key": source_key},
            bucket,
            target_key,
        )

    size_bytes = sum(max(int(obj.get("Size") or 0), 0) for obj in source_files)
    return target_path.rstrip("/"), size_bytes, True


async def _upload_selected_remote_checkpoint_with_progress(
    job_id: str,
    checkpoint_name: str,
    emit_progress: Callable[[dict], None],
) -> dict:
    emit_progress({"type": "start", "message": "チェックポイント登録を開始しました"})

    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_data = await _refresh_job_ssh_target_if_needed(job_data)

    checkpoint_name = str(checkpoint_name or "").strip()
    if not checkpoint_name.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"checkpoint_name must be numeric: {checkpoint_name}",
        )

    step = int(checkpoint_name)
    model_id = str(job_data.get("model_id") or job_id).strip()
    if not model_id:
        raise HTTPException(
            status_code=500,
            detail="model_id を生成できないためDB登録できませんでした。",
        )
    checkpoint_mgr = _get_checkpoint_index_manager()
    existing_steps = checkpoint_mgr.get_job_steps(job_id)

    if step not in existing_steps:
        checkpoint_root = _get_remote_checkpoint_root(job_data)
        remote_checkpoint_path = f"{checkpoint_root.rstrip('/')}/{checkpoint_name}"

        emit_progress({"type": "connecting_ssh", "message": "インスタンスへ接続中..."})
        conn = _get_ssh_connection_for_job(job_data, timeout=30)
        if not conn:
            raise HTTPException(
                status_code=503,
                detail="SSH接続に失敗しました。インスタンスが起動中か確認してください。",
            )

        local_checkpoint_path: Optional[Path] = None
        temp_dir_obj: Optional[tempfile.TemporaryDirectory] = None
        try:
            emit_progress({"type": "validating", "message": "checkpoint存在を確認中..."})
            check_cmd = f"test -d {shlex.quote(remote_checkpoint_path)}"
            exit_code, _, _ = conn.exec_command(check_cmd, timeout=15)
            if exit_code != 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Remote checkpoint not found: {remote_checkpoint_path}",
                )

            emit_progress(
                {
                    "type": "downloading",
                    "message": "checkpointをバックエンドへ転送中...",
                    "checkpoint_name": checkpoint_name,
                }
            )
            temp_dir_obj = tempfile.TemporaryDirectory(prefix=f"checkpoint_upload_{job_id}_")
            local_checkpoint_path = Path(temp_dir_obj.name) / checkpoint_name
            conn.download_directory(remote_checkpoint_path, local_checkpoint_path)

            emit_progress({"type": "registering", "message": "checkpoint index登録中..."})
            _register_job_for_checkpoint_if_needed(checkpoint_mgr, job_data)

            emit_progress({"type": "uploading", "message": "R2へアップロード中..."})
            ok, msg = checkpoint_mgr.upload_step_checkpoint(
                job_name=job_id,
                step=step,
                local_checkpoint_path=local_checkpoint_path,
                update_last=True,
            )
            if not ok:
                raise HTTPException(
                    status_code=500,
                    detail=f"Checkpoint upload failed: {msg}",
                )
        finally:
            conn.disconnect()
            if temp_dir_obj is not None:
                temp_dir_obj.cleanup()
    else:
        emit_progress(
            {
                "type": "uploaded",
                "message": "R2には既に登録済みのためアップロードをスキップしました",
                "checkpoint_name": checkpoint_name,
                "step": step,
            }
        )

    prefix = checkpoint_mgr.sync._get_prefix()
    r2_step_path = (
        f"s3://{checkpoint_mgr.sync.bucket}/{prefix}checkpoints/{job_id}/step_{step:06d}"
    )
    emit_progress(
        {
            "type": "uploaded",
            "message": "R2登録が完了しました",
            "checkpoint_name": checkpoint_name,
            "step": step,
        }
    )
    emit_progress(
        {
            "type": "uploading_model",
            "message": "推論モデルをR2へ反映中...",
        }
    )
    try:
        model_r2_path, model_size_bytes, copied_model = _ensure_model_artifact_in_r2_from_checkpoint(
            checkpoint_mgr,
            job_id=job_id,
            model_id=model_id,
            step=step,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"モデルアーティファクトのR2反映に失敗しました: {exc}",
        ) from exc
    emit_progress(
        {
            "type": "model_uploaded",
            "message": (
                "推論モデルをR2へ反映しました"
                if copied_model
                else "推論モデルは既にR2に存在します"
            ),
            "model_id": model_id,
            "model_r2_path": model_r2_path,
        }
    )
    emit_progress(
        {
            "type": "registering_model",
            "message": "モデルをDBへ登録中...",
        }
    )
    job_data["model_id"] = model_id
    job_data["model_size_bytes"] = model_size_bytes
    await _save_job(job_data)
    try:
        await _upsert_model_for_job(job_data)
    except Exception as exc:
        logger.exception(
            "Remote checkpoint upload succeeded but model DB upsert failed: job_id=%s step=%s",
            job_id,
            step,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "R2登録は完了しましたが、モデルのDB登録に失敗しました: "
                f"{exc}. 同じチェックポイントで再実行してください。"
            ),
        ) from exc
    emit_progress(
        {
            "type": "model_registered",
            "message": "モデルDB登録が完了しました",
            "model_id": model_id,
        }
    )
    return RemoteCheckpointUploadResponse(
        job_id=job_id,
        checkpoint_name=checkpoint_name,
        step=step,
        r2_step_path=r2_step_path,
        model_id=model_id,
        db_registered=True,
        message="チェックポイントをR2/DBに登録し、推論モデルも反映しました",
    ).model_dump()


def _get_ssh_connection_for_job(
    job_data: dict, timeout: int = 30
) -> Optional[SSHConnection]:
    """Get SSHConnection for job instance.

    Args:
        job_data: Job data dict containing ip, ssh_user, ssh_private_key
        timeout: Connection timeout in seconds

    Returns:
        Connected SSHConnection or None if connection fails
    """
    ip = job_data.get("ip")
    if not ip:
        return None

    users = _build_ssh_user_candidates(job_data.get("ssh_user", _get_default_ssh_user()))
    key_candidates = _build_ssh_private_key_candidates(job_data.get("ssh_private_key"))
    if not key_candidates:
        logger.warning(
            "No usable SSH private key found for job %s (saved=%s, env=%s)",
            job_data.get("job_id"),
            job_data.get("ssh_private_key"),
            os.environ.get("VERDA_SSH_PRIVATE_KEY"),
        )
        return None

    last_error: Optional[Exception] = None
    for user in users:
        for key_path in key_candidates:
            try:
                conn = SSHConnection(
                    host=ip,
                    user=user,
                    private_key_path=key_path,
                )
                conn.connect(timeout_sec=timeout)
                return conn
            except SystemExit as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc

    if last_error:
        logger.warning(
            "SSH connection failed for job %s (ip=%s, users=%s, keys=%s): %s",
            job_data.get("job_id"),
            ip,
            ",".join(users),
            ",".join(str(p) for p in key_candidates),
            last_error,
        )
        logger.debug(
            "Failed to connect SSH for job %s with all key/user candidates: %s",
            job_data.get("job_id"),
            last_error,
        )
    return None


def _check_remote_status(job_data: dict) -> str:
    """Check remote process status via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return "unreachable"

    try:
        train_cmd = f"tmux has-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'"
        exit_code, stdout, stderr = conn.exec_command(train_cmd)
        train_status = stdout.strip()
        if train_status == "running":
            return "running"

        setup_cmd = f"tmux has-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'"
        exit_code, stdout, stderr = conn.exec_command(setup_cmd)
        setup_status = stdout.strip()
        if setup_status == "running":
            return "starting"
        return "stopped"
    except Exception:
        return "error"
    finally:
        conn.disconnect()


def _get_remote_logs(
    job_data: dict, lines: int = 100, log_type: str = "training"
) -> Optional[str]:
    """Get remote logs via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return None

    try:
        if log_type == "setup":
            log_file = _get_setup_log_file_path(job_data)
        else:
            log_file = _get_training_log_file_path(job_data)
        cmd = f"tail -n {lines} {log_file} 2>/dev/null || echo '[Log file not found]'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout
    except Exception:
        return None
    finally:
        conn.disconnect()


def _get_remote_log_file(
    job_data: dict,
    log_type: str = "training",
    timeout: int = 15,
) -> Optional[str]:
    try:
        conn = _get_ssh_connection_for_job(job_data, timeout=timeout)
    except SystemExit:
        return None
    if not conn:
        return None
    try:
        if log_type == "setup":
            log_file = _get_setup_log_file_path(job_data)
        else:
            log_file = _get_training_log_file_path(job_data)
        cmd = f"cat {log_file} 2>/dev/null || echo '[Log file not found]'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout
    except Exception:
        return None
    finally:
        conn.disconnect()


def _should_try_r2_first(job_data: dict) -> bool:
    cleanup_status = job_data.get("cleanup_status")
    if cleanup_status in ("running", "done"):
        return True
    if job_data.get("status") in ("completed", "failed", "stopped", "terminated"):
        return True
    if not job_data.get("ip"):
        return True
    return False


def _get_log_file_name(job_data: dict, log_type: str) -> str:
    mode = job_data.get("mode", "train")
    if log_type == "setup":
        return f"setup_env_{mode}.log"
    return f"training_{mode}.log"


def _get_logs_r2_sync_service() -> Optional["R2SyncService"]:
    try:
        from percus_ai.storage import ManifestManager, R2SyncService

        manifest = ManifestManager()
        manifest.init_directories()
        bucket = os.getenv("R2_BUCKET", "percus-data")
        version = os.getenv("R2_VERSION", "v2")
        return R2SyncService(manifest, bucket, version=version)
    except Exception as e:
        logger.warning(f"Failed to init R2 sync service for logs: {e}")
        return None


def _upload_log_file_to_r2(r2: "R2SyncService", local_path: Path, job_id: str) -> bool:
    try:
        prefix = f"{r2.version}/" if r2.version else ""
        key = f"{prefix}training_logs/{job_id}/{local_path.name}"
        r2.s3.client.upload_file(str(local_path), r2.bucket, key)
        return True
    except Exception as e:
        logger.warning(f"Failed to upload log to R2: {e}")
        return False


async def _upload_remote_logs_to_r2(conn: SSHConnection, job_data: dict) -> None:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return
    remote_base_dir = job_data.get("remote_base_dir", "/root/.physical-ai")
    remote_run_dir = f"{remote_base_dir}/run"
    job_data["log_r2_prefix"] = f"training_logs/{job_id}/"
    await _save_job(job_data)

    for log_type in ("setup", "training"):
        log_name = _get_log_file_name(job_data, log_type)
        remote_path = f"{remote_run_dir}/{log_name}"
        local_path = Path("/tmp") / f"{job_id}_{log_name}"
        try:
            conn.download_file(remote_path, local_path)
        except Exception as e:
            logger.warning(f"Failed to download log {remote_path}: {e}")
            continue
        _upload_log_file_to_r2(r2, local_path, job_id)
        try:
            local_path.unlink()
        except Exception:
            pass


def _tail_text_lines(text: str, lines: int) -> str:
    if lines <= 0:
        return ""
    parts = text.splitlines()
    if len(parts) <= lines:
        return "\n".join(parts) + ("\n" if text.endswith("\n") else "")
    return "\n".join(parts[-lines:]) + "\n"


def _get_logs_from_r2(job_data: dict, lines: int, log_type: str) -> Optional[str]:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return None
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        body = obj["Body"].read().decode("utf-8", errors="replace")
        return _tail_text_lines(body, lines)
    except Exception as e:
        logger.warning(f"Failed to fetch log from R2: {e}")
        return None


def _get_full_logs_from_r2(job_data: dict, log_type: str) -> Optional[str]:
    r2 = _get_logs_r2_sync_service()
    if not r2:
        return None
    job_id = job_data.get("job_id") or job_data.get("id")
    if not job_id:
        return None
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        obj = r2.s3.client.get_object(Bucket=r2.bucket, Key=key)
        return obj["Body"].read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Failed to fetch full log from R2: {e}")
        return None


def _check_logs_in_r2(job_data: dict, log_type: str) -> dict:
    r2 = _get_logs_r2_sync_service()
    job_id = job_data.get("job_id") or job_data.get("id")
    if not r2 or not job_id:
        return {"exists": False, "key": None, "error": "r2_unavailable"}
    log_name = _get_log_file_name(job_data, log_type)
    prefix = f"{r2.version}/" if r2.version else ""
    key = f"{prefix}training_logs/{job_id}/{log_name}"
    try:
        r2.s3.client.head_object(Bucket=r2.bucket, Key=key)
        return {"exists": True, "key": key, "error": None}
    except Exception as e:
        return {"exists": False, "key": key, "error": str(e)}


async def _get_remote_progress(job_id: str) -> Optional[dict]:
    """Get training progress from Supabase metrics."""
    client = await get_supabase_async_client()
    response = (
        await client.table("training_job_metrics")
        .select("step,loss,metrics")
        .eq("job_id", job_id)
        .eq("split", "train")
        .order("step", desc=True)
        .limit(1)
        .execute()
    )
    data = response.data or []
    if not data:
        return None
    latest = data[0]
    step = latest.get("step")
    loss = latest.get("loss")
    return {
        "step": str(step) if step is not None else "N/A",
        "loss": str(loss) if loss is not None else "N/A",
    }


async def _get_latest_metric(job_id: str, split: str) -> Optional[dict]:
    client = await get_supabase_async_client()
    response = (
        await client.table("training_job_metrics")
        .select("step,loss,ts,metrics")
        .eq("job_id", job_id)
        .eq("split", split)
        .order("step", desc=True)
        .limit(1)
        .execute()
    )
    data = response.data or []
    if not data:
        return None
    return data[0]


async def _get_latest_metrics(job_id: str) -> tuple[Optional[dict], Optional[dict]]:
    return await _get_latest_metric(job_id, "train"), await _get_latest_metric(
        job_id, "val"
    )


async def _get_metrics_series(job_id: str, split: str, limit: int) -> list[dict]:
    client = await get_supabase_async_client()
    response = (
        await client.table("training_job_metrics")
        .select("step,loss,ts")
        .eq("job_id", job_id)
        .eq("split", split)
        .order("step", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data or []


def _stop_remote_job(job_data: dict) -> bool:
    """Stop remote training job via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return False

    try:
        conn.exec_command(
            f"tmux kill-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null || true"
        )
        conn.exec_command(
            f"tmux kill-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null || true"
        )
        return True
    except Exception:
        return False
    finally:
        conn.disconnect()


# --- API Endpoints ---


# Known GPU models to check (in priority order)
GPU_MODELS_QUICK = ["B300", "B200", "H200", "H100", "A100"]
GPU_COUNTS_QUICK = [1]  # Only check count=1 for speed
KNOWN_LOCATIONS = ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]

# Cache for GPU availability (TTL: 10 minutes)
_gpu_availability_cache: dict = {}
_gpu_availability_cache_time: dict[str, float] = {}
_GPU_CACHE_TTL = 600  # 10 minutes


def _extract_availability_entry(item: object) -> tuple[Optional[str], list[str]]:
    if not isinstance(item, dict):
        return None, []

    location_code_raw = item.get("location_code") or item.get("locationCode")
    location_code = (
        location_code_raw
        if isinstance(location_code_raw, str) and location_code_raw
        else None
    )

    availabilities = item.get("availabilities")
    if not isinstance(availabilities, list):
        return location_code, []

    instance_types = [
        instance_type
        for instance_type in availabilities
        if isinstance(instance_type, str) and instance_type
    ]
    return location_code, instance_types


def _extract_gpu_model(instance_type: str) -> str:
    prefix = instance_type.split(".", 1)[0]
    idx = 0
    while idx < len(prefix) and prefix[idx].isdigit():
        idx += 1
    return prefix[idx:] or prefix


def _build_quick_configs(
    instance_types: list[object],
) -> list[tuple[str, int, str, Optional[float]]]:
    configs_to_check = []
    for gpu_model in GPU_MODELS_QUICK:
        for gpu_count in GPU_COUNTS_QUICK:
            for item in instance_types:
                instance_type = getattr(item, "instance_type", None)
                if not isinstance(instance_type, str):
                    continue

                count = _extract_gpu_count(instance_type)
                if count is None:
                    continue

                if count == gpu_count and gpu_model.upper() in instance_type.upper():
                    spot_price = getattr(item, "spot_price_per_hour", None)
                    configs_to_check.append(
                        (gpu_model, gpu_count, instance_type, spot_price)
                    )
                    break

    return configs_to_check


def _build_all_configs(
    instance_types: list[object],
) -> list[tuple[str, int, str, Optional[float]]]:
    configs_to_check: list[tuple[str, int, str, Optional[float]]] = []

    for item in instance_types:
        instance_type = getattr(item, "instance_type", None)
        if not isinstance(instance_type, str) or not instance_type:
            continue

        gpu_count = _extract_gpu_count(instance_type)
        if gpu_count is None or gpu_count <= 0:
            continue

        gpu_model = _extract_gpu_model(instance_type)
        if not gpu_model or gpu_model.upper() == "CPU":
            continue

        spot_price = getattr(item, "spot_price_per_hour", None)
        configs_to_check.append((gpu_model, gpu_count, instance_type, spot_price))

    configs_to_check.sort(key=lambda item: (item[0], item[1], item[2]))
    return configs_to_check


def _ordered_availability_locations(
    preferred_locations: list[str],
    *availability_maps: dict[str, set[str]],
) -> list[str]:
    known = []
    for location in preferred_locations:
        if location not in known:
            known.append(location)

    extras = sorted(
        {
            location
            for availability_map in availability_maps
            for location in availability_map
            if location not in known
        }
    )
    return known + extras


def _get_location_codes(client: VerdaClient) -> list[str]:
    try:
        items = client.locations.get() or []
    except Exception:
        return list(KNOWN_LOCATIONS)

    codes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if isinstance(code, str) and code:
            codes.append(code)

    return codes or list(KNOWN_LOCATIONS)


def _fetch_availability_sets(
    client: VerdaClient,
    preferred_locations: list[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    spot_available_by_loc = {loc: set() for loc in preferred_locations}
    ondemand_available_by_loc = {loc: set() for loc in preferred_locations}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(client.instances.get_availabilities, True, None): True,
            executor.submit(client.instances.get_availabilities, False, None): False,
        }

        for future in as_completed(futures, timeout=30):
            is_spot = futures[future]
            try:
                items = future.result() or []
            except Exception:
                continue
            target = spot_available_by_loc if is_spot else ondemand_available_by_loc
            for item in items:
                location_code, instance_types = _extract_availability_entry(item)
                if (
                    not location_code
                    or location_code not in preferred_locations
                    or not instance_types
                ):
                    continue

                target.setdefault(location_code, set()).update(instance_types)

    return spot_available_by_loc, ondemand_available_by_loc


@router.get("/gpu-availability", response_model=GpuAvailabilityResponse)
def get_gpu_availability(scan: Literal["quick", "all"] = "all"):
    """Check GPU availability.

    scan="quick": checks main configurations only (B300, B200, H200, H100, A100 x1)
    scan="all": checks all GPU instance types and all locations
    """
    global _gpu_availability_cache, _gpu_availability_cache_time

    cache_key = f"gpu_availability:{scan}"
    should_use_cache = True

    # Check cache
    cache_time = _gpu_availability_cache_time.get(cache_key, 0.0)
    if (
        should_use_cache
        and time.time() - cache_time < _GPU_CACHE_TTL
        and cache_key in _gpu_availability_cache
    ):
        return GpuAvailabilityResponse(
            available=_gpu_availability_cache[cache_key],
            checked_at=datetime.fromtimestamp(cache_time),
        )

    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    available = []

    try:
        # Get all instance types (single API call)
        instance_types = client.instance_types.get()

        if scan == "all":
            preferred_locations = _get_location_codes(client)
            configs_to_check = _build_all_configs(instance_types)
        else:
            preferred_locations = list(KNOWN_LOCATIONS)
            configs_to_check = _build_quick_configs(instance_types)

        spot_available_by_loc, ondemand_available_by_loc = _fetch_availability_sets(
            client, preferred_locations
        )

        availability_locations = _ordered_availability_locations(
            preferred_locations,
            spot_available_by_loc,
            ondemand_available_by_loc,
        )

        # Build response
        for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
            spot_locs = [
                loc
                for loc in availability_locations
                if instance_type in spot_available_by_loc.get(loc, set())
            ]
            ondemand_locs = [
                loc
                for loc in availability_locations
                if instance_type in ondemand_available_by_loc.get(loc, set())
            ]
            available.append(
                GpuAvailabilityInfo(
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    instance_type=instance_type,
                    spot_available=len(spot_locs) > 0,
                    ondemand_available=len(ondemand_locs) > 0,
                    spot_locations=spot_locs,
                    ondemand_locations=ondemand_locs,
                    spot_price_per_hour=spot_price,
                )
            )

        # Update cache
        if should_use_cache:
            _gpu_availability_cache[cache_key] = available
            _gpu_availability_cache_time[cache_key] = time.time()

    except Exception as e:
        logger.exception("Failed to check GPU availability")
        raise HTTPException(status_code=503, detail=f"GPU空き状況の確認に失敗: {e}")

    return GpuAvailabilityResponse(available=available)


@router.get("/verda/storage", response_model=VerdaStorageListResponse)
async def list_verda_storage():
    """List Verda storage volumes (active + deleted)."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    items = [
        _build_verda_storage_item(volume, state)
        for _, (state, volume) in volumes_by_id.items()
        if getattr(volume, "id", "")
    ]
    items.sort(key=lambda item: (item.state != "deleted", item.created_at or ""))
    return VerdaStorageListResponse(items=items, total=len(items))


@router.post("/verda/storage/delete", response_model=VerdaStorageActionResult)
async def delete_verda_storage(request: VerdaStorageActionRequest):
    """Delete Verda storage volumes (logical delete)."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage delete requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for delete")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "active":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="既に削除済みのストレージです",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            client.volumes.delete(chunk, is_permanent=False)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to delete volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage delete result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.post("/verda/storage/restore", response_model=VerdaStorageActionResult)
async def restore_verda_storage(request: VerdaStorageActionRequest):
    """Restore Verda storage volumes from trash."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage restore requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for restore")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "deleted":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="削除済みではありません",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            _restore_verda_volumes(client, chunk)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to restore volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage restore result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.post("/verda/storage/purge", response_model=VerdaStorageActionResult)
async def purge_verda_storage(request: VerdaStorageActionRequest):
    """Permanently delete Verda storage volumes from trash."""
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    logger.info(f"Verda storage purge requested: {request.volume_ids}")
    result = VerdaStorageActionResult()
    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for purge")
        raise HTTPException(
            status_code=502, detail=f"Verda APIに接続できません: {e}"
        ) from e

    eligible_ids: list[str] = []
    for volume_id in request.volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="対象が見つかりません（既に削除済みの可能性）",
                )
            )
            continue

        state, _ = state_volume
        if state != "deleted":
            result.skipped.append(
                VerdaStorageActionFailure(
                    id=volume_id,
                    reason="削除済みではありません",
                )
            )
            continue

        eligible_ids.append(volume_id)

    for chunk in _chunk_list(eligible_ids):
        try:
            client.volumes.delete(chunk, is_permanent=True)
            result.success_ids.extend(chunk)
        except Exception as e:
            logger.exception(f"Failed to purge volume chunk: {chunk}")
            for volume_id in chunk:
                result.failed.append(
                    VerdaStorageActionFailure(
                        id=volume_id,
                        reason=str(e),
                    )
                )

    logger.info(
        "Verda storage purge result: success=%s failed=%s skipped=%s",
        len(result.success_ids),
        len(result.failed),
        len(result.skipped),
    )
    return result


@router.websocket("/ws/gpu-availability")
async def websocket_gpu_availability(websocket: WebSocket):
    """Stream GPU availability check results in real-time.

    Each GPU result is sent as it becomes available:
    - {"type": "checking", "gpu_model": "H100", "message": "H100を確認中..."}
    - {"type": "result", "gpu_model": "H100", "gpu_count": 1, "spot_available": true, ...}
    - {"type": "complete", "message": "確認完了"}
    - {"type": "cached", "message": "キャッシュから取得"}
    """
    await websocket.accept()

    global _gpu_availability_cache, _gpu_availability_cache_time

    try:
        scan = websocket.query_params.get("scan", "all")
        if scan not in {"quick", "all"}:
            scan = "all"
        cache_key = f"gpu_availability:{scan}"
        should_use_cache = True

        # Check cache first
        cache_time = _gpu_availability_cache_time.get(cache_key, 0.0)
        if (
            should_use_cache
            and time.time() - cache_time < _GPU_CACHE_TTL
            and cache_key in _gpu_availability_cache
        ):
            await websocket.send_json(
                {"type": "cached", "message": "キャッシュから取得"}
            )
            for item in _gpu_availability_cache[cache_key]:
                await websocket.send_json(
                    {
                        "type": "result",
                        "gpu_model": item.gpu_model,
                        "gpu_count": item.gpu_count,
                        "spot_available": item.spot_available,
                        "ondemand_available": item.ondemand_available,
                    }
                )
            await websocket.send_json({"type": "complete", "message": "確認完了"})
            await websocket.close()
            return

        client = _get_verda_client()
        if not client:
            await websocket.send_json(
                {"type": "error", "error": "Verda認証情報が設定されていません"}
            )
            await websocket.close()
            return

        await websocket.send_json(
            {"type": "start", "message": "GPU空き状況を確認中..."}
        )

        # Get instance types
        loop = asyncio.get_event_loop()
        instance_types = await loop.run_in_executor(
            _executor, client.instance_types.get
        )

        # Build configs to check
        if scan == "all":
            preferred_locations = await loop.run_in_executor(
                _executor, _get_location_codes, client
            )
            configs_to_check = _build_all_configs(instance_types)
        else:
            preferred_locations = list(KNOWN_LOCATIONS)
            configs_to_check = _build_quick_configs(instance_types)

        # Check each GPU and stream results
        available = []
        for gpu_model, _, _, _ in configs_to_check:
            await websocket.send_json(
                {
                    "type": "checking",
                    "gpu_model": gpu_model,
                    "message": f"{gpu_model}を確認中...",
                }
            )

        spot_available_by_loc, ondemand_available_by_loc = await loop.run_in_executor(
            _executor, _fetch_availability_sets, client, preferred_locations
        )
        availability_locations = _ordered_availability_locations(
            preferred_locations,
            spot_available_by_loc,
            ondemand_available_by_loc,
        )

        for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
            spot_locs = [
                loc
                for loc in availability_locations
                if instance_type in spot_available_by_loc.get(loc, set())
            ]
            ondemand_locs = [
                loc
                for loc in availability_locations
                if instance_type in ondemand_available_by_loc.get(loc, set())
            ]
            spot_available = len(spot_locs) > 0
            ondemand_available = len(ondemand_locs) > 0

            await websocket.send_json(
                {
                    "type": "result",
                    "gpu_model": gpu_model,
                    "gpu_count": gpu_count,
                    "spot_available": spot_available,
                    "ondemand_available": ondemand_available,
                }
            )

            available.append(
                GpuAvailabilityInfo(
                    gpu_model=gpu_model,
                    gpu_count=gpu_count,
                    instance_type=instance_type,
                    spot_available=spot_available,
                    ondemand_available=ondemand_available,
                    spot_locations=spot_locs,
                    ondemand_locations=ondemand_locs,
                    spot_price_per_hour=spot_price,
                )
            )

        # Update cache
        if should_use_cache:
            _gpu_availability_cache[cache_key] = available
            _gpu_availability_cache_time[cache_key] = time.time()

        await websocket.send_json({"type": "complete", "message": "確認完了"})

    except Exception as e:
        logger.exception("WebSocket GPU availability check failed")
        await websocket.send_json({"type": "error", "error": str(e)})

    await websocket.close()


@router.websocket("/ws/verda/storage")
async def websocket_verda_storage(websocket: WebSocket):
    """Run Verda storage actions with progress via WebSocket."""
    await websocket.accept()

    try:
        request = await websocket.receive_json()
    except Exception:
        await websocket.send_json({"type": "error", "error": "Invalid request"})
        await websocket.close()
        return

    action = request.get("action")
    volume_ids = request.get("volume_ids", [])
    if action not in ("delete", "restore", "purge"):
        await websocket.send_json({"type": "error", "error": "Unsupported action"})
        await websocket.close()
        return

    client = _get_verda_client()
    if not client:
        await websocket.send_json(
            {
                "type": "error",
                "error": "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
            }
        )
        await websocket.close()
        return

    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for WS action")
        await websocket.send_json(
            {"type": "error", "error": f"Verda APIに接続できません: {e}"}
        )
        await websocket.close()
        return

    required_state = "active" if action == "delete" else "deleted"
    is_permanent = action == "purge"

    skipped: list[dict] = []
    eligible_ids: list[str] = []
    for volume_id in volume_ids:
        state_volume = volumes_by_id.get(volume_id)
        if not state_volume:
            skipped.append(
                {
                    "id": volume_id,
                    "reason": "対象が見つかりません（既に削除済みの可能性）",
                }
            )
            continue
        state, _ = state_volume
        if state != required_state:
            skipped.append(
                {
                    "id": volume_id,
                    "reason": "削除済みではありません"
                    if required_state == "deleted"
                    else "既に削除済みのストレージです",
                }
            )
            continue
        eligible_ids.append(volume_id)

    total = len(volume_ids)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    done_count = {"value": 0}
    done_lock = threading.Lock()

    def emit_progress(
        volume_id: str, status: str, reason: Optional[str] = None
    ) -> None:
        with done_lock:
            done_count["value"] += 1
            current = done_count["value"]
        payload = {
            "type": "progress",
            "id": volume_id,
            "status": status,
            "done": current,
            "total": total,
        }
        if reason:
            payload["reason"] = reason
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    loop.call_soon_threadsafe(
        queue.put_nowait,
        {"type": "start", "total": total, "eligible": len(eligible_ids)},
    )

    for item in skipped:
        emit_progress(item["id"], "skipped", item["reason"])

    def worker() -> None:
        result = {
            "success_ids": [],
            "failed": [],
            "skipped": skipped,
        }
        try:
            batch_action = "delete" if action == "purge" else action
            chunks = _chunk_list(eligible_ids, chunk_size=5)
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(
                        _perform_verda_volume_action_batch,
                        batch_action,
                        chunk,
                        is_permanent,
                    ): chunk
                    for chunk in chunks
                }
                for future in as_completed(futures):
                    chunk = futures[future]
                    try:
                        future.result()
                        result["success_ids"].extend(chunk)
                        for volume_id in chunk:
                            emit_progress(volume_id, "success")
                    except Exception as e:
                        reason = str(e)
                        for volume_id in chunk:
                            result["failed"].append({"id": volume_id, "reason": reason})
                            emit_progress(volume_id, "failed", reason)
        finally:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "complete", "result": result}
            )

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") == "complete":
                break
    except WebSocketDisconnect:
        return
    finally:
        await websocket.close()


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(days: int = Query(365, ge=1, le=365)):
    """List training jobs.

    Args:
        days: Return jobs from past N days (running jobs always included)
    """
    jobs_data = await _list_jobs(days)
    jobs = [JobInfo(**j) for j in jobs_data]
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str):
    """Get job details with remote status."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job_data.get("status") in ("running", "starting", "deploying"):
        await _refresh_job_status_from_instance(job_data)

    job = JobInfo(**job_data)
    remote_status = None
    progress = None
    latest_train_metrics, latest_val_metrics = await _get_latest_metrics(job_id)
    summary = job_data.get("summary")
    early_stopping = job_data.get("early_stopping")
    training_config = job_data.get("training_config")

    # Progress is derived from Supabase metrics
    if job.status in ("running", "starting", "deploying"):
        progress = await _get_remote_progress(job_id)

    return JobDetailResponse(
        job=job,
        remote_status=remote_status,
        progress=progress,
        latest_train_metrics=latest_train_metrics,
        latest_val_metrics=latest_val_metrics,
        summary=summary,
        early_stopping=early_stopping,
        training_config=training_config,
    )


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(
    job_id: str,
    lines: int = Query(100, ge=1, le=10000),
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Get job logs from remote instance."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_status = None
    if job_data.get("status") in ("running", "starting", "deploying"):
        instance_status = await _refresh_job_status_from_instance(job_data)

    remote_allowed = True
    if instance_status in (None, "offline", "error", "discontinued"):
        remote_allowed = False

    source = "remote"
    logs = None
    if remote_allowed:
        logs = _get_remote_logs(job_data, lines, log_type=log_type)
    if logs is None:
        source = "r2"
        logs = _get_logs_from_r2(job_data, lines, log_type)
    if logs is None:
        raise HTTPException(
            status_code=503, detail="Could not connect to remote instance"
        )

    return JobLogsResponse(job_id=job_id, logs=logs, lines=lines, source=source)


@router.get("/jobs/{job_id}/logs/download", response_class=PlainTextResponse)
async def download_job_logs(
    job_id: str,
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Download full job logs as plain text."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_status = None
    if job_data.get("status") in ("running", "starting", "deploying"):
        instance_status = await _refresh_job_status_from_instance(job_data)

    remote_allowed = True
    if instance_status in (None, "offline", "error", "discontinued"):
        remote_allowed = False

    if _should_try_r2_first(job_data):
        logs = _get_full_logs_from_r2(job_data, log_type)
        if logs is None and remote_allowed:
            logs = _get_remote_log_file(job_data, log_type=log_type, timeout=30)
            if logs is None:
                logs = _get_remote_logs(job_data, lines=5000, log_type=log_type)
    else:
        logs = None
        if remote_allowed:
            logs = _get_remote_log_file(job_data, log_type=log_type, timeout=30)
            if logs is None:
                logs = _get_remote_logs(job_data, lines=5000, log_type=log_type)
        if logs is None:
            logs = _get_full_logs_from_r2(job_data, log_type)
    if logs is None:
        r2_status = _check_logs_in_r2(job_data, log_type)
        raise HTTPException(
            status_code=503,
            detail=(
                "Log fetch failed. "
                f"r2_exists={r2_status.get('exists')} key={r2_status.get('key')}"
            ),
        )
    return logs


@router.get("/jobs/{job_id}/logs/status")
async def get_job_logs_status(
    job_id: str,
    log_type: str = Query("training", pattern="^(training|setup)$"),
):
    """Check whether logs exist on R2 for this job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    r2_status = _check_logs_in_r2(job_data, log_type)
    return {
        "job_id": job_id,
        "log_type": log_type,
        "r2": r2_status,
    }


@router.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
async def get_job_progress(job_id: str):
    """Get training progress for a job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    progress = await _get_remote_progress(job_id)
    if progress is None:
        return JobProgressResponse(job_id=job_id)

    return JobProgressResponse(job_id=job_id, **progress)


@router.get("/jobs/{job_id}/metrics", response_model=JobMetricsResponse)
async def get_job_metrics(
    job_id: str,
    response: Response,
    limit: int = Query(1000, ge=1, le=10000),
):
    """Get training/validation loss series for a job."""
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    train = await _get_metrics_series(job_id, "train", limit)
    val = await _get_metrics_series(job_id, "val", limit)

    # Fallback to R2 archive if DB has no metrics for a terminal job
    from_archive = False
    if not train and not val and job_data.get("status") in (
        "completed", "stopped", "terminated", "failed",
    ):
        archived = _get_metrics_from_r2(job_id)
        if archived:
            train = [m for m in archived if m.get("split") == "train"][:limit]
            val = [m for m in archived if m.get("split") == "val"][:limit]
            from_archive = True

    if from_archive:
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"

    return JobMetricsResponse(job_id=job_id, train=train, val=val)


@router.get("/jobs/{job_id}/instance-status", response_model=InstanceStatusResponse)
async def get_instance_status(job_id: str):
    """Get detailed instance status from Verda API.

    This endpoint checks the actual cloud instance status and optionally
    the remote training process status via SSH.
    """
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    job_status = job_data.get("status", "unknown")
    ip = job_data.get("ip")

    # Check instance status via Verda API
    instance_status = None
    message = ""

    if instance_id:
        instance_status = _check_instance_via_api(instance_id)
        if instance_status is None:
            message = "Instance not found in Verda (may be deleted)"
        elif instance_status == "running":
            message = "Instance is running"
        elif instance_status in ("offline", "error", "discontinued"):
            message = f"Instance is {instance_status} (terminated)"
        else:
            message = f"Instance is {instance_status}"
    else:
        message = "No instance ID associated with this job"

    # Check remote process status if instance is running and has IP
    remote_process_status = None
    if instance_status == "running" and ip:
        remote_process_status = _check_remote_status(job_data)
        if remote_process_status == "running":
            message = "Instance running, training in progress"
        elif remote_process_status == "stopped":
            message = "Instance running, training process stopped"
        elif remote_process_status == "unreachable":
            message = "Instance running, but SSH unreachable"

    return InstanceStatusResponse(
        job_id=job_id,
        instance_id=instance_id or "",
        instance_status=instance_status,
        job_status=job_status,
        ip=ip,
        remote_process_status=remote_process_status,
        gpu_model=job_data.get("gpu_model"),
        gpus_per_instance=job_data.get("gpus_per_instance"),
        created_at=job_data.get("created_at"),
        message=message,
    )


@router.get(
    "/jobs/{job_id}/checkpoints/remote",
    response_model=RemoteCheckpointListResponse,
)
async def list_remote_job_checkpoints(job_id: str):
    """List checkpoint directories available on the remote instance."""
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    job_data = await _refresh_job_ssh_target_if_needed(job_data)

    try:
        checkpoint_names, checkpoint_root = await asyncio.to_thread(
            _list_remote_checkpoint_dirs, job_data
        )
    except RuntimeError as exc:
        detail = str(exc)
        status_code = 404 if "見つかりません" in detail else 503
        raise HTTPException(status_code=status_code, detail=detail)

    return RemoteCheckpointListResponse(
        job_id=job_id,
        checkpoint_names=checkpoint_names,
        checkpoint_root=checkpoint_root,
    )


@router.post("/jobs/{job_id}/revive", response_model=JobReviveResponse)
async def revive_job_instance(job_id: str):
    """Revive a terminated instance by restoring its OS volume and starting a CPU instance."""
    result = await _revive_job_with_progress(job_id, lambda _msg: None)
    return JobReviveResponse(**result)


async def _revive_job_with_progress(
    job_id: str, emit_progress: Callable[[dict], None]
) -> dict:
    emit_progress({"type": "start", "message": "蘇生を開始しました"})
    job_data = await _load_job(job_id, include_deleted=True)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    if not instance_id:
        raise HTTPException(status_code=400, detail="ジョブに instance_id がありません")

    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)",
        )

    emit_progress({"type": "loading_storage", "message": "ストレージ情報を取得中..."})
    volumes_by_id = _collect_verda_volumes(client)
    picked = _pick_os_volume_for_instance(volumes_by_id, instance_id)
    if not picked:
        picked = _pick_os_volume_for_job(volumes_by_id, job_id)
    if not picked:
        raise HTTPException(
            status_code=404,
            detail="対象インスタンスのストレージが見つかりません",
        )

    state, volume = picked
    volume_id = getattr(volume, "id", "") or ""
    if not volume_id:
        raise HTTPException(
            status_code=404, detail="ストレージIDが取得できませんでした"
        )

    if state == "deleted":
        emit_progress(
            {
                "type": "restore_storage",
                "message": "ストレージを復活中...",
                "volume_id": volume_id,
            }
        )
        _restore_verda_volumes(client, [volume_id])
        _wait_for_volume_restore(client, volume_id)
        emit_progress(
            {
                "type": "restore_complete",
                "message": "ストレージ復活完了",
                "volume_id": volume_id,
            }
        )

    detach_ready_statuses = {"offline", "discontinued", "deleted"}
    attached_instance_id = getattr(volume, "instance_id", None)
    if attached_instance_id and attached_instance_id != instance_id:
        emit_progress(
            {
                "type": "detaching_from_other",
                "message": "別インスタンスからデタッチ中...",
                "instance_id": attached_instance_id,
            }
        )
        attached_status = _check_instance_via_api(attached_instance_id)
        if attached_status is not None and attached_status not in detach_ready_statuses:
            _delete_verda_instance(attached_instance_id)
            _wait_for_instance_offline(
                client, attached_instance_id, allowed_statuses=detach_ready_statuses
            )

    instance_status = _check_instance_via_api(instance_id)
    if instance_status is not None and instance_status not in detach_ready_statuses:
        emit_progress(
            {
                "type": "stopping_old_instance",
                "message": "旧インスタンス停止中...",
                "instance_id": instance_id,
            }
        )
        _delete_verda_instance(instance_id)
        _wait_for_instance_offline(
            client, instance_id, allowed_statuses=detach_ready_statuses
        )

    emit_progress(
        {
            "type": "detaching_storage",
            "message": "ストレージをデタッチ中...",
            "volume_id": volume_id,
        }
    )
    _ensure_volume_detached(client, volume_id)
    _wait_for_volume_detached(client, volume_id)
    emit_progress(
        {
            "type": "detached_storage",
            "message": "ストレージのデタッチ完了",
            "volume_id": volume_id,
        }
    )

    emit_progress({"type": "select_instance", "message": "CPUインスタンスを選択中..."})
    instance_type = _select_cpu_instance_type(client)
    ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
    if not ssh_key_name:
        raise HTTPException(
            status_code=400, detail="VERDA_SSH_KEY_NAMEが設定されていません"
        )
    ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

    preferred_location = getattr(volume, "location", None) or "auto"
    location = _find_location(client, instance_type, preferred_location, is_spot=False)
    hostname = f"revive-{job_id[:8]}"

    emit_progress(
        {"type": "creating_instance", "message": "CPUインスタンスを作成中..."}
    )
    instance = client.instances.create(
        instance_type=instance_type,
        image=volume_id,
        hostname=hostname,
        description=f"Revive job: {job_id}",
        ssh_key_ids=[ssh_key_id],
        location=location,
        is_spot=False,
    )
    new_instance_id = instance.id

    ip = None
    start_time = time.time()
    deadline = start_time + IP_WAIT_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            inst = client.instances.get_by_id(new_instance_id)
            if getattr(inst, "ip", None):
                ip = inst.ip
                break
        except Exception:
            pass
        emit_progress(
            {
                "type": "waiting_ip",
                "message": "IP割り当て待機中...",
                "elapsed": int(time.time() - start_time),
                "timeout": IP_WAIT_TIMEOUT_SEC,
            }
        )
        time.sleep(10)

    if not ip:
        raise HTTPException(status_code=504, detail="IP取得タイムアウト (15分)")

    ssh_private_key = _select_preferred_ssh_private_key(job_data.get("ssh_private_key"))
    ssh_user = job_data.get("ssh_user") or _get_default_ssh_user()

    result = JobReviveResponse(
        job_id=job_id,
        old_instance_id=instance_id,
        volume_id=volume_id,
        instance_id=new_instance_id,
        instance_type=instance_type,
        ip=ip,
        ssh_user=ssh_user,
        ssh_private_key=ssh_private_key,
        location=location,
        message="CPUインスタンスを起動しました。SSH接続できます。",
    )
    job_data["instance_id"] = new_instance_id
    job_data["ip"] = ip
    job_data["ssh_user"] = ssh_user
    job_data["ssh_private_key"] = ssh_private_key
    await _save_job(job_data)
    return result.model_dump()


@router.websocket("/ws/jobs/{job_id}/checkpoints/upload")
async def websocket_upload_remote_checkpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    access_token = websocket.query_params.get("access_token")
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            access_token = parts[1]
    if not access_token:
        access_token = websocket.cookies.get(ACCESS_COOKIE_NAME)
    refresh_token = websocket.cookies.get(REFRESH_COOKIE_NAME)
    supabase_session = build_session_from_tokens(access_token, refresh_token)
    if not supabase_session or is_session_expired(supabase_session):
        refreshed_session = refresh_session_from_refresh_token(refresh_token)
        if refreshed_session:
            supabase_session = refreshed_session
    if not supabase_session or not supabase_session.get("user_id"):
        await websocket.send_json(
            {
                "type": "error",
                "error": "認証情報がありません。ログインし直してください。",
            }
        )
        await websocket.close()
        return

    try:
        payload = await websocket.receive_json()
    except Exception:
        await websocket.send_json(
            {
                "type": "error",
                "error": "リクエスト形式が不正です。",
            }
        )
        await websocket.close()
        return

    try:
        request = RemoteCheckpointUploadRequest(**payload)
    except Exception as exc:
        await websocket.send_json(
            {
                "type": "error",
                "error": f"パラメータエラー: {exc}",
            }
        )
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def emit(msg: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    def worker() -> None:
        token = set_request_session(supabase_session)
        try:
            result = asyncio.run(
                _upload_selected_remote_checkpoint_with_progress(
                    job_id,
                    request.checkpoint_name,
                    emit,
                )
            )
            emit({"type": "complete", "result": result})
        except HTTPException as exc:
            emit({"type": "error", "error": str(exc.detail)})
        except Exception as exc:
            emit({"type": "error", "error": str(exc)})
        finally:
            reset_request_session(token)

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") in ("complete", "error"):
                break
    except WebSocketDisconnect:
        return


@router.websocket("/ws/jobs/{job_id}/revive")
async def websocket_revive_job(websocket: WebSocket, job_id: str):
    await websocket.accept()
    access_token = websocket.query_params.get("access_token")
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            access_token = parts[1]
    if not access_token:
        access_token = websocket.cookies.get(ACCESS_COOKIE_NAME)
    refresh_token = websocket.cookies.get(REFRESH_COOKIE_NAME)
    supabase_session = build_session_from_tokens(access_token, refresh_token)
    if not supabase_session or is_session_expired(supabase_session):
        refreshed_session = refresh_session_from_refresh_token(refresh_token)
        if refreshed_session:
            supabase_session = refreshed_session
    if not supabase_session or not supabase_session.get("user_id"):
        await websocket.send_json(
            {
                "type": "error",
                "error": "認証情報がありません。ログインし直してください。",
            }
        )
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def emit(msg: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    def worker() -> None:
        token = set_request_session(supabase_session)
        try:
            result = asyncio.run(_revive_job_with_progress(job_id, emit))
            emit({"type": "complete", "result": result})
        except HTTPException as exc:
            emit({"type": "error", "error": str(exc.detail)})
        except Exception as exc:
            emit({"type": "error", "error": str(exc)})
        finally:
            reset_request_session(token)

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") in ("complete", "error"):
                break
    except WebSocketDisconnect:
        return


@router.post("/jobs/{job_id}/stop", response_model=JobActionResponse)
async def stop_job(job_id: str):
    """Stop a running training job."""
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job_data.get("status") not in ("running", "starting"):
        return JobActionResponse(
            job_id=job_id,
            success=False,
            message=f"Job is not running (status: {job_data.get('status')})",
        )

    success = _stop_remote_job(job_data)
    if success:
        job_data["status"] = "stopped"
        job_data["termination_reason"] = "USER_STOP"
        job_data["completed_at"] = datetime.now().isoformat()
        await _save_job(job_data)
        await _archive_job_metrics(job_id)

    return JobActionResponse(
        job_id=job_id,
        success=success,
        message="Job stopped" if success else "Failed to stop job",
    )


def _delete_verda_instance(instance_id: str, wait_timeout: int = 30) -> bool:
    """Delete Verda instance and verify deletion.

    Args:
        instance_id: The Verda instance ID to delete
        wait_timeout: Maximum seconds to wait for deletion confirmation

    Returns:
        True if instance was deleted or is being deleted, False if deletion failed
    """
    client = _get_verda_client()
    if not client:
        logger.warning(
            f"Cannot delete instance {instance_id}: Verda client not available"
        )
        return False

    try:
        # Check if instance exists first
        instance = client.instances.get_by_id(instance_id)
        current_status = instance.status
        logger.info(f"Instance {instance_id} current status: {current_status}")

        if current_status in ("offline", "deleted", "deleting", "discontinued"):
            logger.info(
                f"Instance {instance_id} already terminated or deleting (status: {current_status})"
            )
            return True

        # Send delete request
        logger.info(f"Sending delete request for instance {instance_id}")
        client.instances.action(instance_id, client.constants.instance_actions.DELETE)

        # Wait and verify deletion status
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            time.sleep(2)
            try:
                instance = client.instances.get_by_id(instance_id)
                new_status = instance.status
                logger.info(
                    f"Instance {instance_id} status after delete request: {new_status}"
                )

                if new_status in ("deleted", "deleting", "offline", "discontinued"):
                    logger.info(
                        f"Instance {instance_id} deletion confirmed (status: {new_status})"
                    )
                    return True
            except Exception as check_error:
                # Instance not found - likely deleted
                logger.info(
                    f"Instance {instance_id} no longer found (likely deleted): {check_error}"
                )
                return True

        # Timeout - deletion may still be in progress
        logger.warning(
            f"Instance {instance_id} deletion not confirmed within {wait_timeout}s, but request was sent"
        )
        return True

    except Exception as e:
        error_msg = str(e).lower()
        # Check if it's a "not found" error - instance already deleted
        if "not found" in error_msg or "404" in error_msg:
            logger.info(f"Instance {instance_id} not found (already deleted)")
            return True
        # Actual error - deletion failed
        logger.error(f"Failed to delete instance {instance_id}: {e}")
        return False


@router.delete("/jobs/{job_id}", response_model=JobActionResponse)
async def delete_job(job_id: str, terminate_instance: bool = True):
    """Delete a job record and optionally terminate the remote instance.

    Args:
        job_id: Job ID to delete
        terminate_instance: If True (default), also terminate the Verda instance
    """
    job_data = await _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    instance_id = job_data.get("instance_id")
    instance_deleted = False

    job_data["deleted_at"] = datetime.now().isoformat()
    job_data["status"] = "terminated"
    job_data["termination_reason"] = "USER_DELETE"

    # Terminate Verda instance if requested and available
    if terminate_instance and instance_id:
        job_data["cleanup_status"] = "running"
        await _save_job(job_data)
        instance_deleted = _delete_verda_instance(instance_id)
        job_data["cleanup_status"] = "done" if instance_deleted else "failed"
    await _save_job(job_data)
    await _archive_job_metrics(job_id)

    if instance_id and terminate_instance:
        if instance_deleted:
            message = "ジョブを論理削除し、インスタンスを削除しました"
        else:
            message = "ジョブを論理削除しました（インスタンス終了に失敗）"
    else:
        message = "ジョブを論理削除しました"

    return JobActionResponse(
        job_id=job_id,
        success=True,
        message=message,
    )


@router.post("/jobs/check-status", response_model=JobStatusCheckResponse)
async def check_all_jobs_status():
    """Check and update status of all running jobs.

    This will connect to Verda API and SSH to verify job status.
    """
    jobs_data = await _list_jobs()
    updates = []
    checked = 0

    for job_data in jobs_data:
        if job_data.get("status") not in ("running", "starting"):
            continue

        checked += 1
        old_status = job_data["status"]
        job_id = job_data["job_id"]
        instance_id = job_data.get("instance_id")

        # First check via Verda API
        instance_status = _check_instance_via_api(instance_id) if instance_id else None

        if instance_status is None:
            # Instance not found (deleted or API error)
            job_data["status"] = "terminated"
            job_data["termination_reason"] = "INSTANCE_NOT_FOUND"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await _archive_job_metrics(job_id)
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="terminated",
                    instance_status="not_found",
                    reason="Instance not found (deleted)",
                )
            )
            continue

        if instance_status in ("offline", "error", "discontinued"):
            # Instance terminated (spot preemption, error, etc.)
            job_data["status"] = "terminated"
            job_data["termination_reason"] = "INSTANCE_TERMINATED"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await _archive_job_metrics(job_id)
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="terminated",
                    instance_status=instance_status,
                    reason=f"Instance is {instance_status}",
                )
            )
            continue

        if instance_status != "running":
            # Still provisioning
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason=f"Instance is {instance_status}",
                )
            )
            continue

        # Instance is running, check training process via SSH
        remote_status = _check_remote_status(job_data)

        if remote_status == "stopped":
            await _mark_job_completed(job_id, termination_reason="REMOTE_EXIT")
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status="completed",
                    instance_status=instance_status,
                    reason="Training process finished",
                )
            )
        elif remote_status == "unreachable":
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason="Could not connect via SSH",
                )
            )
        else:
            updates.append(
                JobStatusUpdate(
                    job_id=job_id,
                    old_status=old_status,
                    new_status=old_status,
                    instance_status=instance_status,
                    reason=f"Process status: {remote_status}",
                )
            )

    return JobStatusCheckResponse(updates=updates, checked_count=checked)


@router.post("/jobs", response_model=JobCreateResponse)
async def create_job(request: JobCreateRequest, background_tasks: BackgroundTasks):
    """Create and launch a new training job.

    This endpoint creates a cloud instance and starts training.
    The job runs in the background by default.
    """
    if not request.job_name:
        raise HTTPException(
            status_code=422,
            detail="job_name must be provided",
        )
    if not request.dataset:
        raise HTTPException(
            status_code=422,
            detail="dataset must be provided",
        )
    if not request.policy:
        raise HTTPException(
            status_code=422,
            detail="policy must be provided",
        )
    job_name = request.job_name

    job_id = str(uuid.uuid4())
    session = get_supabase_session() or {}
    supabase_access_token = session.get("access_token")
    supabase_refresh_token = session.get("refresh_token")
    supabase_user_id = session.get("user_id")

    # Check if Verda credentials are available
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Verda/DataCrunch credentials not configured. "
            "Set DATACRUNCH_CLIENT_ID and DATACRUNCH_CLIENT_SECRET.",
        )

    now = datetime.now().isoformat()

    try:
        # Select instance type
        instance_type = _select_instance_type(
            client,
            request.cloud.gpu_model,
            request.cloud.gpus_per_instance,
        )

        # Get SSH key
        ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
        ssh_private_key = os.environ.get(
            "VERDA_SSH_PRIVATE_KEY",
            str(Path.home() / ".ssh" / "id_rsa"),
        )
        ssh_user = _get_default_ssh_user()
        try:
            ssh_private_key = _resolve_ssh_private_key_path(ssh_private_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not ssh_key_name:
            raise HTTPException(
                status_code=503,
                detail="SSH key not configured. Set VERDA_SSH_KEY_NAME.",
            )

        ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

        # Find available location
        location = _find_location(
            client,
            instance_type,
            request.cloud.location,
            request.cloud.is_spot,
        )

        # Create instance
        instance_id = _create_instance(
            client,
            instance_type=instance_type,
            ssh_key_id=ssh_key_id,
            location=location,
            is_spot=request.cloud.is_spot,
            storage_size=request.cloud.storage_size,
            hostname=f"train-{job_id[:16]}",
        )

        # Save job info (status: starting)
        training_payload = {
            k: v for k, v in training_config.model_dump().items() if v is not None
        }
        validation_payload = {
            k: v for k, v in request.validation.model_dump().items() if v is not None
        }
        early_stopping_payload = {
            k: v
            for k, v in request.early_stopping.model_dump().items()
            if v is not None
        }
        if early_stopping_payload.get("enable"):
            validation_payload.setdefault("enable", True)
            if training_payload.get("save_checkpoint") is False:
                training_payload["save_checkpoint"] = True
        if (
            validation_payload.get("enable")
            and validation_payload.get("eval_freq") is None
        ):
            validation_payload["eval_freq"] = (
                training_payload.get("save_freq") or 20_000
            )

        policy_payload = {"type": checkpoint_entry.policy_type}
        if request.policy:
            if request.policy.pretrained_path:
                policy_payload["pretrained_path"] = request.policy.pretrained_path
            if request.policy.dtype:
                policy_payload["dtype"] = request.policy.dtype
            if request.policy.compile_model is not None:
                policy_payload["compile_model"] = request.policy.compile_model
            if request.policy.gradient_checkpointing is not None:
                policy_payload["gradient_checkpointing"] = (
                    request.policy.gradient_checkpointing
                )
            if request.policy.use_amp is not None:
                policy_payload["use_amp"] = request.policy.use_amp

        profile_instance_id, profile_snapshot = await _resolve_profile_info(
            request.dataset.id if request.dataset else None
        )
        job_data = {
            "job_id": job_id,
            "job_name": job_name,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "mode": "train",
            "profile_instance_id": profile_instance_id,
            "profile_snapshot": profile_snapshot,
            "ssh_user": ssh_user,
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root/.physical-ai",
            "checkpoint_repo_id": request.checkpoint_repo_id,
            "created_at": now,
            "updated_at": now,
            "gpu_model": request.cloud.gpu_model,
            "gpus_per_instance": request.cloud.gpus_per_instance,
            "policy_type": request.policy.type if request.policy else None,
            "dataset_id": request.dataset.id if request.dataset else None,
            "training_config": _build_pipeline_config(request, job_id),
        }
        await _save_job(job_data)

        # Start background task to wait for IP and deploy training
        background_tasks.add_task(
            _deploy_and_start_training,
            job_id=job_id,
            request=request,
            supabase_access_token=supabase_access_token,
            supabase_refresh_token=supabase_refresh_token,
            supabase_user_id=supabase_user_id,
        )

        return JobCreateResponse(
            job_id=job_id,
            instance_id=instance_id,
            status="starting",
            message="Instance created, waiting for IP and deploying training",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {e}")


# --- Helper functions for job creation ---


def _select_instance_type(client, gpu_model: str, gpus_per_instance: int) -> str:
    """Select instance type from Verda."""
    gpu_model_upper = gpu_model.upper()
    types = client.instance_types.get()

    candidates = []
    for t in types:
        itype = t.instance_type
        count = _extract_gpu_count(itype)
        if count is None:
            continue

        if count != gpus_per_instance:
            continue
        if gpu_model_upper not in itype.upper():
            continue

        candidates.append(t)

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=f"No instance type found for {gpu_model} x {gpus_per_instance}",
        )

    candidates.sort(key=lambda t: t.spot_price_per_hour)
    return candidates[0].instance_type


def _get_ssh_key_id(client, key_name: str) -> str:
    """Get SSH key ID by name."""
    keys = client.ssh_keys.get()
    for k in keys:
        if k.name == key_name:
            return k.id
    raise HTTPException(
        status_code=400,
        detail=f"SSH key '{key_name}' not found in Verda account",
    )


def _find_location(
    client,
    instance_type: str,
    preferred: str,
    is_spot: bool,
) -> str:
    """Find available location."""
    known_locations = ["FIN-01", "FIN-02", "FIN-03", "ICE-01"]
    instance_mode = "Spot" if is_spot else "On-demand"

    if preferred and preferred.lower() != "auto":
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=preferred,
            ):
                return preferred
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"Location '{preferred}' not available for {instance_type} ({instance_mode})",
        )

    # Find any available location
    checked_locations = []
    for loc in known_locations:
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=loc,
            ):
                return loc
            checked_locations.append(loc)
        except Exception:
            continue

    raise HTTPException(
        status_code=503,
        detail=(
            f"No {instance_mode} instance available for {instance_type}. "
            f"Checked locations: {', '.join(checked_locations) or 'none'}. "
            f"Try again later, use on-demand (is_spot: false), or choose a different GPU."
        ),
    )


def _create_instance(
    client,
    instance_type: str,
    ssh_key_id: str,
    location: str,
    is_spot: bool,
    storage_size: Optional[int],
    hostname: str,
) -> str:
    """Create Verda instance."""
    os_volume = None
    if storage_size:
        vol_name = f"os-{hostname}-{int(time.time())}"[:32]
        os_volume = {
            "size": storage_size,
            "type": "NVMe",
            "name": vol_name,
        }

    if is_spot:
        instance = client.instances.create(
            instance_type=instance_type,
            image="ubuntu-24.04-cuda-12.8-open-docker",
            hostname=hostname,
            description=f"Training job: {hostname}",
            ssh_key_ids=[ssh_key_id],
            location=location,
            os_volume=os_volume,
            is_spot=True,
            contract="SPOT",
        )
    else:
        instance = client.instances.create(
            instance_type=instance_type,
            image="ubuntu-24.04-cuda-12.8-open-docker",
            hostname=hostname,
            description=f"Training job: {hostname}",
            ssh_key_ids=[ssh_key_id],
            location=location,
            os_volume=os_volume,
            is_spot=False,
        )

    return instance.id


def _create_job_with_progress(
    request_data: dict,
    emit_progress: Callable[[dict], None],
    supabase_session: Optional[dict] = None,
) -> dict:
    """Create a training job with progress callbacks.

    This function is designed to run in a thread pool executor.
    It combines instance creation and deployment into a single flow
    with progress updates at each step.

    Args:
        request_data: Job creation request data (dict form of JobCreateRequest)
        emit_progress: Callback function to emit progress events

    Returns:
        dict with job_id, status, and message
    """
    from interfaces_backend.models.training import (
        DatasetConfig,
        PolicyConfig,
        TrainingParams,
        CloudConfig,
        JobCreateRequest,
    )

    token = set_request_session(supabase_session)
    supabase_access_token = None
    supabase_refresh_token = None
    supabase_user_id = None
    if supabase_session:
        supabase_access_token = supabase_session.get("access_token")
        supabase_refresh_token = supabase_session.get("refresh_token")
        supabase_user_id = supabase_session.get("user_id")

    try:
        emit_progress({"type": "start", "message": "ジョブ作成を開始..."})

        # Parse request data
        try:
            emit_progress({"type": "validating", "message": "設定を検証中..."})

            job_name = request_data.get("job_name")
            if not job_name:
                emit_progress(
                    {"type": "error", "error": "ジョブ名が指定されていません"}
                )
                return {"success": False, "error": "ジョブ名が指定されていません"}

            dataset_data = request_data.get("dataset", {})
            policy_data = request_data.get("policy", {})
            training_data = request_data.get("training", {})
            cloud_data = request_data.get("cloud", {})
            checkpoint_repo_id = request_data.get("checkpoint_repo_id")
            wandb_enable = request_data.get("wandb_enable", True)

            # Build config objects
            dataset = DatasetConfig(
                id=dataset_data.get("id", ""),
                source=dataset_data.get("source", "r2"),
                hf_repo_id=dataset_data.get("hf_repo_id"),
                video_backend=dataset_data.get("video_backend"),
                split=dataset_data.get("split"),
            )
            policy = PolicyConfig(
                type=policy_data.get("type", "act"),
                pretrained_path=policy_data.get("pretrained_path"),
                compile_model=policy_data.get("compile_model"),
                gradient_checkpointing=policy_data.get("gradient_checkpointing"),
                dtype=policy_data.get("dtype"),
                use_amp=policy_data.get("use_amp"),
            )
            training = TrainingParams(
                steps=training_data.get("steps"),
                batch_size=training_data.get("batch_size"),
                save_freq=training_data.get("save_freq"),
                log_freq=training_data.get("log_freq"),
                num_workers=training_data.get("num_workers"),
                save_checkpoint=training_data.get("save_checkpoint"),
            )
            validation_data = request_data.get("validation", {})
            early_stopping_data = request_data.get("early_stopping", {})
            cloud = CloudConfig(
                gpu_model=cloud_data.get("gpu_model", "H100"),
                gpus_per_instance=cloud_data.get("gpus_per_instance", 1),
                storage_size=cloud_data.get("storage_size"),
                location=cloud_data.get("location", "auto"),
                is_spot=cloud_data.get("is_spot", True),
            )

            job_id = str(uuid.uuid4())

            emit_progress({"type": "validated", "message": "設定OK"})

        except Exception as e:
            emit_progress({"type": "error", "error": f"設定検証エラー: {e}"})
            return {"success": False, "error": str(e)}

        # Get Verda client
        client = _get_verda_client()
        if not client:
            emit_progress(
                {"type": "error", "error": "Verda認証情報が設定されていません"}
            )
            return {"success": False, "error": "Verda認証情報が設定されていません"}

        # Track instance_id for cleanup on failure
        instance_id: Optional[str] = None

        def cleanup_instance_on_failure(error_msg: str) -> dict:
            """Clean up instance if creation succeeded but subsequent steps failed."""
            nonlocal instance_id
            if instance_id:
                emit_progress(
                    {
                        "type": "cleanup",
                        "message": f"エラー発生のためインスタンスを削除中: {instance_id}",
                    }
                )
                logger.warning(
                    f"Cleaning up instance {instance_id} due to failure: {error_msg}"
                )
                _update_cleanup_status_sync(job_id, "running")
                cleanup_ok = _delete_verda_instance(instance_id)
                _update_cleanup_status_sync(job_id, "done" if cleanup_ok else "failed")
            return {"success": False, "error": error_msg}

        try:
            # Select instance type
            emit_progress(
                {
                    "type": "selecting_instance",
                    "message": "インスタンスタイプを選択中...",
                }
            )
            instance_type = _select_instance_type(
                client, cloud.gpu_model, cloud.gpus_per_instance
            )
            emit_progress(
                {
                    "type": "instance_selected",
                    "message": f"インスタンスタイプ: {instance_type}",
                    "instance_type": instance_type,
                }
            )

            # Get SSH key
            emit_progress({"type": "getting_ssh_key", "message": "SSHキーを取得中..."})
            ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
            ssh_private_key = os.environ.get(
                "VERDA_SSH_PRIVATE_KEY",
                str(Path.home() / ".ssh" / "id_rsa"),
            )
            ssh_user = _get_default_ssh_user()
            try:
                ssh_private_key = _resolve_ssh_private_key_path(ssh_private_key)
            except RuntimeError as exc:
                emit_progress({"type": "error", "error": str(exc)})
                return {"success": False, "error": str(exc)}
            if not ssh_key_name:
                emit_progress(
                    {"type": "error", "error": "VERDA_SSH_KEY_NAMEが設定されていません"}
                )
                return {
                    "success": False,
                    "error": "VERDA_SSH_KEY_NAMEが設定されていません",
                }
            ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

            # Find location
            emit_progress(
                {
                    "type": "finding_location",
                    "message": "利用可能なロケーションを検索中...",
                }
            )
            location = _find_location(
                client, instance_type, cloud.location, cloud.is_spot
            )
            emit_progress(
                {
                    "type": "location_found",
                    "message": f"ロケーション: {location}",
                    "location": location,
                }
            )

            # Create instance
            emit_progress(
                {"type": "creating_instance", "message": "インスタンスを作成中..."}
            )
            instance_id = _create_instance(
                client,
                instance_type=instance_type,
                ssh_key_id=ssh_key_id,
                location=location,
                is_spot=cloud.is_spot,
                storage_size=cloud.storage_size,
                hostname=f"train-{job_id[:16]}",
            )
            emit_progress(
                {
                    "type": "instance_created",
                    "message": f"インスタンス作成完了: {instance_id}",
                    "instance_id": instance_id,
                }
            )

            request_model = JobCreateRequest(
                job_name=job_name,
                dataset=dataset,
                policy=policy,
                training=training,
                validation=ValidationConfig(**validation_data)
                if validation_data
                else ValidationConfig(),
                early_stopping=(
                    EarlyStoppingConfig(**early_stopping_data)
                    if early_stopping_data
                    else EarlyStoppingConfig()
                ),
                cloud=cloud,
                checkpoint_repo_id=checkpoint_repo_id,
                wandb_enable=wandb_enable,
            )
            training_config = _build_pipeline_config(request_model, job_id)

            # Save job info
            now = datetime.now().isoformat()
            profile_instance_id, profile_snapshot = _resolve_profile_info_sync(
                dataset.id
            )
            job_data = {
                "job_id": job_id,
                "job_name": job_name,
                "instance_id": instance_id,
                "ip": None,
                "status": "starting",
                "mode": "train",
                "profile_instance_id": profile_instance_id,
                "profile_snapshot": profile_snapshot,
                "ssh_user": ssh_user,
                "ssh_private_key": ssh_private_key,
                "remote_base_dir": "/root/.physical-ai",
                "checkpoint_repo_id": checkpoint_repo_id,
                "created_at": now,
                "updated_at": now,
                "gpu_model": cloud.gpu_model,
                "gpus_per_instance": cloud.gpus_per_instance,
                "policy_type": policy.type,
                "dataset_id": dataset.id,
                "training_config": training_config,
            }
            _save_job_sync(job_data)

            # Wait for IP (up to 15 minutes)
            emit_progress(
                {
                    "type": "waiting_ip",
                    "message": "IPアドレス割り当て待機中...",
                    "elapsed": 0,
                    "timeout": IP_WAIT_TIMEOUT_SEC,
                }
            )
            ip = None
            start_time = time.time()
            deadline = start_time + IP_WAIT_TIMEOUT_SEC
            while time.time() < deadline:
                try:
                    instance = client.instances.get_by_id(instance_id)
                    if getattr(instance, "ip", None):
                        ip = instance.ip
                        break
                except Exception:
                    pass
                elapsed = int(time.time() - start_time)
                emit_progress(
                    {
                        "type": "waiting_ip",
                        "message": f"IPアドレス割り当て待機中... ({elapsed}秒経過)",
                        "elapsed": elapsed,
                        "timeout": IP_WAIT_TIMEOUT_SEC,
                    }
                )
                time.sleep(IP_POLL_INTERVAL_SEC)

            if not ip:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "IP_TIMEOUT"
                job_data["error_message"] = "IP取得タイムアウト"
                job_data["completed_at"] = datetime.now().isoformat()
                _save_job_sync(job_data)
                emit_progress({"type": "error", "error": "IP取得タイムアウト (15分)"})
                return cleanup_instance_on_failure("IP取得タイムアウト (15分)")

            emit_progress(
                {"type": "ip_assigned", "message": f"IP取得完了: {ip}", "ip": ip}
            )

            # Update job with IP
            job_data["ip"] = ip
            _save_job_sync(job_data)

            # Poll Verda status until instance becomes running
            emit_progress(
                {
                    "type": "waiting_running",
                    "message": "インスタンス起動待機中...",
                    "elapsed": 0,
                    "timeout": INSTANCE_RUNNING_WAIT_TIMEOUT_SEC,
                }
            )
            running = False
            status = ""
            start_time = time.time()
            running_deadline = start_time + INSTANCE_RUNNING_WAIT_TIMEOUT_SEC
            while time.time() < running_deadline:
                try:
                    instance = client.instances.get_by_id(instance_id)
                    status = (
                        str(getattr(instance, "status", "") or "").strip().lower()
                    )
                    if status == "running":
                        running = True
                        break
                    if status in INSTANCE_TERMINAL_STATUSES:
                        break
                except Exception:
                    status = ""

                elapsed = int(time.time() - start_time)
                status_label = status or "unknown"
                emit_progress(
                    {
                        "type": "waiting_running",
                        "message": f"インスタンス起動待機中... (status={status_label}, {elapsed}秒経過)",
                        "elapsed": elapsed,
                        "timeout": INSTANCE_RUNNING_WAIT_TIMEOUT_SEC,
                        "instance_status": status_label,
                    }
                )
                time.sleep(INSTANCE_STATUS_POLL_INTERVAL_SEC)

            if not running:
                job_data["status"] = "failed"
                if status in INSTANCE_TERMINAL_STATUSES:
                    job_data["failure_reason"] = "INSTANCE_TERMINATED"
                    job_data["error_message"] = (
                        f"インスタンスが終了状態です: {status}"
                    )
                    error_message = f"インスタンスが終了状態です: {status}"
                else:
                    job_data["failure_reason"] = "INSTANCE_RUNNING_TIMEOUT"
                    job_data["error_message"] = "インスタンス起動待機タイムアウト"
                    error_message = "インスタンス起動待機タイムアウト (10分)"
                job_data["completed_at"] = datetime.now().isoformat()
                _save_job_sync(job_data)
                emit_progress({"type": "error", "error": error_message})
                return cleanup_instance_on_failure(error_message)

            emit_progress({"type": "instance_running", "message": "インスタンス起動完了"})

            # SSH deployment using SSHConnection and RemoteExecutor
            ssh_user = job_data.get("ssh_user", _get_default_ssh_user())
            job_data["status"] = "deploying"
            _save_job_sync(job_data)

            # Wait for SSH (up to 5 minutes)
            emit_progress(
                {
                    "type": "connecting_ssh",
                    "message": "SSH接続中...",
                    "attempt": 0,
                    "max_attempts": max(
                        1,
                        (
                            SSH_WAIT_TIMEOUT_SEC
                            + SSH_CONNECT_RETRY_INTERVAL_SEC
                            - 1
                        )
                        // SSH_CONNECT_RETRY_INTERVAL_SEC,
                    ),
                }
            )
            conn: Optional[SSHConnection] = None
            start_time = time.time()
            ssh_deadline = start_time + SSH_WAIT_TIMEOUT_SEC
            attempt = 0
            last_ssh_error = ""
            ssh_user_candidates = _build_ssh_user_candidates(ssh_user)
            fatal_ssh_config_error = False
            max_attempts = max(
                1,
                (SSH_WAIT_TIMEOUT_SEC + SSH_CONNECT_RETRY_INTERVAL_SEC - 1)
                // SSH_CONNECT_RETRY_INTERVAL_SEC,
            )
            while time.time() < ssh_deadline:
                attempt += 1
                connected_user: Optional[str] = None
                for candidate_user in ssh_user_candidates:
                    try:
                        conn = _create_ssh_connection(
                            ip,
                            candidate_user,
                            ssh_private_key,
                            timeout=SSH_CONNECT_ATTEMPT_TIMEOUT_SEC,
                        )
                        connected_user = candidate_user
                        break
                    except Exception as exc:
                        last_ssh_error = (
                            f"user={candidate_user}: {type(exc).__name__}: {exc}"
                        )
                        if "SSH鍵が見つかりません" in str(exc) or "SSH鍵パスが不正" in str(exc):
                            fatal_ssh_config_error = True
                            break

                if conn and connected_user:
                    if connected_user != ssh_user:
                        ssh_user = connected_user
                        job_data["ssh_user"] = ssh_user
                        _save_job_sync(job_data)
                    break
                if fatal_ssh_config_error:
                    break

                elapsed = int(time.time() - start_time)
                detail = f" | {last_ssh_error}" if last_ssh_error else ""
                emit_progress(
                    {
                        "type": "connecting_ssh",
                        "message": f"SSH接続中... (試行 {attempt}/{max_attempts}, {elapsed}秒経過){detail}",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "elapsed": elapsed,
                    }
                )
                time.sleep(SSH_CONNECT_RETRY_INTERVAL_SEC)

            if not conn:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "SSH_TIMEOUT"
                timeout_msg = "SSH接続タイムアウト"
                if last_ssh_error:
                    timeout_msg = f"{timeout_msg}: {last_ssh_error}"
                job_data["error_message"] = timeout_msg
                job_data["completed_at"] = datetime.now().isoformat()
                _save_job_sync(job_data)
                emit_progress({"type": "error", "error": timeout_msg})
                return cleanup_instance_on_failure(timeout_msg)

            emit_progress({"type": "ssh_ready", "message": "SSH接続完了"})

            try:
                home_dir = conn.resolve_path("$HOME") or "/root"
                remote_base_dir = f"{home_dir}/.physical-ai"
                remote_run_dir = f"{remote_base_dir}/run"
                job_data["remote_base_dir"] = remote_base_dir
                _save_job_sync(job_data)

                # Create remote directory
                emit_progress(
                    {"type": "deploying", "message": "リモートディレクトリを作成中..."}
                )
                conn.mkdir_p(remote_run_dir)

                # Upload remote scripts
                emit_progress(
                    {
                        "type": "deploying",
                        "message": "スクリプトをアップロード中...",
                        "file": "setup_env.sh",
                    }
                )
                setup_env_path = REMOTE_SCRIPTS_DIR / "setup_env.sh"
                entry_path = REMOTE_SCRIPTS_DIR / "entry.py"
                run_training_path = REMOTE_SCRIPTS_DIR / "run_training.sh"

                if setup_env_path.exists():
                    conn.upload_file(setup_env_path, f"{remote_run_dir}/setup_env.sh")
                emit_progress(
                    {
                        "type": "deploying",
                        "message": "スクリプトをアップロード中...",
                        "file": "entry.py",
                    }
                )
                if entry_path.exists():
                    conn.upload_file(entry_path, f"{remote_run_dir}/entry.py")
                emit_progress(
                    {
                        "type": "deploying",
                        "message": "スクリプトをアップロード中...",
                        "file": "run_training.sh",
                    }
                )
                if run_training_path.exists():
                    conn.upload_file(
                        run_training_path, f"{remote_run_dir}/run_training.sh"
                    )

                # Generate and upload .env file
                emit_progress(
                    {
                        "type": "deploying",
                        "message": "環境変数をアップロード中...",
                        "file": ".env",
                    }
                )
                env_content = _generate_env_file(
                    job_id,
                    instance_id,
                    policy.type if policy else None,
                    supabase_access_token=supabase_access_token,
                    supabase_refresh_token=supabase_refresh_token,
                    supabase_user_id=supabase_user_id,
                )
                conn.upload_content(env_content, f"{remote_run_dir}/.env")

                # Generate and upload instance_info.env
                emit_progress(
                    {
                        "type": "deploying",
                        "message": "インスタンス情報をアップロード中...",
                        "file": "instance_info.env",
                    }
                )
                instance_info = _generate_instance_info_env(
                    job_id, instance_id, auto_delete=True
                )
                conn.upload_content(
                    instance_info, f"{remote_run_dir}/instance_info.env"
                )

                # Make scripts executable
                conn.exec_command(f"chmod +x {remote_run_dir}/setup_env.sh")
                conn.exec_command(f"chmod +x {remote_run_dir}/run_training.sh")

                # Run setup synchronously and stream logs
                emit_progress({"type": "setting_up", "message": "環境構築中..."})

                def _emit_setup_log(line: str) -> None:
                    line = line.strip()
                    if line:
                        emit_progress({"type": "training_log", "message": line})

                setup_cmd = f"cd {remote_run_dir} && timeout {SETUP_TIMEOUT_SEC}s bash setup_env.sh train 2>&1"
                setup_exit_code = run_remote_command(
                    conn,
                    setup_cmd,
                    stream_output=False,
                    on_stdout=_emit_setup_log,
                )
                if setup_exit_code != 0:
                    if setup_exit_code == 124:
                        job_data["status"] = "failed"
                        job_data["failure_reason"] = "SETUP_TIMEOUT"
                        job_data["error_message"] = "環境構築がタイムアウトしました"
                        job_data["completed_at"] = datetime.now().isoformat()
                        _save_job_sync(job_data)
                        _run_async(_upload_remote_logs_to_r2(conn, job_data))
                        emit_progress(
                            {"type": "error", "error": "環境構築がタイムアウトしました"}
                        )
                        return cleanup_instance_on_failure(
                            "環境構築がタイムアウトしました"
                        )
                    job_data["status"] = "failed"
                    job_data["failure_reason"] = "SETUP_FAILED"
                    job_data["error_message"] = (
                        f"環境構築に失敗しました (exit={setup_exit_code})"
                    )
                    job_data["completed_at"] = datetime.now().isoformat()
                    _save_job_sync(job_data)
                    _run_async(_upload_remote_logs_to_r2(conn, job_data))
                    emit_progress({"type": "error", "error": "環境構築に失敗しました"})
                    return cleanup_instance_on_failure("環境構築に失敗しました")

                # Start training in separate tmux session
                executor = RemoteExecutor(conn, remote_base_dir=remote_run_dir)
                emit_progress(
                    {"type": "starting_training", "message": "学習を開始中..."}
                )
                success = executor.run_background(
                    "bash run_training.sh train",
                    session_name=TMUX_TRAIN_SESSION_NAME,
                )
                if not success:
                    emit_progress(
                        {
                            "type": "training_log",
                            "message": "警告: 学習用tmuxセッションの開始を確認できませんでした",
                        }
                    )
                else:
                    job_data["status"] = "starting"
                    _save_job_sync(job_data)

                emit_progress(
                    {
                        "type": "complete",
                        "message": "学習プロセスを起動しました。リモート側の開始確認待ちです。",
                        "job_id": job_id,
                        "instance_id": instance_id,
                        "ip": ip,
                        "status": "starting",
                    }
                )

                return {
                    "success": True,
                    "job_id": job_id,
                    "instance_id": instance_id,
                    "ip": ip,
                    "status": "starting",
                }

            finally:
                conn.disconnect()

        except HTTPException as e:
            if instance_id:
                job_data = _load_job_sync(job_id, include_deleted=True)
                if job_data:
                    job_data["status"] = "failed"
                    job_data["failure_reason"] = "VERDA_ERROR"
                    job_data["error_message"] = e.detail
                    job_data["completed_at"] = datetime.now().isoformat()
                    _save_job_sync(job_data)
            emit_progress({"type": "error", "error": e.detail})
            return cleanup_instance_on_failure(e.detail)
        except Exception as e:
            if instance_id:
                job_data = _load_job_sync(job_id, include_deleted=True)
                if job_data:
                    job_data["status"] = "failed"
                    job_data["failure_reason"] = "UNKNOWN"
                    job_data["error_message"] = str(e)
                    job_data["completed_at"] = datetime.now().isoformat()
                    _save_job_sync(job_data)
            emit_progress({"type": "error", "error": str(e)})
            return cleanup_instance_on_failure(str(e))
    finally:
        reset_request_session(token)


@router.websocket("/ws/create-job")
async def websocket_create_job(websocket: WebSocket):
    """WebSocket endpoint for creating training jobs with real-time progress.

    Client sends JSON request (same format as POST /api/training/jobs but dict):
    {
        "job_name": "job_name",
        "dataset": {"id": "...", "source": "r2"},
        "policy": {"type": "act", "pretrained_path": null},
        "training": {"steps": 100000, "batch_size": 32},
        "cloud": {"gpu_model": "H100", "gpus_per_instance": 1, "is_spot": true},
        "checkpoint_repo_id": null,
        "wandb_enable": true
    }

    Server sends progress updates:
    - {"type": "start", "message": "..."}
    - {"type": "validating", "message": "..."}
    - {"type": "validated", "message": "..."}
    - {"type": "selecting_instance", "message": "..."}
    - {"type": "instance_selected", "message": "...", "instance_type": "..."}
    - {"type": "finding_location", "message": "..."}
    - {"type": "location_found", "message": "...", "location": "..."}
    - {"type": "creating_instance", "message": "..."}
    - {"type": "instance_created", "message": "...", "instance_id": "..."}
    - {"type": "waiting_ip", "message": "...", "elapsed": N, "timeout": 900}
    - {"type": "ip_assigned", "message": "...", "ip": "..."}
    - {"type": "waiting_running", "message": "...", "elapsed": N, "timeout": 600, "instance_status": "..."}
    - {"type": "instance_running", "message": "..."}
    - {"type": "connecting_ssh", "message": "...", "attempt": N, "max_attempts": M}
    - {"type": "ssh_ready", "message": "..."}
    - {"type": "deploying", "message": "...", "file": "..."}
    - {"type": "setting_up", "message": "..."}
    - {"type": "starting_training", "message": "..."}
    - {"type": "complete", "job_id": "...", "instance_id": "...", "ip": "...", "status": "starting"}
    - {"type": "error", "error": "..."}
    - {"type": "heartbeat"} (sent periodically to keep connection alive)
    """
    await websocket.accept()
    logger.info("WebSocket create-job client connected")

    try:
        access_token = websocket.query_params.get("access_token")
        auth_header = websocket.headers.get("authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                access_token = parts[1]
        if not access_token:
            access_token = websocket.cookies.get(ACCESS_COOKIE_NAME)
        refresh_token = websocket.cookies.get(REFRESH_COOKIE_NAME)
        supabase_session = build_session_from_tokens(access_token, refresh_token)
        if not supabase_session or is_session_expired(supabase_session):
            refreshed_session = refresh_session_from_refresh_token(refresh_token)
            if refreshed_session:
                supabase_session = refreshed_session
        if not supabase_session or not supabase_session.get("user_id"):
            await websocket.send_json(
                {
                    "type": "error",
                    "error": "認証情報がありません。ログインし直してください。",
                }
            )
            await websocket.close()
            return

        # Wait for job creation request
        data = await websocket.receive_json()

        # Queue for progress updates from thread
        progress_queue: asyncio.Queue = asyncio.Queue()

        # Capture event loop for use in thread callback
        main_loop = asyncio.get_running_loop()

        def emit_progress(progress: dict):
            """Callback to put progress in queue (called from thread)."""
            asyncio.run_coroutine_threadsafe(progress_queue.put(progress), main_loop)

        # Run job creation in thread pool
        async def run_job_creation():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                _executor,
                lambda: _create_job_with_progress(
                    data, emit_progress, supabase_session
                ),
            )

        # Start job creation task
        creation_task = asyncio.create_task(run_job_creation())

        # Forward progress updates to WebSocket
        heartbeat_interval = 0
        while True:
            try:
                progress = await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                await websocket.send_json(progress)

                if progress.get("type") in ("complete", "error"):
                    break

                heartbeat_interval = 0
            except asyncio.TimeoutError:
                if creation_task.done():
                    # Drain remaining messages
                    while not progress_queue.empty():
                        progress = await progress_queue.get()
                        await websocket.send_json(progress)
                    break

                # Send heartbeat every 5 seconds
                heartbeat_interval += 1
                if heartbeat_interval >= 5:
                    await websocket.send_json({"type": "heartbeat"})
                    heartbeat_interval = 0

        # Get final result
        result = await creation_task

        # If no complete/error was sent yet, send final status
        if not progress_queue.empty():
            while not progress_queue.empty():
                progress = await progress_queue.get()
                await websocket.send_json(progress)

    except WebSocketDisconnect:
        logger.info("WebSocket create-job client disconnected")
    except Exception as e:
        logger.error(f"WebSocket create-job error: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


async def _deploy_and_start_training(
    job_id: str,
    request: JobCreateRequest,
    supabase_access_token: Optional[str] = None,
    supabase_refresh_token: Optional[str] = None,
    supabase_user_id: Optional[str] = None,
) -> None:
    """Background task to deploy and start training.

    This waits for the instance IP, uploads files, and starts training.
    Uses SSHConnection and RemoteExecutor for consistency with other code paths.
    """
    session = build_session_from_tokens(supabase_access_token, supabase_refresh_token)
    token = set_request_session(session)
    try:
        job_data = await _load_job(job_id)
        if not job_data:
            return

        client = _get_verda_client()
        if not client:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "VERDA_ERROR"
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            return

        instance_id = job_data["instance_id"]

        async def cleanup_on_failure(error_msg: str) -> None:
            """Clean up instance on deployment failure."""
            logger.warning(
                f"Cleaning up instance {instance_id} due to failure: {error_msg}"
            )
            await _update_cleanup_status(job_id, "running")
            cleanup_ok = _delete_verda_instance(instance_id)
            await _update_cleanup_status(job_id, "done" if cleanup_ok else "failed")

        try:
            # Wait for IP (up to 15 minutes)
            ip = None
            deadline = time.time() + IP_WAIT_TIMEOUT_SEC
            while time.time() < deadline:
                try:
                    instance = client.instances.get_by_id(instance_id)
                    if getattr(instance, "ip", None):
                        ip = instance.ip
                        break
                except Exception:
                    pass
                time.sleep(IP_POLL_INTERVAL_SEC)

            if not ip:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "IP_TIMEOUT"
                job_data["error_message"] = "IP取得タイムアウト"
                job_data["completed_at"] = datetime.now().isoformat()
                await _save_job(job_data)
                await cleanup_on_failure("IP取得タイムアウト")
                return

            # Update job with IP
            job_data["ip"] = ip
            await _save_job(job_data)

            # Poll Verda status until instance becomes running
            running = False
            status = ""
            running_deadline = time.time() + INSTANCE_RUNNING_WAIT_TIMEOUT_SEC
            while time.time() < running_deadline:
                try:
                    instance = client.instances.get_by_id(instance_id)
                    status = str(getattr(instance, "status", "") or "").strip().lower()
                    if status == "running":
                        running = True
                        break
                    if status in INSTANCE_TERMINAL_STATUSES:
                        break
                except Exception:
                    status = ""
                time.sleep(INSTANCE_STATUS_POLL_INTERVAL_SEC)

            if not running:
                job_data["status"] = "failed"
                if status in INSTANCE_TERMINAL_STATUSES:
                    job_data["failure_reason"] = "INSTANCE_TERMINATED"
                    failure_msg = f"インスタンスが終了状態です: {status}"
                    job_data["error_message"] = failure_msg
                else:
                    job_data["failure_reason"] = "INSTANCE_RUNNING_TIMEOUT"
                    failure_msg = "インスタンス起動待機タイムアウト"
                    job_data["error_message"] = failure_msg
                job_data["completed_at"] = datetime.now().isoformat()
                await _save_job(job_data)
                await cleanup_on_failure(failure_msg)
                return

            job_data["status"] = "deploying"
            await _save_job(job_data)

            # SSH deployment using SSHConnection
            ssh_user = job_data.get("ssh_user", _get_default_ssh_user())
            ssh_private_key = job_data.get(
                "ssh_private_key", str(Path.home() / ".ssh" / "id_rsa")
            )

            # Wait for SSH to be ready (up to 5 minutes)
            conn: Optional[SSHConnection] = None
            ssh_deadline = time.time() + SSH_WAIT_TIMEOUT_SEC
            last_ssh_error = ""
            ssh_user_candidates = _build_ssh_user_candidates(ssh_user)
            fatal_ssh_config_error = False
            while time.time() < ssh_deadline:
                connected_user: Optional[str] = None
                for candidate_user in ssh_user_candidates:
                    try:
                        conn = _create_ssh_connection(
                            ip,
                            candidate_user,
                            ssh_private_key,
                            timeout=SSH_CONNECT_ATTEMPT_TIMEOUT_SEC,
                        )
                        connected_user = candidate_user
                        break
                    except Exception as exc:
                        last_ssh_error = (
                            f"user={candidate_user}: {type(exc).__name__}: {exc}"
                        )
                        if "SSH鍵が見つかりません" in str(exc) or "SSH鍵パスが不正" in str(exc):
                            fatal_ssh_config_error = True
                            break
                if conn and connected_user:
                    if connected_user != ssh_user:
                        ssh_user = connected_user
                        job_data["ssh_user"] = ssh_user
                        await _save_job(job_data)
                    break
                if fatal_ssh_config_error:
                    break
                time.sleep(SSH_CONNECT_RETRY_INTERVAL_SEC)

            if not conn:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "SSH_TIMEOUT"
                failure_msg = "SSH接続タイムアウト"
                if last_ssh_error:
                    failure_msg = f"{failure_msg}: {last_ssh_error}"
                job_data["error_message"] = failure_msg
                job_data["completed_at"] = datetime.now().isoformat()
                await _save_job(job_data)
                await cleanup_on_failure(failure_msg)
                return

            try:
                home_dir = conn.resolve_path("$HOME") or "/root"
                remote_base_dir = f"{home_dir}/.physical-ai"
                remote_run_dir = f"{remote_base_dir}/run"
                job_data["remote_base_dir"] = remote_base_dir
                await _save_job(job_data)

                # Create remote directory
                conn.mkdir_p(remote_run_dir)

                # Upload remote scripts
                setup_env_path = REMOTE_SCRIPTS_DIR / "setup_env.sh"
                entry_path = REMOTE_SCRIPTS_DIR / "entry.py"
                run_training_path = REMOTE_SCRIPTS_DIR / "run_training.sh"

                if setup_env_path.exists():
                    conn.upload_file(setup_env_path, f"{remote_run_dir}/setup_env.sh")
                if entry_path.exists():
                    conn.upload_file(entry_path, f"{remote_run_dir}/entry.py")
                if run_training_path.exists():
                    conn.upload_file(
                        run_training_path, f"{remote_run_dir}/run_training.sh"
                    )

                # Generate and upload .env file
                env_content = _generate_env_file(
                    job_id,
                    instance_id,
                    request.policy.type if request.policy else None,
                    supabase_access_token=supabase_access_token,
                    supabase_refresh_token=supabase_refresh_token,
                    supabase_user_id=supabase_user_id,
                )
                conn.upload_content(env_content, f"{remote_run_dir}/.env")

                # Generate and upload instance_info.env
                instance_info = _generate_instance_info_env(
                    job_id, instance_id, auto_delete=True
                )
                conn.upload_content(
                    instance_info, f"{remote_run_dir}/instance_info.env"
                )

                # Make scripts executable
                conn.exec_command(f"chmod +x {remote_run_dir}/setup_env.sh")
                conn.exec_command(f"chmod +x {remote_run_dir}/run_training.sh")

                # Run setup synchronously
                setup_cmd = f"cd {remote_run_dir} && timeout {SETUP_TIMEOUT_SEC}s bash setup_env.sh train 2>&1"
                setup_exit_code = run_remote_command(
                    conn,
                    setup_cmd,
                    stream_output=False,
                )
                if setup_exit_code != 0:
                    if setup_exit_code == 124:
                        job_data["status"] = "failed"
                        job_data["failure_reason"] = "SETUP_TIMEOUT"
                        job_data["error_message"] = "環境構築がタイムアウトしました"
                        job_data["completed_at"] = datetime.now().isoformat()
                        await _save_job(job_data)
                        await _upload_remote_logs_to_r2(conn, job_data)
                        await cleanup_on_failure("環境構築がタイムアウトしました")
                        return
                    job_data["status"] = "failed"
                    job_data["failure_reason"] = "SETUP_FAILED"
                    job_data["error_message"] = (
                        f"環境構築に失敗しました (exit={setup_exit_code})"
                    )
                    job_data["completed_at"] = datetime.now().isoformat()
                    await _save_job(job_data)
                    await _upload_remote_logs_to_r2(conn, job_data)
                    await cleanup_on_failure("環境構築に失敗しました")
                    return

                # Start training using RemoteExecutor with tmux
                executor = RemoteExecutor(conn, remote_base_dir=remote_run_dir)
                executor.run_background(
                    "bash run_training.sh train", session_name=TMUX_TRAIN_SESSION_NAME
                )
                job_data["status"] = "starting"
                await _save_job(job_data)

            finally:
                conn.disconnect()

        except Exception as e:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "UNKNOWN"
            job_data["error_message"] = str(e)
            job_data["completed_at"] = datetime.now().isoformat()
            await _save_job(job_data)
            await cleanup_on_failure(str(e))
    finally:
        reset_request_session(token)


# --- Checkpoint API ---

_checkpoint_index_manager = None


def _get_checkpoint_index_manager():
    """Get CheckpointIndexManager singleton."""
    global _checkpoint_index_manager
    if _checkpoint_index_manager is None:
        try:
            import os

            from percus_ai.storage import (
                CheckpointIndexManager,
                ManifestManager,
                R2SyncService,
            )

            manifest = ManifestManager()
            manifest.init_directories()
            bucket = os.getenv("R2_BUCKET", "percus-data")
            version = os.getenv("R2_VERSION", "v2")
            r2_service = R2SyncService(manifest, bucket, version=version)
            _checkpoint_index_manager = CheckpointIndexManager(r2_service)
        except Exception as e:
            raise HTTPException(
                status_code=503, detail=f"Failed to initialize checkpoint manager: {e}"
            )
    return _checkpoint_index_manager


def _get_dataset_info_from_manifest(dataset_id: str) -> CheckpointDatasetInfo:
    """Extract dataset info for compatibility checking."""
    try:
        from percus_ai.storage import ManifestManager, get_datasets_dir

        manifest = ManifestManager()
        datasets_dir = get_datasets_dir()
        dataset_path = datasets_dir / dataset_id

        camera_names = []
        action_dim = 0
        state_dim = 0

        # Read from dataset's meta/info.json if available
        info_path = dataset_path / "meta" / "info.json"
        if info_path.exists():
            with open(info_path) as f:
                info = json.load(f)

            # Extract camera names from features
            features = info.get("features", {})
            for key in features:
                if key.startswith("observation.images."):
                    cam_name = key.replace("observation.images.", "")
                    camera_names.append(cam_name)

            # Extract action/state dims
            if "action" in features:
                action_shape = features["action"].get("shape", [])
                action_dim = action_shape[0] if action_shape else 0

            if "observation.state" in features:
                state_shape = features["observation.state"].get("shape", [])
                state_dim = state_shape[0] if state_shape else 0

        return CheckpointDatasetInfo(
            camera_names=camera_names,
            action_dim=action_dim,
            state_dim=state_dim,
        )
    except Exception:
        return CheckpointDatasetInfo()


@router.get("/checkpoints", response_model=CheckpointListResponse)
async def list_checkpoints(
    policy_type: Optional[str] = Query(None, description="Filter by policy type"),
):
    """List all checkpoints with optional filtering.

    Returns all available checkpoints from R2 storage.
    Each checkpoint entry represents a training job with its latest step.
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Load index from R2
        index = checkpoint_mgr.load_index()
        if not index:
            return CheckpointListResponse(checkpoints=[], total=0)

        checkpoints = []
        for entry in index.checkpoints:
            # Filter by policy_type if specified
            if policy_type and entry.policy_type != policy_type:
                continue

            # Convert dataset_info
            ds_info = CheckpointDatasetInfo(
                camera_names=entry.dataset_info.camera_names
                if entry.dataset_info
                else [],
                action_dim=entry.dataset_info.action_dim if entry.dataset_info else 0,
                state_dim=entry.dataset_info.state_dim if entry.dataset_info else 0,
            )

            checkpoints.append(
                CheckpointInfo(
                    job_name=entry.job_name,
                    policy_type=entry.policy_type,
                    step=entry.latest_step,
                    dataset_id=entry.dataset_id,
                    dataset_info=ds_info,
                    created_at=entry.created_at,
                    size_mb=entry.size_mb,
                    pretrained_path=entry.pretrained_path,
                    author=entry.author if hasattr(entry, "author") else None,
                )
            )

        # Sort by created_at descending
        checkpoints.sort(key=lambda c: c.created_at, reverse=True)

        return CheckpointListResponse(
            checkpoints=checkpoints,
            total=len(checkpoints),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to list checkpoints from R2: {e}"
        )


@router.get("/checkpoints/{job_name}", response_model=CheckpointDetailResponse)
async def get_checkpoint(job_name: str):
    """Get detailed information about a specific checkpoint job.

    Includes all available step numbers for the job.
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Get job info
        entry = checkpoint_mgr.get_job_info(job_name)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Checkpoint not found: {job_name}"
            )

        # Get available steps
        steps = checkpoint_mgr.get_job_steps(job_name)

        # Convert dataset_info
        ds_info = CheckpointDatasetInfo(
            camera_names=entry.dataset_info.camera_names if entry.dataset_info else [],
            action_dim=entry.dataset_info.action_dim if entry.dataset_info else 0,
            state_dim=entry.dataset_info.state_dim if entry.dataset_info else 0,
        )

        return CheckpointDetailResponse(
            job_name=entry.job_name,
            policy_type=entry.policy_type,
            dataset_id=entry.dataset_id,
            dataset_info=ds_info,
            pretrained_path=entry.pretrained_path,
            available_steps=steps,
            latest_step=entry.latest_step,
            created_at=entry.created_at,
            size_mb=entry.size_mb,
            author=entry.author if hasattr(entry, "author") else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to get checkpoint info: {e}"
        )


@router.post(
    "/checkpoints/{job_name}/download", response_model=CheckpointDownloadResponse
)
async def download_checkpoint(
    job_name: str,
    request: Optional[CheckpointDownloadRequest] = None,
):
    """Download a checkpoint to local storage.

    Downloads either a specific step or the latest checkpoint.
    """
    step = request.step if request else None
    target_path = request.target_path if request else None

    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Verify checkpoint exists
        entry = checkpoint_mgr.get_job_info(job_name)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Checkpoint not found: {job_name}"
            )

        # Determine target path
        if target_path:
            download_path = Path(target_path)
        else:
            # Use default models directory
            models_dir = get_models_dir()
            download_path = models_dir / job_name

        download_path.mkdir(parents=True, exist_ok=True)

        # Download checkpoint
        if step is not None:
            # Verify step exists
            available_steps = checkpoint_mgr.get_job_steps(job_name)
            if step not in available_steps:
                raise HTTPException(
                    status_code=404,
                    detail=f"Step {step} not found. Available steps: {available_steps}",
                )
            success, error = checkpoint_mgr.download_step_checkpoint(
                job_name, step, download_path
            )
            downloaded_step = step
        else:
            success, error = checkpoint_mgr.download_latest_checkpoint(
                job_name, download_path
            )
            downloaded_step = entry.latest_step

        if not success:
            raise HTTPException(status_code=500, detail=f"Download failed: {error}")

        return CheckpointDownloadResponse(
            success=True,
            job_name=job_name,
            step=downloaded_step,
            target_path=str(download_path),
            message=f"Downloaded checkpoint step {downloaded_step}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to download checkpoint: {e}"
        )


@router.post(
    "/checkpoints/compatibility-check", response_model=DatasetCompatibilityCheckResponse
)
async def check_dataset_compatibility(request: DatasetCompatibilityCheckRequest):
    """Check if a dataset is compatible with a checkpoint for continue training.

    Validates:
    - Camera configuration (names and count)
    - Action dimension
    - State dimension
    """
    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # Get checkpoint info
        entry = checkpoint_mgr.get_job_info(request.checkpoint_job_name)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.checkpoint_job_name}",
            )

        # Get dataset info
        dataset_info = _get_dataset_info_from_manifest(request.dataset_id)

        # Perform compatibility check
        errors = []
        warnings = []

        checkpoint_ds_info = entry.dataset_info if entry.dataset_info else None

        if checkpoint_ds_info:
            # Camera check (critical)
            if set(checkpoint_ds_info.camera_names) != set(dataset_info.camera_names):
                errors.append(
                    f"Camera configuration mismatch. "
                    f"Checkpoint: {checkpoint_ds_info.camera_names}, "
                    f"Dataset: {dataset_info.camera_names}"
                )

            # Action dimension check (critical)
            if (
                checkpoint_ds_info.action_dim != dataset_info.action_dim
                and checkpoint_ds_info.action_dim > 0
            ):
                errors.append(
                    f"Action dimension mismatch. "
                    f"Checkpoint: {checkpoint_ds_info.action_dim}, "
                    f"Dataset: {dataset_info.action_dim}"
                )

            # State dimension check (warning only)
            if (
                checkpoint_ds_info.state_dim != dataset_info.state_dim
                and checkpoint_ds_info.state_dim > 0
            ):
                warnings.append(
                    f"State dimension differs. "
                    f"Checkpoint: {checkpoint_ds_info.state_dim}, "
                    f"Dataset: {dataset_info.state_dim}"
                )

            cp_info = CheckpointDatasetInfo(
                camera_names=checkpoint_ds_info.camera_names,
                action_dim=checkpoint_ds_info.action_dim,
                state_dim=checkpoint_ds_info.state_dim,
            )
        else:
            cp_info = CheckpointDatasetInfo()
            warnings.append("Checkpoint has no dataset info for comparison")

        return DatasetCompatibilityCheckResponse(
            is_compatible=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            checkpoint_info=cp_info,
            dataset_info=dataset_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compatibility check failed: {e}")


@router.post("/jobs/continue", response_model=JobCreateResponse)
async def create_continue_job(
    request: JobCreateContinueRequest,
    background_tasks: BackgroundTasks,
):
    """Create a continue training job from checkpoint.

    Downloads checkpoint from R2 and starts training with additional steps.
    """
    checkpoint_config = request.checkpoint
    dataset_config = request.dataset
    training_config = request.training

    try:
        checkpoint_mgr = _get_checkpoint_index_manager()

        # 1. Validate checkpoint exists
        checkpoint_entry = checkpoint_mgr.get_job_info(checkpoint_config.job_name)
        if not checkpoint_entry:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {checkpoint_config.job_name}",
            )

        # Determine step to use
        step = checkpoint_config.step or checkpoint_entry.latest_step

        # Verify step exists
        available_steps = checkpoint_mgr.get_job_steps(checkpoint_config.job_name)
        if step not in available_steps:
            raise HTTPException(
                status_code=400,
                detail=f"Step {step} not available. Available: {available_steps}",
            )

        # 2. Validate dataset compatibility if using different dataset
        if not dataset_config.use_original:
            compat_result = await check_dataset_compatibility(
                DatasetCompatibilityCheckRequest(
                    checkpoint_job_name=checkpoint_config.job_name,
                    dataset_id=dataset_config.id,
                )
            )
            if not compat_result.is_compatible:
                raise HTTPException(
                    status_code=400,
                    detail=f"Dataset incompatible: {'; '.join(compat_result.errors)}",
                )

        # 3. Generate job name
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        author = request.author or _default_author_user_id()
        job_name = f"{checkpoint_config.job_name}_continue_{author}_{date_str}"
        job_id = str(uuid.uuid4())

        # 4. Prepare training config
        dataset_id = (
            checkpoint_entry.dataset_id
            if dataset_config.use_original
            else dataset_config.id
        )

        # Calculate total steps
        total_steps = step + training_config.additional_steps

        # Check if Verda credentials are available
        client = _get_verda_client()
        if not client:
            raise HTTPException(
                status_code=503,
                detail="Verda/DataCrunch credentials not configured.",
            )

        now = datetime.now().isoformat()

        # Select instance type
        instance_type = _select_instance_type(
            client,
            request.cloud.gpu_model,
            request.cloud.gpus_per_instance,
        )

        # Get SSH key
        ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
        ssh_private_key = os.environ.get(
            "VERDA_SSH_PRIVATE_KEY",
            str(Path.home() / ".ssh" / "id_rsa"),
        )
        ssh_user = _get_default_ssh_user()
        try:
            ssh_private_key = _resolve_ssh_private_key_path(ssh_private_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if not ssh_key_name:
            raise HTTPException(
                status_code=503,
                detail="SSH key not configured. Set VERDA_SSH_KEY_NAME.",
            )

        ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

        # Find available location
        location = _find_location(
            client,
            instance_type,
            request.cloud.location,
            request.cloud.is_spot,
        )

        # Create instance
        instance_id = _create_instance(
            client,
            instance_type=instance_type,
            ssh_key_id=ssh_key_id,
            location=location,
            is_spot=request.cloud.is_spot,
            storage_size=request.cloud.storage_size,
            hostname=f"train-{job_id[:16]}",
        )

        # Save job info (status: starting)
        profile_instance_id, profile_snapshot = await _resolve_profile_info(dataset_id)
        job_data = {
            "job_id": job_id,
            "job_name": job_name,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "mode": "resume_local",
            "profile_instance_id": profile_instance_id,
            "profile_snapshot": profile_snapshot,
            "continue_from": {
                "job_name": checkpoint_config.job_name,
                "step": step,
            },
            "dataset_id": dataset_id,
            "policy_type": checkpoint_entry.policy_type,
            "ssh_user": ssh_user,
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root/.physical-ai",
            "created_at": now,
            "updated_at": now,
            "gpu_model": request.cloud.gpu_model,
            "gpus_per_instance": request.cloud.gpus_per_instance,
            "total_steps": total_steps,
            "additional_steps": training_config.additional_steps,
            "author": author,
            "training_config": {
                "dataset": request.dataset.model_dump(),
                "policy": policy_payload,
                "training": training_payload,
                "validation": validation_payload or {"enable": False},
                "early_stopping": early_stopping_payload or {"enable": False},
                "checkpoint": {
                    "job_name": checkpoint_config.job_name,
                    "step": step,
                },
            },
        }
        await _save_job(job_data)

        # TODO: Start background task to wait for IP and deploy continue training
        # For now, return the job info

        return JobCreateResponse(
            job_id=job_id,
            instance_id=instance_id,
            status="starting",
            message=f"Continue training job created from {checkpoint_config.job_name} step {step}",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create continue job: {e}"
        )


# --- WebSocket Log Streaming ---


@router.websocket("/ws/jobs/{job_id}/logs")
async def websocket_stream_logs(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time log streaming via SSH.

    Connects to the remote instance via SSH and streams logs using tail -f.
    Client receives log lines as they arrive.

    Messages sent to client:
    - {"type": "connected", "message": "SSH接続完了"}
    - {"type": "log", "line": "..."}
    - {"type": "status", "status": "completed|failed|stopped"}
    - {"type": "error", "error": "..."}
    - {"type": "heartbeat"}
    """
    await websocket.accept()
    log_type = websocket.query_params.get("log_type", "training")
    if log_type not in ("training", "setup"):
        await websocket.send_json(
            {"type": "error", "error": f"Invalid log_type: {log_type}"}
        )
        await websocket.close()
        return
    logger.info(f"WebSocket log stream client connected for job {job_id}")

    job_data = await _load_job(job_id)
    if not job_data:
        await websocket.send_json(
            {"type": "error", "error": f"Job not found: {job_id}"}
        )
        await websocket.close()
        return

    # Check job has IP
    ip = job_data.get("ip")
    if not ip:
        await websocket.send_json({"type": "error", "error": "Job has no IP address"})
        await websocket.close()
        return

    status_subscription_id = None
    status_queue = None
    realtime_manager = None
    ssh_conn: Optional[SSHConnection] = None
    try:
        try:
            realtime_manager = _get_training_job_realtime_manager()
            status_subscription_id, status_queue = await realtime_manager.subscribe(
                job_id,
                asyncio.get_running_loop(),
            )
        except Exception as e:
            await websocket.send_json(
                {"type": "error", "error": f"Realtime購読に失敗しました: {e}"}
            )
            await websocket.close()
            return

        # Connect SSH in thread pool
        loop = asyncio.get_event_loop()
        ssh_conn = await loop.run_in_executor(
            _executor, lambda: _get_ssh_connection_for_job(job_data, timeout=30)
        )

        if not ssh_conn:
            await websocket.send_json(
                {"type": "error", "error": "SSH接続に失敗しました"}
            )
            await websocket.close()
            return

        await websocket.send_json({"type": "connected", "message": "SSH接続完了"})

        # Determine log file path
        if log_type == "setup":
            log_file = _get_setup_log_file_path(job_data)
        else:
            log_file = _get_training_log_file_path(job_data)

        # Start tail -f in a channel
        transport = ssh_conn.client.get_transport()
        channel = transport.open_session()
        channel.exec_command(f"tail -f {log_file} 2>/dev/null")
        channel.setblocking(0)

        last_heartbeat = asyncio.get_event_loop().time()

        while True:
            # Check for incoming data from SSH
            try:
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if data:
                        lines = data.decode("utf-8", errors="replace").split("\n")
                        for line in lines:
                            if line.strip():
                                await websocket.send_json({"type": "log", "line": line})

                # Check if channel closed (process ended)
                if channel.exit_status_ready():
                    await websocket.send_json(
                        {
                            "type": "status",
                            "status": "stream_ended",
                            "message": "ログストリーム終了",
                        }
                    )
                    await _mark_job_completed(job_id)
                    break

            except Exception as e:
                logger.debug(f"SSH recv error: {e}")

            # Send heartbeat every 5 seconds
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat > 5:
                await websocket.send_json({"type": "heartbeat"})
                last_heartbeat = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES:
                await websocket.send_json(
                    {
                        "type": "status",
                        "status": status,
                        "message": f"ジョブ状態: {status}",
                    }
                )
                break

            # Small delay to avoid busy loop
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info(f"WebSocket log stream client disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket log stream error for job {job_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        if ssh_conn:
            try:
                ssh_conn.disconnect()
            except Exception:
                pass
        if status_subscription_id and realtime_manager:
            realtime_manager.unsubscribe(status_subscription_id)


@router.websocket("/ws/jobs/{job_id}/session")
async def websocket_job_session(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for unified job session with progressive loading.

    This endpoint maintains a single SSH connection for the entire session,
    providing immediate local job info followed by SSH-dependent data.

    Server -> Client messages:
    - {"type": "job_info", "data": {...}}     # Immediate (from local JSON)
    - {"type": "ssh_connecting"}               # SSH connection starting
    - {"type": "ssh_connected"}                # SSH connection established
    - {"type": "ssh_error", "error": "..."}    # SSH connection failed
    - {"type": "remote_status", "status": "running|stopped|error|unreachable"}
    - {"type": "progress", "step": "...", "loss": "..."}
    - {"type": "log", "line": "..."}           # Log line (when streaming)
    - {"type": "log_stream_started"}           # Log streaming started
    - {"type": "log_stream_stopped"}           # Log streaming stopped
    - {"type": "heartbeat"}                    # Every 5 seconds

    Client -> Server messages:
    - {"action": "start_logs"}                 # Start log streaming
    - {"action": "stop_logs"}                  # Stop log streaming
    - {"action": "refresh"}                    # Refresh status/progress
    """
    await websocket.accept()
    logger.info(f"WebSocket job session connected for job {job_id}")

    # Load job data immediately
    job_data = await _load_job(job_id)
    if not job_data:
        await websocket.send_json(
            {"type": "error", "error": f"Job not found: {job_id}"}
        )
        await websocket.close()
        return

    status_subscription_id = None
    status_queue = None
    realtime_manager = None
    try:
        realtime_manager = _get_training_job_realtime_manager()
        status_subscription_id, status_queue = await realtime_manager.subscribe(
            job_id,
            asyncio.get_running_loop(),
        )
    except Exception as e:
        await websocket.send_json(
            {"type": "error", "error": f"Realtime購読に失敗しました: {e}"}
        )
        await websocket.close()
        return

    # Send job info immediately (no SSH needed)
    await websocket.send_json(
        {
            "type": "job_info",
            "data": {
                "job_id": job_data.get("job_id"),
                "job_name": job_data.get("job_name"),
                "status": job_data.get("status"),
                "mode": job_data.get("mode"),
                "gpu_model": job_data.get("gpu_model"),
                "gpus_per_instance": job_data.get("gpus_per_instance"),
                "ip": job_data.get("ip"),
                "instance_id": job_data.get("instance_id"),
                "created_at": job_data.get("created_at"),
                "started_at": job_data.get("started_at"),
                "failure_reason": job_data.get("failure_reason"),
                "termination_reason": job_data.get("termination_reason"),
                "cleanup_status": job_data.get("cleanup_status"),
                "deleted_at": job_data.get("deleted_at"),
            },
        }
    )

    ssh_conn: Optional[SSHConnection] = None
    log_channel = None
    is_streaming_logs = False

    try:
        # Check if job has IP (needed for SSH)
        ip = job_data.get("ip")
        if not ip:
            await websocket.send_json(
                {
                    "type": "ssh_error",
                    "error": "Job has no IP address (instance may not be ready)",
                }
            )
            # Continue without SSH - user can still see local info
            await _run_session_loop_no_ssh(websocket, status_queue, job_id)
            return

        # Start SSH connection
        await websocket.send_json({"type": "ssh_connecting"})

        # Connect SSH in thread pool
        loop = asyncio.get_event_loop()
        ssh_conn = await loop.run_in_executor(
            _executor, lambda: _get_ssh_connection_for_job(job_data, timeout=30)
        )

        if not ssh_conn:
            await websocket.send_json(
                {"type": "ssh_error", "error": "SSH接続に失敗しました"}
            )
            await _run_session_loop_no_ssh(websocket, status_queue, job_id)
            return

        await websocket.send_json({"type": "ssh_connected"})

        # Get initial remote status and progress (pass raw paramiko client to helper functions)
        await _send_remote_status(websocket, ssh_conn.client)
        await _send_progress(websocket, job_id)

        # Determine log file path for later use
        log_file = _get_training_log_file_path(job_data)

        last_heartbeat = asyncio.get_event_loop().time()
        last_progress_update = asyncio.get_event_loop().time()

        while True:
            now = asyncio.get_event_loop().time()

            # Handle incoming client messages (non-blocking)
            try:
                # Use wait_for with short timeout to check for messages
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                action = message.get("action")

                if action == "start_logs" and not is_streaming_logs:
                    # Start log streaming using same SSH connection
                    transport = ssh_conn.client.get_transport()
                    if transport and transport.is_active():
                        log_channel = transport.open_session()
                        log_channel.exec_command(f"tail -f {log_file} 2>/dev/null")
                        log_channel.setblocking(0)
                        is_streaming_logs = True
                        await websocket.send_json({"type": "log_stream_started"})

                elif action == "stop_logs" and is_streaming_logs:
                    # Stop log streaming
                    if log_channel:
                        try:
                            log_channel.close()
                        except Exception:
                            pass
                        log_channel = None
                    is_streaming_logs = False
                    await websocket.send_json({"type": "log_stream_stopped"})

                elif action == "refresh":
                    # Refresh status and progress
                    await _send_remote_status(websocket, ssh_conn.client)
                    await _send_progress(websocket, job_id)

            except asyncio.TimeoutError:
                pass  # No message received, continue

            # If streaming logs, read from channel
            if is_streaming_logs and log_channel:
                try:
                    if log_channel.recv_ready():
                        data = log_channel.recv(4096)
                        if data:
                            lines = data.decode("utf-8", errors="replace").split("\n")
                            for line in lines:
                                if line.strip():
                                    await websocket.send_json(
                                        {"type": "log", "line": line}
                                    )

                    # Check if log process ended
                    if log_channel.exit_status_ready():
                        is_streaming_logs = False
                        await websocket.send_json({"type": "log_stream_stopped"})
                        log_channel = None

                except Exception as e:
                    logger.debug(f"Log channel read error: {e}")

            # Send heartbeat every 5 seconds
            if now - last_heartbeat > 5:
                await websocket.send_json({"type": "heartbeat"})
                last_heartbeat = now

            # Update progress every 10 seconds (if not streaming logs)
            if not is_streaming_logs and now - last_progress_update > 10:
                await _send_progress(websocket, job_id)
                last_progress_update = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES:
                await websocket.send_json(
                    {"type": "job_status_changed", "status": status}
                )
                break

            await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        logger.info(f"WebSocket job session disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket job session error for job {job_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        if log_channel:
            try:
                log_channel.close()
            except Exception:
                pass
        if ssh_conn:
            try:
                ssh_conn.disconnect()
            except Exception:
                pass
        if status_subscription_id and realtime_manager:
            realtime_manager.unsubscribe(status_subscription_id)


async def _run_session_loop_no_ssh(
    websocket: WebSocket,
    status_queue: "asyncio.Queue",
    job_id: str,
) -> None:
    """Run session loop without SSH connection (local data only)."""
    last_heartbeat = asyncio.get_event_loop().time()
    last_progress_update = asyncio.get_event_loop().time()

    try:
        while True:
            now = asyncio.get_event_loop().time()

            # Handle incoming client messages
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                action = message.get("action")

                if action == "start_logs":
                    await websocket.send_json(
                        {
                            "type": "ssh_error",
                            "error": "SSH接続がないためログを取得できません",
                        }
                    )

            except asyncio.TimeoutError:
                pass

            # Send heartbeat every 5 seconds
            if now - last_heartbeat > 5:
                await websocket.send_json({"type": "heartbeat"})
                last_heartbeat = now

            if now - last_progress_update > 10:
                await _send_progress(websocket, job_id)
                last_progress_update = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES_WITH_PENDING:
                await websocket.send_json(
                    {"type": "job_status_changed", "status": status}
                )
                break

            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info(f"WebSocket job session (no SSH) disconnected for job {job_id}")
    except Exception as e:
        logger.error(f"WebSocket job session (no SSH) error: {e}")


async def _send_remote_status(websocket: WebSocket, ssh_client) -> None:
    """Send remote process status via existing SSH connection."""
    try:
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(
            _executor,
            lambda: _exec_ssh_command(
                ssh_client,
                (
                    f"tmux has-session -t {TMUX_TRAIN_SESSION_NAME} 2>/dev/null && echo 'running' "
                    f"|| (tmux has-session -t {TMUX_SETUP_SESSION_NAME} 2>/dev/null && echo 'starting' || echo 'stopped')"
                ),
            ),
        )
        await websocket.send_json(
            {"type": "remote_status", "status": status.strip() if status else "unknown"}
        )
    except Exception as e:
        logger.debug(f"Failed to get remote status: {e}")
        await websocket.send_json({"type": "remote_status", "status": "error"})


async def _send_progress(websocket: WebSocket, job_id: str) -> None:
    """Send training progress from Supabase metrics."""
    try:
        loop = asyncio.get_event_loop()
        latest_train, latest_val = await loop.run_in_executor(
            _executor,
            lambda: _get_latest_metrics(job_id),
        )
        latest = latest_train or latest_val
        step = latest.get("step") if latest else None
        loss = latest.get("loss") if latest else None
        await websocket.send_json(
            {
                "type": "progress",
                "step": str(step) if step is not None else "N/A",
                "loss": str(loss) if loss is not None else "N/A",
                "train": latest_train,
                "val": latest_val,
            }
        )
    except Exception as e:
        logger.debug(f"Failed to get progress: {e}")


def _exec_ssh_command(ssh_client, command: str) -> Optional[str]:
    """Execute SSH command and return stdout."""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=10)
        return stdout.read().decode()
    except Exception:
        return None
