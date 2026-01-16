"""Training jobs API router."""

import asyncio
import inspect
import json
import logging
import os
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import yaml
from verda import VerdaClient
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, WebSocket, WebSocketDisconnect

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
    # GPU availability
    GpuAvailabilityInfo,
    GpuAvailabilityResponse,
    VerdaStorageActionFailure,
    VerdaStorageActionRequest,
    VerdaStorageActionResult,
    VerdaStorageItem,
    VerdaStorageListResponse,
)
from percus_ai.storage import get_configs_dir, get_project_root, get_models_dir
from percus_ai.db import get_supabase_async_client, get_supabase_client
from percus_ai.training.ssh.client import SSHConnection
from percus_ai.training.ssh.executor import RemoteExecutor

logger = logging.getLogger(__name__)
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
        event_type = payload.get("eventType") or payload.get("event_type") or payload.get("type")
        if isinstance(event_type, str):
            return event_type.upper()
        data = payload.get("data")
        if isinstance(data, dict):
            event_type = data.get("eventType") or data.get("event_type") or data.get("type")
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
    def __init__(self, job_id: str, loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue") -> None:
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
            self._subscribers[subscriber_id] = _TrainingJobRealtimeSubscriber(job_id, loop, queue)
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
                raise RuntimeError("Supabase Realtime client is not available (async client required)")

            channel_factory = getattr(realtime, "channel", None) or getattr(self._client, "channel", None)
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
                    raise RuntimeError("Supabase Realtime channel handler is not available")
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
                raise RuntimeError("Supabase Realtime channel.subscribe is not available")

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

# Remote scripts directory - contains setup_env.sh, entry.py, etc.
# These scripts are deployed to remote instances for training
REMOTE_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "features" / "percus_ai" / "training" / "remote"


# --- SSH utilities for remote deployment ---
# Uses SSHConnection from percus_ai.training.ssh.client for consistency with executor.py


def _create_ssh_connection(
    ip: str,
    user: str,
    private_key_path: str,
    timeout: int = 300,
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
    conn = SSHConnection(host=ip, user=user, private_key_path=key_path)
    conn.connect(timeout_sec=timeout)
    return conn


def _generate_training_config_yaml(request: "JobCreateRequest", job_id: str) -> str:
    """Generate training config YAML from JobCreateRequest."""
    config = {
        "metadata": {
            "name": request.name,
            "job_id": job_id,
        },
        "dataset": {
            "id": request.dataset.id,
            "source": request.dataset.source,
        },
        "policy": {
            "type": request.policy.type,
        },
        "training": {},
        "wandb": {
            "enable": request.wandb_enable,
        },
    }

    # Add optional dataset fields
    if request.dataset.hf_repo_id:
        config["dataset"]["repo_id"] = request.dataset.hf_repo_id

    # Add optional policy fields
    if request.policy.pretrained_path:
        config["policy"]["pretrained_path"] = request.policy.pretrained_path
    if request.policy.compile_model is not None:
        config["policy"]["compile_model"] = request.policy.compile_model
    if request.policy.gradient_checkpointing is not None:
        config["policy"]["gradient_checkpointing"] = request.policy.gradient_checkpointing
    if request.policy.dtype:
        config["policy"]["dtype"] = request.policy.dtype

    # Add optional training fields
    if request.training.steps:
        config["training"]["steps"] = request.training.steps
    if request.training.batch_size:
        config["training"]["batch_size"] = request.training.batch_size
    if request.training.save_freq:
        config["training"]["save_freq"] = request.training.save_freq

    # Add checkpoint repo if specified
    if request.checkpoint_repo_id:
        config["checkpoint"] = {
            "repo_id": request.checkpoint_repo_id,
            "upload_every_save": True,
        }

    return yaml.dump(config, default_flow_style=False, allow_unicode=True)


def _generate_env_file(job_id: str, instance_id: str, auto_delete: bool = True) -> str:
    """Generate .env file content with required credentials."""
    lines = []

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
    r2_endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("S3_ENDPOINT_URL")
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_ACCESS_KEY")
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
    r2_bucket = os.environ.get("R2_BUCKET") or os.environ.get("S3_BUCKET")
    if r2_bucket:
        lines.append(f"R2_BUCKET={r2_bucket}")
        lines.append(f"S3_BUCKET={r2_bucket}")

    # GitHub token for private repo access (physical-ai-features)
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        lines.append(f"GH_TOKEN={gh_token}")

    # Supabase credentials for remote status updates
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if supabase_url and supabase_key:
        lines.append(f"SUPABASE_URL={supabase_url}")
        if os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            lines.append(f"SUPABASE_SERVICE_ROLE_KEY={supabase_key}")
        else:
            lines.append(f"SUPABASE_ANON_KEY={supabase_key}")

    return "\n".join(lines) + "\n"


def _generate_instance_info_env(job_id: str, instance_id: str, auto_delete: bool = True) -> str:
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


def _restore_verda_volumes(client: VerdaClient, volume_ids: list[str]) -> None:
    """Restore volumes from trash via Verda API."""
    payload = {"action": "restore", "id": volume_ids}
    client._http_client.put("/volumes", json=payload)


def _chunk_list(items: list[str], chunk_size: int = 20) -> list[list[str]]:
    """Split items into smaller chunks."""
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


_verda_client_local = threading.local()


def _get_thread_verda_client() -> Optional[VerdaClient]:
    """Get thread-local Verda client."""
    client = getattr(_verda_client_local, "client", None)
    if client is None:
        client = _get_verda_client()
        _verda_client_local.client = client
    return client


def _perform_verda_volume_action(action: str, volume_id: str, is_permanent: bool) -> None:
    """Perform a Verda volume action for a single volume."""
    client = _get_thread_verda_client()
    if not client:
        raise RuntimeError("Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)")

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
        raise RuntimeError("Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)")

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


def _load_job(job_id: str, include_deleted: bool = False) -> Optional[dict]:
    """Load job from DB."""
    client = get_supabase_client()
    response = client.table(DB_TABLE).select("*").eq("job_id", job_id).execute()
    records = response.data or []
    if not records:
        return None
    record = records[0]
    if not include_deleted and record.get("deleted_at"):
        return None
    metadata = record.get("job_metadata") or {}
    if isinstance(metadata, dict):
        record.update(metadata)
    return record


def _save_job(job_data: dict) -> None:
    """Upsert job into DB."""
    client = get_supabase_client()
    job_data["updated_at"] = datetime.now().isoformat()

    fixed_fields = {
        "job_id",
        "project_id",
        "model_id",
        "policy_type",
        "dataset_id",
        "status",
        "failure_reason",
        "termination_reason",
        "cleanup_status",
        "deleted_at",
        "training_config",
        "compute_profile",
        "author",
        "base_checkpoint",
        "notes",
        "instance_id",
        "ip",
        "config_name",
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
        "job_metadata",
    }
    record = {k: job_data.get(k) for k in fixed_fields if k in job_data}
    metadata = {k: v for k, v in job_data.items() if k not in fixed_fields}
    if metadata:
        record["job_metadata"] = metadata

    client.table(DB_TABLE).upsert(record, on_conflict="job_id").execute()


def _update_cleanup_status(job_id: str, status: str) -> None:
    job_data = _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    job_data["cleanup_status"] = status
    _save_job(job_data)


def _resolve_project_id(dataset_id: Optional[str]) -> Optional[str]:
    if not dataset_id:
        return None
    client = get_supabase_client()
    rows = client.table("datasets").select("project_id").eq("id", dataset_id).execute().data or []
    if rows:
        return rows[0].get("project_id")
    return None


def _upsert_model_for_job(job_data: dict) -> None:
    client = get_supabase_client()
    model_id = job_data.get("model_id") or job_data.get("job_id")
    project_id = job_data.get("project_id") or _resolve_project_id(job_data.get("dataset_id"))
    if not model_id or not project_id:
        logger.warning("Model upsert skipped (model_id or project_id missing)")
        return

    training_cfg = job_data.get("training_config") or {}
    training_params = training_cfg.get("training") if isinstance(training_cfg, dict) else {}
    policy_type = job_data.get("policy_type")
    if not policy_type and isinstance(training_cfg, dict):
        policy = training_cfg.get("policy") or {}
        policy_type = policy.get("type")

    now = datetime.now().isoformat()
    payload = {
        "id": model_id,
        "name": model_id,
        "project_id": project_id,
        "dataset_id": job_data.get("dataset_id"),
        "policy_type": policy_type,
        "training_steps": training_params.get("steps"),
        "batch_size": training_params.get("batch_size"),
        "source": "r2",
        "status": "active",
        "created_at": job_data.get("created_at") or now,
        "updated_at": now,
    }
    client.table("models").upsert(payload, on_conflict="id").execute()


def _mark_job_completed(job_id: str, termination_reason: str = "REMOTE_EXIT") -> None:
    job_data = _load_job(job_id, include_deleted=True)
    if not job_data:
        return
    if job_data.get("status") not in ("running", "starting", "deploying"):
        return
    job_data["status"] = "completed"
    job_data["termination_reason"] = termination_reason
    job_data["completed_at"] = datetime.now().isoformat()
    if not job_data.get("model_id"):
        job_data["model_id"] = job_data.get("job_id")
    _save_job(job_data)
    _upsert_model_for_job(job_data)


def _list_jobs(days: int = 7) -> list[dict]:
    """List jobs from DB.

    Args:
        days: Return jobs from past N days.
              Running/starting jobs are always included.
    """
    client = get_supabase_client()
    response = client.table(DB_TABLE).select("*").is_("deleted_at", "null").execute()
    jobs = response.data or []

    cutoff_date = datetime.now() - timedelta(days=days)
    filtered = []
    for job in jobs:
        metadata = job.get("job_metadata") or {}
        if isinstance(metadata, dict):
            job.update(metadata)
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

# tmux session name for training jobs (consistent with job startup)
TMUX_SESSION_NAME = "instance_setup"

# Timeout constants
IP_WAIT_TIMEOUT_SEC = 900  # 15 minutes to wait for IP assignment
SSH_WAIT_TIMEOUT_SEC = 300  # 5 minutes to wait for SSH to be ready
LOG_STREAM_MAX_SEC = 30  # Max time to stream initial logs
LOG_STREAM_INITIAL_LINES = 10  # Number of log lines to show initially


def _get_log_file_path(job_data: dict) -> str:
    """Get the remote log file path for a job.

    Args:
        job_data: Job data dict containing remote_base_dir and mode

    Returns:
        Full path to the log file on the remote instance
    """
    mode = job_data.get("mode", "train")
    remote_base_dir = job_data.get("remote_base_dir", "/root")
    return f"{remote_base_dir}/lerobot_run/setup_env_{mode}.log"


def _get_ssh_connection_for_job(job_data: dict, timeout: int = 30) -> Optional[SSHConnection]:
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

    try:
        key_path = Path(job_data.get("ssh_private_key", "~/.ssh/id_rsa")).expanduser()
        conn = SSHConnection(
            host=ip,
            user=job_data.get("ssh_user", "root"),
            private_key_path=key_path,
        )
        conn.connect(timeout_sec=timeout)
        return conn
    except Exception:
        return None


def _check_remote_status(job_data: dict) -> str:
    """Check remote process status via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return "unreachable"

    try:
        cmd = f"tmux has-session -t {TMUX_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout.strip()
    except Exception:
        return "error"
    finally:
        conn.disconnect()


def _get_remote_logs(job_data: dict, lines: int = 100) -> Optional[str]:
    """Get remote logs via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return None

    try:
        log_file = _get_log_file_path(job_data)
        cmd = f"tail -n {lines} {log_file} 2>/dev/null || echo '[Log file not found]'"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        return stdout
    except Exception:
        return None
    finally:
        conn.disconnect()


def _get_remote_progress(job_data: dict) -> Optional[dict]:
    """Get training progress via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return None

    try:
        log_file = _get_log_file_path(job_data)

        # Get step info
        cmd = f"grep -oE 'step:[0-9]+|Step [0-9]+|optimization_step=[0-9]+' {log_file} 2>/dev/null | tail -1 || true"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        step_line = stdout.strip()

        # Get loss info
        cmd = f"grep -oE 'loss[^=]*=[0-9.]+|Loss: [0-9.]+' {log_file} 2>/dev/null | tail -1 || true"
        exit_code, stdout, stderr = conn.exec_command(cmd)
        loss_line = stdout.strip()

        return {
            "step": step_line or "N/A",
            "loss": loss_line or "N/A",
        }
    except Exception:
        return None
    finally:
        conn.disconnect()


def _stop_remote_job(job_data: dict) -> bool:
    """Stop remote training job via SSH."""
    conn = _get_ssh_connection_for_job(job_data)
    if not conn:
        return False

    try:
        cmd = f"tmux kill-session -t {TMUX_SESSION_NAME} 2>/dev/null || true"
        conn.exec_command(cmd)
        return True
    except Exception:
        return False
    finally:
        conn.disconnect()


# --- API Endpoints ---


# Known GPU models to check (in priority order)
GPU_MODELS_QUICK = ["B300", "B200", "H200", "H100", "A100"]
GPU_COUNTS_QUICK = [1]  # Only check count=1 for speed
KNOWN_LOCATIONS = ["FIN-01", "FIN-02", "FIN-03"]

# Cache for GPU availability (TTL: 10 minutes)
_gpu_availability_cache: dict = {}
_gpu_availability_cache_time: float = 0
_GPU_CACHE_TTL = 600  # 10 minutes


def _check_availability_for_config(client, instance_type: str, is_spot: bool) -> list[str]:
    """Check availability at locations. Returns as soon as one available location is found."""
    for loc in KNOWN_LOCATIONS:
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=loc,
            ):
                return [loc]  # Early exit: found one available location
        except Exception:
            pass
    return []


@router.get("/gpu-availability", response_model=GpuAvailabilityResponse)
async def get_gpu_availability():
    """Check GPU availability for main configurations (B300, B200, H200, H100, A100 x1).

    Uses parallel API calls and caching (10 min TTL) for fast response.
    Stops location search as soon as one available location is found.
    """
    global _gpu_availability_cache, _gpu_availability_cache_time

    # Check cache
    if time.time() - _gpu_availability_cache_time < _GPU_CACHE_TTL and _gpu_availability_cache:
        return GpuAvailabilityResponse(
            available=_gpu_availability_cache.get("available", []),
            checked_at=datetime.fromtimestamp(_gpu_availability_cache_time),
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

        # Build list of (gpu_model, gpu_count, instance_type, spot_price) to check
        configs_to_check = []
        for gpu_model in GPU_MODELS_QUICK:
            for gpu_count in GPU_COUNTS_QUICK:
                # Find matching instance type
                for t in instance_types:
                    itype = t.instance_type
                    count = _extract_gpu_count(itype)
                    if count is None:
                        continue

                    if count == gpu_count and gpu_model.upper() in itype.upper():
                        spot_price = getattr(t, "spot_price_per_hour", None)
                        configs_to_check.append((gpu_model, gpu_count, itype, spot_price))
                        break

        # Check availability in parallel using ThreadPoolExecutor
        # Each config needs 2 checks (spot + on-demand), done in parallel
        results = {}  # key: (gpu_model, gpu_count) -> {"spot_locs": [], "ondemand_locs": []}

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
                key = (gpu_model, gpu_count)
                results[key] = {"instance_type": instance_type, "spot_price": spot_price, "spot_locs": [], "ondemand_locs": []}

                # Submit spot check
                future_spot = executor.submit(_check_availability_for_config, client, instance_type, True)
                futures[future_spot] = (key, "spot")

                # Submit on-demand check
                future_ondemand = executor.submit(_check_availability_for_config, client, instance_type, False)
                futures[future_ondemand] = (key, "ondemand")

            # Collect results
            for future in as_completed(futures, timeout=30):
                key, check_type = futures[future]
                try:
                    locs = future.result()
                    if check_type == "spot":
                        results[key]["spot_locs"] = locs
                    else:
                        results[key]["ondemand_locs"] = locs
                except Exception:
                    pass

        # Build response
        for (gpu_model, gpu_count), data in results.items():
            available.append(GpuAvailabilityInfo(
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                instance_type=data["instance_type"],
                spot_available=len(data["spot_locs"]) > 0,
                ondemand_available=len(data["ondemand_locs"]) > 0,
                spot_locations=data["spot_locs"],
                ondemand_locations=data["ondemand_locs"],
                spot_price_per_hour=data["spot_price"],
            ))

        # Update cache
        _gpu_availability_cache = {"available": available}
        _gpu_availability_cache_time = time.time()

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
        raise HTTPException(status_code=502, detail=f"Verda APIに接続できません: {e}") from e

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
        raise HTTPException(status_code=502, detail=f"Verda APIに接続できません: {e}") from e

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
        raise HTTPException(status_code=502, detail=f"Verda APIに接続できません: {e}") from e

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
        raise HTTPException(status_code=502, detail=f"Verda APIに接続できません: {e}") from e

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
        # Check cache first
        if time.time() - _gpu_availability_cache_time < _GPU_CACHE_TTL and _gpu_availability_cache:
            await websocket.send_json({"type": "cached", "message": "キャッシュから取得"})
            for item in _gpu_availability_cache.get("available", []):
                await websocket.send_json({
                    "type": "result",
                    "gpu_model": item.gpu_model,
                    "gpu_count": item.gpu_count,
                    "spot_available": item.spot_available,
                    "ondemand_available": item.ondemand_available,
                })
            await websocket.send_json({"type": "complete", "message": "確認完了"})
            await websocket.close()
            return

        client = _get_verda_client()
        if not client:
            await websocket.send_json({
                "type": "error",
                "error": "Verda認証情報が設定されていません"
            })
            await websocket.close()
            return

        await websocket.send_json({"type": "start", "message": "GPU空き状況を確認中..."})

        # Get instance types
        loop = asyncio.get_event_loop()
        instance_types = await loop.run_in_executor(_executor, client.instance_types.get)

        # Build configs to check
        configs_to_check = []
        for gpu_model in GPU_MODELS_QUICK:
            for gpu_count in GPU_COUNTS_QUICK:
                for t in instance_types:
                    itype = t.instance_type
                    count = _extract_gpu_count(itype)
                    if count is None:
                        continue

                    if count == gpu_count and gpu_model.upper() in itype.upper():
                        spot_price = getattr(t, "spot_price_per_hour", None)
                        configs_to_check.append((gpu_model, gpu_count, itype, spot_price))
                        break

        # Check each GPU and stream results
        available = []
        results = {}  # key: (gpu_model, gpu_count) -> {"spot_locs": [], "ondemand_locs": [], ...}

        # Initialize results dict
        for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
            key = (gpu_model, gpu_count)
            results[key] = {
                "instance_type": instance_type,
                "spot_price": spot_price,
                "spot_locs": None,
                "ondemand_locs": None,
            }
            await websocket.send_json({
                "type": "checking",
                "gpu_model": gpu_model,
                "message": f"{gpu_model}を確認中..."
            })

        # Run checks in parallel and stream results as they complete
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {}
            for gpu_model, gpu_count, instance_type, spot_price in configs_to_check:
                key = (gpu_model, gpu_count)

                future_spot = executor.submit(_check_availability_for_config, client, instance_type, True)
                futures[future_spot] = (key, "spot", instance_type, spot_price)

                future_ondemand = executor.submit(_check_availability_for_config, client, instance_type, False)
                futures[future_ondemand] = (key, "ondemand", instance_type, spot_price)

            # Collect results and send as they complete
            for future in as_completed(futures, timeout=30):
                key, check_type, instance_type, spot_price = futures[future]
                gpu_model, gpu_count = key

                try:
                    locs = future.result()
                    if check_type == "spot":
                        results[key]["spot_locs"] = locs
                    else:
                        results[key]["ondemand_locs"] = locs

                    # If both checks are done for this GPU, send result
                    if results[key]["spot_locs"] is not None and results[key]["ondemand_locs"] is not None:
                        spot_available = len(results[key]["spot_locs"]) > 0
                        ondemand_available = len(results[key]["ondemand_locs"]) > 0

                        await websocket.send_json({
                            "type": "result",
                            "gpu_model": gpu_model,
                            "gpu_count": gpu_count,
                            "spot_available": spot_available,
                            "ondemand_available": ondemand_available,
                        })

                        available.append(GpuAvailabilityInfo(
                            gpu_model=gpu_model,
                            gpu_count=gpu_count,
                            instance_type=instance_type,
                            spot_available=spot_available,
                            ondemand_available=ondemand_available,
                            spot_locations=results[key]["spot_locs"],
                            ondemand_locations=results[key]["ondemand_locs"],
                            spot_price_per_hour=spot_price,
                        ))
                except Exception as e:
                    logger.warning(f"GPU availability check failed for {key}: {e}")

        # Update cache
        _gpu_availability_cache = {"available": available}
        _gpu_availability_cache_time = time.time()

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
            {"type": "error", "error": "Verda認証情報が設定されていません (DATACRUNCH_CLIENT_ID/SECRET)"}
        )
        await websocket.close()
        return

    try:
        volumes_by_id = _collect_verda_volumes(client)
    except Exception as e:
        logger.exception("Failed to list Verda volumes for WS action")
        await websocket.send_json({"type": "error", "error": f"Verda APIに接続できません: {e}"})
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
                {"id": volume_id, "reason": "対象が見つかりません（既に削除済みの可能性）"}
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

    def emit_progress(volume_id: str, status: str, reason: Optional[str] = None) -> None:
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
async def list_jobs(days: int = Query(7, ge=1, le=365)):
    """List training jobs.

    Args:
        days: Return jobs from past N days (running jobs always included)
    """
    jobs_data = _list_jobs(days)
    jobs = [JobInfo(**j) for j in jobs_data]
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str):
    """Get job details with remote status."""
    job_data = _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    job = JobInfo(**job_data)
    remote_status = None
    progress = None

    # Check remote status if job is running
    if job.status in ("running", "starting"):
        remote_status = _check_remote_status(job_data)
        progress = _get_remote_progress(job_data)

    return JobDetailResponse(job=job, remote_status=remote_status, progress=progress)


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(job_id: str, lines: int = Query(100, ge=1, le=10000)):
    """Get job logs from remote instance."""
    job_data = _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    logs = _get_remote_logs(job_data, lines)
    if logs is None:
        raise HTTPException(
            status_code=503, detail="Could not connect to remote instance"
        )

    return JobLogsResponse(job_id=job_id, logs=logs, lines=lines)


@router.get("/jobs/{job_id}/progress", response_model=JobProgressResponse)
async def get_job_progress(job_id: str):
    """Get training progress for a job."""
    job_data = _load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    progress = _get_remote_progress(job_data)
    if progress is None:
        return JobProgressResponse(job_id=job_id)

    return JobProgressResponse(job_id=job_id, **progress)


@router.get("/jobs/{job_id}/instance-status", response_model=InstanceStatusResponse)
async def get_instance_status(job_id: str):
    """Get detailed instance status from Verda API.

    This endpoint checks the actual cloud instance status and optionally
    the remote training process status via SSH.
    """
    job_data = _load_job(job_id)
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


@router.post("/jobs/{job_id}/stop", response_model=JobActionResponse)
async def stop_job(job_id: str):
    """Stop a running training job."""
    job_data = _load_job(job_id)
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
        _save_job(job_data)

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
        logger.warning(f"Cannot delete instance {instance_id}: Verda client not available")
        return False

    try:
        # Check if instance exists first
        instance = client.instances.get_by_id(instance_id)
        current_status = instance.status
        logger.info(f"Instance {instance_id} current status: {current_status}")

        if current_status in ("offline", "deleted", "deleting"):
            logger.info(f"Instance {instance_id} already terminated or deleting (status: {current_status})")
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
                logger.info(f"Instance {instance_id} status after delete request: {new_status}")

                if new_status in ("deleted", "deleting", "offline"):
                    logger.info(f"Instance {instance_id} deletion confirmed (status: {new_status})")
                    return True
            except Exception as check_error:
                # Instance not found - likely deleted
                logger.info(f"Instance {instance_id} no longer found (likely deleted): {check_error}")
                return True

        # Timeout - deletion may still be in progress
        logger.warning(f"Instance {instance_id} deletion not confirmed within {wait_timeout}s, but request was sent")
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
    job_data = _load_job(job_id)
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
        _save_job(job_data)
        instance_deleted = _delete_verda_instance(instance_id)
        job_data["cleanup_status"] = "done" if instance_deleted else "failed"
    _save_job(job_data)

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
    jobs_data = _list_jobs()
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
            _save_job(job_data)
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
            _save_job(job_data)
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
            _mark_job_completed(job_id, termination_reason="REMOTE_EXIT")
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

    Can be called with either:
    - config_id: Load settings from saved config file
    - Direct fields: Provide name, dataset, policy, etc. directly
    """
    # If config_id is provided, load config and populate request fields
    if request.config_id:
        config_data = _load_config(request.config_id)
        if not config_data:
            raise HTTPException(
                status_code=404,
                detail=f"Config not found: {request.config_id}",
            )

        # Import models for building request from config
        from interfaces_backend.models.training import (
            DatasetConfig,
            PolicyConfig,
            TrainingParams,
            CloudConfig,
        )

        # Build request from config data
        dataset_cfg = config_data.get("dataset", {})
        policy_cfg = config_data.get("policy", {})
        training_cfg = config_data.get("training", {})
        verda_cfg = config_data.get("verda", {})
        output_cfg = config_data.get("output", {})
        wandb_cfg = config_data.get("wandb", {})

        # Use config_id as job name if not provided
        job_id = request.name or request.config_id

        # Build dataset config
        request.dataset = DatasetConfig(
            id=dataset_cfg.get("id", ""),
            source=dataset_cfg.get("source", "r2"),
            hf_repo_id=dataset_cfg.get("hf_repo_id"),
        )

        # Build policy config
        request.policy = PolicyConfig(
            type=policy_cfg.get("type", "act"),
            pretrained_path=policy_cfg.get("pretrained_path"),
            compile_model=policy_cfg.get("compile_model"),
            gradient_checkpointing=policy_cfg.get("gradient_checkpointing"),
            dtype=policy_cfg.get("dtype"),
        )

        # Build training params
        request.training = TrainingParams(
            steps=training_cfg.get("steps"),
            batch_size=training_cfg.get("batch_size"),
            save_freq=training_cfg.get("save_freq"),
        )

        # Build cloud config
        request.cloud = CloudConfig(
            gpu_model=verda_cfg.get("gpu_model", "H100"),
            gpus_per_instance=verda_cfg.get("gpus_per_instance", 1),
            storage_size=verda_cfg.get("storage_size"),
            location=verda_cfg.get("location", "auto"),
            is_spot=verda_cfg.get("is_spot", True),
        )

        # Other settings
        request.checkpoint_repo_id = output_cfg.get("checkpoint_repo_id")
        request.wandb_enable = wandb_cfg.get("enable", True)
    else:
        # Validate required fields when not using config_id
        if not request.name:
            raise HTTPException(
                status_code=422,
                detail="Either config_id or name must be provided",
            )
        if not request.dataset:
            raise HTTPException(
                status_code=422,
                detail="Either config_id or dataset must be provided",
            )
        if not request.policy:
            raise HTTPException(
                status_code=422,
                detail="Either config_id or policy must be provided",
            )
        job_id = request.name

    # Check if Verda credentials are available
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Verda/DataCrunch credentials not configured. "
            "Set DATACRUNCH_CLIENT_ID and DATACRUNCH_CLIENT_SECRET.",
        )

    now = datetime.now().isoformat()

    # Check for duplicate job_id
    if _load_job(job_id):
        raise HTTPException(
            status_code=409,
            detail=f"Job with ID '{job_id}' already exists",
        )

    try:
        # Select instance type
        instance_type = _select_instance_type(
            client,
            request.cloud.gpu_model,
            request.cloud.gpus_per_instance,
        )

        # Get SSH key
        ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
        ssh_private_key = os.environ.get("VERDA_SSH_PRIVATE_KEY", "~/.ssh/id_rsa")

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
            hostname=f"train-{job_id[:16].replace('_', '-')}",
        )

        # Save job info (status: starting)
        job_data = {
            "job_id": job_id,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "config_name": job_id,
            "mode": "train",
            "project_id": _resolve_project_id(request.dataset.id if request.dataset else None),
            "ssh_user": "root",
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root",
            "checkpoint_repo_id": request.checkpoint_repo_id,
            "created_at": now,
            "updated_at": now,
            "gpu_model": request.cloud.gpu_model,
            "gpus_per_instance": request.cloud.gpus_per_instance,
            "policy_type": request.policy.type if request.policy else None,
            "dataset_id": request.dataset.id if request.dataset else None,
            "training_config": {
                "dataset": request.dataset.model_dump() if request.dataset else {},
                "policy": request.policy.model_dump() if request.policy else {},
                "training": request.training.model_dump(),
                "wandb_enable": request.wandb_enable,
                "checkpoint_repo_id": request.checkpoint_repo_id,
            },
            "compute_profile": request.cloud.model_dump(),
        }
        _save_job(job_data)

        # Start background task to wait for IP and deploy training
        background_tasks.add_task(
            _deploy_and_start_training,
            job_id=job_id,
            request=request,
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
    )

    emit_progress({"type": "start", "message": "ジョブ作成を開始..."})

    # Parse request data
    try:
        emit_progress({"type": "validating", "message": "設定を検証中..."})

        name = request_data.get("name")
        if not name:
            emit_progress({"type": "error", "error": "ジョブ名が指定されていません"})
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
        )
        policy = PolicyConfig(
            type=policy_data.get("type", "act"),
            pretrained_path=policy_data.get("pretrained_path"),
        )
        training = TrainingParams(
            steps=training_data.get("steps"),
            batch_size=training_data.get("batch_size"),
            save_freq=training_data.get("save_freq"),
        )
        cloud = CloudConfig(
            gpu_model=cloud_data.get("gpu_model", "H100"),
            gpus_per_instance=cloud_data.get("gpus_per_instance", 1),
            storage_size=cloud_data.get("storage_size"),
            location=cloud_data.get("location", "auto"),
            is_spot=cloud_data.get("is_spot", True),
        )

        job_id = name

        # Check for duplicate
        if _load_job(job_id):
            emit_progress({"type": "error", "error": f"ジョブ '{job_id}' は既に存在します"})
            return {"success": False, "error": f"ジョブ '{job_id}' は既に存在します"}

        emit_progress({"type": "validated", "message": "設定OK"})

    except Exception as e:
        emit_progress({"type": "error", "error": f"設定検証エラー: {e}"})
        return {"success": False, "error": str(e)}

    # Get Verda client
    client = _get_verda_client()
    if not client:
        emit_progress({"type": "error", "error": "Verda認証情報が設定されていません"})
        return {"success": False, "error": "Verda認証情報が設定されていません"}

    # Track instance_id for cleanup on failure
    instance_id: Optional[str] = None

    def cleanup_instance_on_failure(error_msg: str) -> dict:
        """Clean up instance if creation succeeded but subsequent steps failed."""
        nonlocal instance_id
        if instance_id:
            emit_progress({"type": "cleanup", "message": f"エラー発生のためインスタンスを削除中: {instance_id}"})
            logger.warning(f"Cleaning up instance {instance_id} due to failure: {error_msg}")
            _update_cleanup_status(job_id, "running")
            cleanup_ok = _delete_verda_instance(instance_id)
            _update_cleanup_status(job_id, "done" if cleanup_ok else "failed")
        return {"success": False, "error": error_msg}

    try:
        # Select instance type
        emit_progress({"type": "selecting_instance", "message": "インスタンスタイプを選択中..."})
        instance_type = _select_instance_type(client, cloud.gpu_model, cloud.gpus_per_instance)
        emit_progress({
            "type": "instance_selected",
            "message": f"インスタンスタイプ: {instance_type}",
            "instance_type": instance_type,
        })

        # Get SSH key
        emit_progress({"type": "getting_ssh_key", "message": "SSHキーを取得中..."})
        ssh_key_name = os.environ.get("VERDA_SSH_KEY_NAME", "")
        ssh_private_key = os.environ.get("VERDA_SSH_PRIVATE_KEY", "~/.ssh/id_rsa")
        if not ssh_key_name:
            emit_progress({"type": "error", "error": "VERDA_SSH_KEY_NAMEが設定されていません"})
            return {"success": False, "error": "VERDA_SSH_KEY_NAMEが設定されていません"}
        ssh_key_id = _get_ssh_key_id(client, ssh_key_name)

        # Find location
        emit_progress({"type": "finding_location", "message": "利用可能なロケーションを検索中..."})
        location = _find_location(client, instance_type, cloud.location, cloud.is_spot)
        emit_progress({
            "type": "location_found",
            "message": f"ロケーション: {location}",
            "location": location,
        })

        # Create instance
        emit_progress({"type": "creating_instance", "message": "インスタンスを作成中..."})
        instance_id = _create_instance(
            client,
            instance_type=instance_type,
            ssh_key_id=ssh_key_id,
            location=location,
            is_spot=cloud.is_spot,
            storage_size=cloud.storage_size,
            hostname=f"train-{job_id[:16].replace('_', '-')}",
        )
        emit_progress({
            "type": "instance_created",
            "message": f"インスタンス作成完了: {instance_id}",
            "instance_id": instance_id,
        })

        # Save job info
        now = datetime.now().isoformat()
        job_data = {
            "job_id": job_id,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "config_name": job_id,
            "mode": "train",
            "project_id": _resolve_project_id(dataset.id),
            "ssh_user": "root",
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root",
            "checkpoint_repo_id": checkpoint_repo_id,
            "created_at": now,
            "updated_at": now,
            "gpu_model": cloud.gpu_model,
            "gpus_per_instance": cloud.gpus_per_instance,
            "policy_type": policy.type,
            "dataset_id": dataset.id,
            "training_config": {
                "dataset": dataset.model_dump(),
                "policy": policy.model_dump(),
                "training": training.model_dump(),
                "wandb_enable": wandb_enable,
                "checkpoint_repo_id": checkpoint_repo_id,
            },
            "compute_profile": cloud.model_dump(),
        }
        _save_job(job_data)

        # Wait for IP (up to 15 minutes)
        emit_progress({"type": "waiting_ip", "message": "IPアドレス割り当て待機中...", "elapsed": 0, "timeout": 900})
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
            emit_progress({
                "type": "waiting_ip",
                "message": f"IPアドレス割り当て待機中... ({elapsed}秒経過)",
                "elapsed": elapsed,
                "timeout": 900,
            })
            time.sleep(15)

        if not ip:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "IP_TIMEOUT"
            job_data["error_message"] = "IP取得タイムアウト"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            emit_progress({"type": "error", "error": "IP取得タイムアウト (15分)"})
            return cleanup_instance_on_failure("IP取得タイムアウト (15分)")

        emit_progress({"type": "ip_assigned", "message": f"IP取得完了: {ip}", "ip": ip})

        # Update job with IP
        job_data["ip"] = ip
        job_data["status"] = "deploying"
        _save_job(job_data)

        # SSH deployment using SSHConnection and RemoteExecutor
        ssh_user = "root"
        remote_base_dir = "/root"
        remote_run_dir = f"{remote_base_dir}/lerobot_run"

        # Wait for SSH (up to 5 minutes)
        emit_progress({"type": "connecting_ssh", "message": "SSH接続中...", "attempt": 0, "max_attempts": 30})
        conn: Optional[SSHConnection] = None
        start_time = time.time()
        ssh_deadline = start_time + SSH_WAIT_TIMEOUT_SEC
        attempt = 0
        while time.time() < ssh_deadline:
            attempt += 1
            try:
                conn = _create_ssh_connection(ip, ssh_user, ssh_private_key)
                break
            except Exception:
                elapsed = int(time.time() - start_time)
                emit_progress({
                    "type": "connecting_ssh",
                    "message": f"SSH接続中... (試行 {attempt}/30, {elapsed}秒経過)",
                    "attempt": attempt,
                    "max_attempts": 30,
                    "elapsed": elapsed,
                })
                time.sleep(10)

        if not conn:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "SSH_TIMEOUT"
            job_data["error_message"] = "SSH接続タイムアウト"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            emit_progress({"type": "error", "error": "SSH接続タイムアウト (5分)"})
            return cleanup_instance_on_failure("SSH接続タイムアウト (5分)")

        emit_progress({"type": "ssh_ready", "message": "SSH接続完了"})

        try:
            # Create remote directory
            emit_progress({"type": "deploying", "message": "リモートディレクトリを作成中..."})
            conn.mkdir_p(remote_run_dir)

            # Upload remote scripts
            emit_progress({"type": "deploying", "message": "スクリプトをアップロード中...", "file": "setup_env.sh"})
            setup_env_path = REMOTE_SCRIPTS_DIR / "setup_env.sh"
            read_config_path = REMOTE_SCRIPTS_DIR / "read_train_config.py"
            entry_path = REMOTE_SCRIPTS_DIR / "entry.py"

            if setup_env_path.exists():
                conn.upload_file(setup_env_path, f"{remote_run_dir}/setup_env.sh")
            emit_progress({"type": "deploying", "message": "スクリプトをアップロード中...", "file": "read_train_config.py"})
            if read_config_path.exists():
                conn.upload_file(read_config_path, f"{remote_run_dir}/read_train_config.py")
            emit_progress({"type": "deploying", "message": "スクリプトをアップロード中...", "file": "entry.py"})
            if entry_path.exists():
                conn.upload_file(entry_path, f"{remote_run_dir}/entry.py")

            # Generate and upload training config YAML
            emit_progress({"type": "deploying", "message": "学習設定をアップロード中...", "file": "train.remote.yaml"})

            # Build request object for config generation
            from interfaces_backend.models.training import JobCreateRequest
            request = JobCreateRequest(
                name=name,
                dataset=dataset,
                policy=policy,
                training=training,
                cloud=cloud,
                checkpoint_repo_id=checkpoint_repo_id,
                wandb_enable=wandb_enable,
            )
            config_yaml = _generate_training_config_yaml(request, job_id)
            conn.upload_content(config_yaml, f"{remote_run_dir}/train.remote.yaml")

            # Generate and upload .env file
            emit_progress({"type": "deploying", "message": "環境変数をアップロード中...", "file": ".env"})
            env_content = _generate_env_file(job_id, instance_id)
            conn.upload_content(env_content, f"{remote_run_dir}/.env")

            # Generate and upload instance_info.env
            emit_progress({"type": "deploying", "message": "インスタンス情報をアップロード中...", "file": "instance_info.env"})
            instance_info = _generate_instance_info_env(job_id, instance_id, auto_delete=True)
            conn.upload_content(instance_info, f"{remote_run_dir}/instance_info.env")

            # Make setup script executable
            conn.exec_command(f"chmod +x {remote_run_dir}/setup_env.sh")

            # Start training using RemoteExecutor with tmux
            emit_progress({"type": "starting_training", "message": "学習を開始中..."})
            executor = RemoteExecutor(conn, remote_base_dir=remote_run_dir)
            success = executor.run_background(
                "bash setup_env.sh train",
                session_name=TMUX_SESSION_NAME,
            )
            if not success:
                emit_progress({"type": "training_log", "message": "警告: tmuxセッションの開始を確認できませんでした"})

            # Stream log file in real-time using tail -f
            log_file = _get_log_file_path(job_data)
            max_stream_time = LOG_STREAM_MAX_SEC
            lines_to_show = LOG_STREAM_INITIAL_LINES
            lines_received = 0
            start_time = time.time()
            log_file_found = False

            try:
                # Wait for log file to exist (max 5 seconds)
                emit_progress({"type": "training_log", "message": "ログファイル待機中..."})
                for i in range(10):
                    exit_code, stdout, stderr = conn.exec_command(
                        f"test -f {log_file} && echo 'exists' || echo 'not_exists'",
                        timeout=2
                    )
                    if "exists" in stdout:
                        log_file_found = True
                        emit_progress({"type": "training_log", "message": "ログストリーミング開始..."})
                        break
                    time.sleep(0.5)

                if not log_file_found:
                    emit_progress({"type": "training_log", "message": "ログファイル作成待ち (バックグラウンドで起動中)..."})

                # Use tail -f to stream logs in real-time
                transport = conn.client.get_transport()
                channel = transport.open_session()
                # Use tail -F (capital F) to handle file that doesn't exist yet
                channel.exec_command(f"tail -F {log_file} 2>/dev/null")
                channel.setblocking(0)  # Non-blocking mode

                buffer = ""
                while time.time() - start_time < max_stream_time:
                    # Check if data is available
                    if channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        buffer += chunk

                        # Process complete lines
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if line.strip():
                                emit_progress({
                                    "type": "training_log",
                                    "message": line.strip(),
                                })
                                lines_received += 1

                        # Exit once we have enough lines
                        if lines_received >= lines_to_show:
                            break
                    else:
                        time.sleep(0.1)

                channel.close()

            except Exception as e:
                logger.warning(f"Log streaming error (non-fatal): {e}")
                emit_progress({"type": "training_log", "message": f"ログ取得エラー: {e}"})

            emit_progress({
                "type": "complete",
                "message": "学習プロセスを起動しました。リモート側の開始確認待ちです。",
                "job_id": job_id,
                "instance_id": instance_id,
                "ip": ip,
                "status": "deploying",
            })

            return {
                "success": True,
                "job_id": job_id,
                "instance_id": instance_id,
                "ip": ip,
                "status": "deploying",
            }

        finally:
            conn.disconnect()

    except HTTPException as e:
        if instance_id:
            job_data = _load_job(job_id, include_deleted=True)
            if job_data:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "VERDA_ERROR"
                job_data["error_message"] = e.detail
                job_data["completed_at"] = datetime.now().isoformat()
                _save_job(job_data)
        emit_progress({"type": "error", "error": e.detail})
        return cleanup_instance_on_failure(e.detail)
    except Exception as e:
        if instance_id:
            job_data = _load_job(job_id, include_deleted=True)
            if job_data:
                job_data["status"] = "failed"
                job_data["failure_reason"] = "UNKNOWN"
                job_data["error_message"] = str(e)
                job_data["completed_at"] = datetime.now().isoformat()
                _save_job(job_data)
        emit_progress({"type": "error", "error": str(e)})
        return cleanup_instance_on_failure(str(e))


@router.websocket("/ws/create-job")
async def websocket_create_job(websocket: WebSocket):
    """WebSocket endpoint for creating training jobs with real-time progress.

    Client sends JSON request (same format as POST /api/training/jobs but dict):
    {
        "name": "job_name",
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
    - {"type": "connecting_ssh", "message": "...", "attempt": N, "max_attempts": 30}
    - {"type": "ssh_ready", "message": "..."}
    - {"type": "deploying", "message": "...", "file": "..."}
    - {"type": "starting_training", "message": "..."}
    - {"type": "complete", "job_id": "...", "instance_id": "...", "ip": "...", "status": "running"}
    - {"type": "error", "error": "..."}
    - {"type": "heartbeat"} (sent periodically to keep connection alive)
    """
    await websocket.accept()
    logger.info("WebSocket create-job client connected")

    try:
        # Wait for job creation request
        data = await websocket.receive_json()

        # Queue for progress updates from thread
        progress_queue: asyncio.Queue = asyncio.Queue()

        # Capture event loop for use in thread callback
        main_loop = asyncio.get_running_loop()

        def emit_progress(progress: dict):
            """Callback to put progress in queue (called from thread)."""
            asyncio.run_coroutine_threadsafe(
                progress_queue.put(progress),
                main_loop
            )

        # Run job creation in thread pool
        async def run_job_creation():
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                _executor,
                lambda: _create_job_with_progress(data, emit_progress)
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


async def _deploy_and_start_training(job_id: str, request: JobCreateRequest) -> None:
    """Background task to deploy and start training.

    This waits for the instance IP, uploads files, and starts training.
    Uses SSHConnection and RemoteExecutor for consistency with other code paths.
    """
    job_data = _load_job(job_id)
    if not job_data:
        return

    client = _get_verda_client()
    if not client:
        job_data["status"] = "failed"
        job_data["failure_reason"] = "VERDA_ERROR"
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)
        return

    instance_id = job_data["instance_id"]

    def cleanup_on_failure(error_msg: str) -> None:
        """Clean up instance on deployment failure."""
        logger.warning(f"Cleaning up instance {instance_id} due to failure: {error_msg}")
        _update_cleanup_status(job_id, "running")
        cleanup_ok = _delete_verda_instance(instance_id)
        _update_cleanup_status(job_id, "done" if cleanup_ok else "failed")

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
            time.sleep(15)

        if not ip:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "IP_TIMEOUT"
            job_data["error_message"] = "IP取得タイムアウト"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            cleanup_on_failure("IP取得タイムアウト")
            return

        # Update job with IP
        job_data["ip"] = ip
        job_data["status"] = "deploying"
        _save_job(job_data)

        # SSH deployment using SSHConnection
        ssh_user = job_data.get("ssh_user", "root")
        ssh_private_key = job_data.get("ssh_private_key", "~/.ssh/id_rsa")
        remote_base_dir = job_data.get("remote_base_dir", "/root")
        remote_run_dir = f"{remote_base_dir}/lerobot_run"

        # Wait for SSH to be ready (up to 5 minutes)
        conn: Optional[SSHConnection] = None
        ssh_deadline = time.time() + SSH_WAIT_TIMEOUT_SEC
        while time.time() < ssh_deadline:
            try:
                conn = _create_ssh_connection(ip, ssh_user, ssh_private_key)
                break
            except Exception:
                time.sleep(10)

        if not conn:
            job_data["status"] = "failed"
            job_data["failure_reason"] = "SSH_TIMEOUT"
            job_data["error_message"] = "SSH接続タイムアウト"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            cleanup_on_failure("SSH接続タイムアウト")
            return

        try:
            # Create remote directory
            conn.mkdir_p(remote_run_dir)

            # Upload remote scripts
            setup_env_path = REMOTE_SCRIPTS_DIR / "setup_env.sh"
            read_config_path = REMOTE_SCRIPTS_DIR / "read_train_config.py"
            entry_path = REMOTE_SCRIPTS_DIR / "entry.py"

            if setup_env_path.exists():
                conn.upload_file(setup_env_path, f"{remote_run_dir}/setup_env.sh")
            if read_config_path.exists():
                conn.upload_file(read_config_path, f"{remote_run_dir}/read_train_config.py")
            if entry_path.exists():
                conn.upload_file(entry_path, f"{remote_run_dir}/entry.py")

            # Generate and upload training config YAML
            config_yaml = _generate_training_config_yaml(request, job_id)
            conn.upload_content(config_yaml, f"{remote_run_dir}/train.remote.yaml")

            # Generate and upload .env file
            instance_id = job_data["instance_id"]
            env_content = _generate_env_file(job_id, instance_id)
            conn.upload_content(env_content, f"{remote_run_dir}/.env")

            # Generate and upload instance_info.env
            instance_info = _generate_instance_info_env(job_id, instance_id, auto_delete=True)
            conn.upload_content(instance_info, f"{remote_run_dir}/instance_info.env")

            # Make setup script executable
            conn.exec_command(f"chmod +x {remote_run_dir}/setup_env.sh")

            # Start training using RemoteExecutor with tmux
            executor = RemoteExecutor(conn, remote_base_dir=remote_run_dir)
            executor.run_background("bash setup_env.sh train", session_name=TMUX_SESSION_NAME)

        finally:
            conn.disconnect()

    except Exception as e:
        job_data["status"] = "failed"
        job_data["failure_reason"] = "UNKNOWN"
        job_data["error_message"] = str(e)
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)
        cleanup_on_failure(str(e))


# --- Checkpoint API ---

_checkpoint_index_manager = None


def _get_checkpoint_index_manager():
    """Get CheckpointIndexManager singleton."""
    global _checkpoint_index_manager
    if _checkpoint_index_manager is None:
        try:
            import os

            from percus_ai.storage import CheckpointIndexManager, ManifestManager, R2SyncService

            manifest = ManifestManager()
            manifest.init_directories()
            bucket = os.getenv("R2_BUCKET", "percus-data")
            version = os.getenv("R2_VERSION", "v2")
            r2_service = R2SyncService(manifest, bucket, version=version)
            _checkpoint_index_manager = CheckpointIndexManager(r2_service)
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to initialize checkpoint manager: {e}"
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
    policy_type: Optional[str] = Query(None, description="Filter by policy type")
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
                camera_names=entry.dataset_info.camera_names if entry.dataset_info else [],
                action_dim=entry.dataset_info.action_dim if entry.dataset_info else 0,
                state_dim=entry.dataset_info.state_dim if entry.dataset_info else 0,
            )

            checkpoints.append(CheckpointInfo(
                job_name=entry.job_name,
                policy_type=entry.policy_type,
                step=entry.latest_step,
                dataset_id=entry.dataset_id,
                dataset_info=ds_info,
                created_at=entry.created_at,
                size_mb=entry.size_mb,
                pretrained_path=entry.pretrained_path,
                author=entry.author if hasattr(entry, 'author') else None,
            ))

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
            status_code=503,
            detail=f"Failed to list checkpoints from R2: {e}"
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
                status_code=404,
                detail=f"Checkpoint not found: {job_name}"
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
            author=entry.author if hasattr(entry, 'author') else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to get checkpoint info: {e}"
        )


@router.post("/checkpoints/{job_name}/download", response_model=CheckpointDownloadResponse)
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
                status_code=404,
                detail=f"Checkpoint not found: {job_name}"
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
                    detail=f"Step {step} not found. Available steps: {available_steps}"
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
            raise HTTPException(
                status_code=500,
                detail=f"Download failed: {error}"
            )

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
            status_code=503,
            detail=f"Failed to download checkpoint: {e}"
        )


@router.post("/checkpoints/compatibility-check", response_model=DatasetCompatibilityCheckResponse)
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
                detail=f"Checkpoint not found: {request.checkpoint_job_name}"
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
            if checkpoint_ds_info.action_dim != dataset_info.action_dim and checkpoint_ds_info.action_dim > 0:
                errors.append(
                    f"Action dimension mismatch. "
                    f"Checkpoint: {checkpoint_ds_info.action_dim}, "
                    f"Dataset: {dataset_info.action_dim}"
                )

            # State dimension check (warning only)
            if checkpoint_ds_info.state_dim != dataset_info.state_dim and checkpoint_ds_info.state_dim > 0:
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
        raise HTTPException(
            status_code=500,
            detail=f"Compatibility check failed: {e}"
        )


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
                detail=f"Checkpoint not found: {checkpoint_config.job_name}"
            )

        # Determine step to use
        step = checkpoint_config.step or checkpoint_entry.latest_step

        # Verify step exists
        available_steps = checkpoint_mgr.get_job_steps(checkpoint_config.job_name)
        if step not in available_steps:
            raise HTTPException(
                status_code=400,
                detail=f"Step {step} not available. Available: {available_steps}"
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
                    detail=f"Dataset incompatible: {'; '.join(compat_result.errors)}"
                )

        # 3. Generate job name
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        author = request.author or os.environ.get("LEROBOT_AUTHOR", "user")
        job_id = f"{checkpoint_config.job_name}_continue_{author}_{date_str}"

        # Check for duplicates
        if _load_job(job_id):
            job_id = f"{job_id}_{datetime.now().strftime('%H%M%S')}"

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
        ssh_private_key = os.environ.get("VERDA_SSH_PRIVATE_KEY", "~/.ssh/id_rsa")

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
            hostname=f"train-{job_id[:16].replace('_', '-')}",
        )

        # Save job info (status: starting)
        job_data = {
            "job_id": job_id,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "config_name": job_id,
            "mode": "resume_local",
            "project_id": _resolve_project_id(dataset_id),
            "continue_from": {
                "job_name": checkpoint_config.job_name,
                "step": step,
            },
            "dataset_id": dataset_id,
            "policy_type": checkpoint_entry.policy_type,
            "ssh_user": "root",
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root",
            "created_at": now,
            "updated_at": now,
            "gpu_model": request.cloud.gpu_model,
            "gpus_per_instance": request.cloud.gpus_per_instance,
            "total_steps": total_steps,
            "additional_steps": training_config.additional_steps,
            "author": author,
            "training_config": {
                "dataset": request.dataset.model_dump(),
                "training": training_config.model_dump(),
                "checkpoint": {
                    "job_name": checkpoint_config.job_name,
                    "step": step,
                },
            },
            "compute_profile": request.cloud.model_dump(),
        }
        _save_job(job_data)

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
            status_code=500,
            detail=f"Failed to create continue job: {e}"
        )


# --- Training Configs API ---

# Configs directory
CONFIGS_DIR = get_configs_dir()


def _get_config_file(config_id: str) -> Path:
    """Get config file path."""
    return CONFIGS_DIR / f"{config_id}.yaml"


def _list_configs() -> list[dict]:
    """List all training configs."""
    if not CONFIGS_DIR.exists():
        return []

    configs = []
    for config_file in CONFIGS_DIR.glob("*.yaml"):
        try:
            with open(config_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                continue

            configs.append({
                "config_id": config_file.stem,
                "name": data.get("metadata", {}).get("name", config_file.stem),
                "policy_type": data.get("policy", {}).get("type", "unknown"),
                "dataset_id": data.get("dataset", {}).get("id", "unknown"),
                "gpu_model": data.get("verda", {}).get("gpu_model", "H100"),
                "file_path": str(config_file),
                "modified_at": datetime.fromtimestamp(
                    config_file.stat().st_mtime
                ).isoformat(),
            })
        except Exception:
            continue

    configs.sort(key=lambda c: c.get("modified_at", ""), reverse=True)
    return configs


def _load_config(config_id: str) -> Optional[dict]:
    """Load config from file."""
    config_file = _get_config_file(config_id)
    if not config_file.exists():
        return None

    with open(config_file, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config(config_id: str, config_data: dict) -> Path:
    """Save config to file."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    config_file = _get_config_file(config_id)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    return config_file


def _convert_model_to_yaml_format(config) -> dict:
    """Convert Pydantic model to YAML format."""
    return {
        "metadata": {
            "name": config.name,
        },
        "dataset": {
            "id": config.dataset.id,
            "source": config.dataset.source,
            "hf_repo_id": config.dataset.hf_repo_id,
        },
        "policy": {
            "type": config.policy.type,
            "pretrained_path": config.policy.pretrained_path,
            "compile_model": config.policy.compile_model,
            "gradient_checkpointing": config.policy.gradient_checkpointing,
            "dtype": config.policy.dtype,
        },
        "training": {
            "steps": config.training.steps,
            "batch_size": config.training.batch_size,
            "save_freq": config.training.save_freq,
        },
        "output": {
            "output_dir": config.output.output_dir,
            "checkpoint_repo_id": config.output.checkpoint_repo_id,
            "upload_every_save": config.output.upload_every_save,
        },
        "wandb": {
            "enable": config.wandb.enable,
        },
        "verda": {
            "gpu_model": config.cloud.gpu_model,
            "gpus_per_instance": config.cloud.gpus_per_instance,
            "storage_size": config.cloud.storage_size,
            "location": config.cloud.location,
            "is_spot": config.cloud.is_spot,
        },
    }


def _convert_yaml_to_model_format(data: dict) -> dict:
    """Convert YAML format to Pydantic model format."""
    metadata = data.get("metadata", {})
    dataset = data.get("dataset", {})
    policy = data.get("policy", {})
    training = data.get("training", {})
    output = data.get("output", {})
    wandb = data.get("wandb", {})
    verda = data.get("verda", {})

    return {
        "name": metadata.get("name", ""),
        "dataset": {
            "id": dataset.get("id", ""),
            "source": dataset.get("source", "r2"),
            "hf_repo_id": dataset.get("hf_repo_id"),
        },
        "policy": {
            "type": policy.get("type", "act"),
            "pretrained_path": policy.get("pretrained_path"),
            "compile_model": policy.get("compile_model"),
            "gradient_checkpointing": policy.get("gradient_checkpointing"),
            "dtype": policy.get("dtype"),
        },
        "training": {
            "steps": training.get("steps"),
            "batch_size": training.get("batch_size"),
            "save_freq": training.get("save_freq"),
        },
        "output": {
            "output_dir": output.get("output_dir"),
            "checkpoint_repo_id": output.get("checkpoint_repo_id"),
            "upload_every_save": output.get("upload_every_save", False),
        },
        "wandb": {
            "enable": wandb.get("enable", True),
        },
        "cloud": {
            "gpu_model": verda.get("gpu_model", "H100"),
            "gpus_per_instance": verda.get("gpus_per_instance", 1),
            "storage_size": verda.get("storage_size"),
            "location": verda.get("location", "auto"),
            "is_spot": verda.get("is_spot", True),
        },
    }


# Import training config models
from interfaces_backend.models.training_config import (
    TrainingConfigInfo,
    TrainingConfigListResponse,
    TrainingConfigDetailResponse,
    TrainingConfigCreateRequest,
    TrainingConfigCreateResponse,
    TrainingConfigModel,
    TrainingConfigValidationResult,
    TrainingConfigDryRunResult,
    # R2 sync models
    ConfigSyncStatusResponse,
    ConfigSyncResponse,
    RemoteConfigListResponse,
)
from percus_ai.storage import ManifestManager, R2SyncService


@router.get("/configs", response_model=TrainingConfigListResponse)
async def list_training_configs():
    """List all training configuration files."""
    configs_data = _list_configs()
    configs = [TrainingConfigInfo(**c) for c in configs_data]
    return TrainingConfigListResponse(configs=configs, total=len(configs))


@router.get("/configs/{config_id}", response_model=TrainingConfigDetailResponse)
async def get_training_config(config_id: str):
    """Get training configuration details."""
    data = _load_config(config_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Config not found: {config_id}")

    model_data = _convert_yaml_to_model_format(data)
    config = TrainingConfigModel(**model_data)

    return TrainingConfigDetailResponse(
        config_id=config_id,
        config=config,
        file_path=str(_get_config_file(config_id)),
    )


@router.post("/configs", response_model=TrainingConfigCreateResponse)
async def create_training_config(request: TrainingConfigCreateRequest):
    """Create a new training configuration."""
    config_id = request.config.name.replace(" ", "_").lower()

    # Check for duplicate
    if _get_config_file(config_id).exists():
        raise HTTPException(
            status_code=409,
            detail=f"Config '{config_id}' already exists",
        )

    yaml_data = _convert_model_to_yaml_format(request.config)
    file_path = _save_config(config_id, yaml_data)

    return TrainingConfigCreateResponse(
        config_id=config_id,
        file_path=str(file_path),
        message="Training config created",
    )


@router.put("/configs/{config_id}", response_model=TrainingConfigCreateResponse)
async def update_training_config(config_id: str, request: TrainingConfigCreateRequest):
    """Update an existing training configuration."""
    if not _get_config_file(config_id).exists():
        raise HTTPException(status_code=404, detail=f"Config not found: {config_id}")

    yaml_data = _convert_model_to_yaml_format(request.config)
    file_path = _save_config(config_id, yaml_data)

    return TrainingConfigCreateResponse(
        config_id=config_id,
        file_path=str(file_path),
        message="Training config updated",
    )


@router.delete("/configs/{config_id}")
async def delete_training_config(config_id: str):
    """Delete a training configuration."""
    config_file = _get_config_file(config_id)
    if not config_file.exists():
        raise HTTPException(status_code=404, detail=f"Config not found: {config_id}")

    config_file.unlink()
    return {"config_id": config_id, "message": "Config deleted"}


@router.get("/configs/{config_id}/validate", response_model=TrainingConfigValidationResult)
async def validate_training_config(config_id: str):
    """Validate a training configuration."""
    data = _load_config(config_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Config not found: {config_id}")

    errors = []
    warnings = []

    # Check required fields
    dataset = data.get("dataset", {})
    if not dataset.get("id"):
        errors.append("dataset.id is required")

    policy = data.get("policy", {})
    if not policy.get("type"):
        errors.append("policy.type is required")

    # Check dataset source
    source = dataset.get("source", "r2")
    if source == "hub" and not dataset.get("hf_repo_id"):
        warnings.append("dataset.hf_repo_id recommended for hub source")

    # Check training params
    training = data.get("training", {})
    if not training.get("steps"):
        warnings.append("training.steps not set (will use default)")

    # Check Verda config
    verda = data.get("verda", {})
    if verda.get("is_spot", True):
        warnings.append("Using spot instance (may be preempted)")

    return TrainingConfigValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


@router.post("/configs/{config_id}/dry-run", response_model=TrainingConfigDryRunResult)
async def dry_run_training_config(config_id: str):
    """Simulate training launch without actually running."""
    data = _load_config(config_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Config not found: {config_id}")

    verda = data.get("verda", {})
    dataset = data.get("dataset", {})
    policy = data.get("policy", {})

    return TrainingConfigDryRunResult(
        config_id=config_id,
        would_create_instance={
            "gpu_model": verda.get("gpu_model", "H100"),
            "gpus_per_instance": verda.get("gpus_per_instance", 1),
            "location": verda.get("location", "auto"),
            "is_spot": verda.get("is_spot", True),
            "storage_size": verda.get("storage_size"),
        },
        estimated_cost_per_hour=None,  # Would need Verda API to get actual price
        files_to_deploy=[
            ".env",
            "train.remote.yaml",
            "setup_env.sh",
            "entry.py",
        ],
        remote_command=f"bash ./setup_env.sh train",
    )


# --- R2 Sync for Training Configs ---

_config_manifest_manager: Optional[ManifestManager] = None
_config_sync_service: Optional[R2SyncService] = None


def _get_config_manifest() -> ManifestManager:
    """Get manifest manager singleton."""
    global _config_manifest_manager
    if _config_manifest_manager is None:
        _config_manifest_manager = ManifestManager()
    return _config_manifest_manager


def _get_config_sync_service() -> R2SyncService:
    """Get R2 sync service singleton."""
    global _config_sync_service
    if _config_sync_service is None:
        bucket = os.environ.get("R2_BUCKET", "percus-data")
        version = os.environ.get("R2_VERSION", "v2")
        _config_sync_service = R2SyncService(_get_config_manifest(), bucket, version=version)
    return _config_sync_service


@router.get("/configs/{config_name}/sync", response_model=ConfigSyncStatusResponse)
async def get_config_sync_status(config_name: str):
    """Check sync status of a training config with R2."""
    try:
        sync_service = _get_config_sync_service()
        status = sync_service.check_config_sync(config_name)

        return ConfigSyncStatusResponse(
            config_name=config_name,
            status=status.status,
            local_hash=status.local_hash,
            remote_hash=status.remote_hash,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check sync status: {e}")


@router.post("/configs/{config_name}/upload", response_model=ConfigSyncResponse)
async def upload_config_to_r2(config_name: str, force: bool = Query(False)):
    """Upload a training config to R2.

    Args:
        config_name: Config name (filename without .yaml)
        force: Force upload even if remote is newer
    """
    # Check if local config exists
    config_file = _get_config_file(config_name)
    if not config_file.exists():
        raise HTTPException(status_code=404, detail=f"Config not found: {config_name}")

    try:
        sync_service = _get_config_sync_service()
        success, message = sync_service.upload_config(config_name, force=force)

        return ConfigSyncResponse(
            success=success,
            message=message,
            config_name=config_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload config: {e}")


@router.post("/configs/{config_name}/download", response_model=ConfigSyncResponse)
async def download_config_from_r2(config_name: str, force: bool = Query(False)):
    """Download a training config from R2.

    Args:
        config_name: Config name (filename without .yaml)
        force: Force download even if local is newer
    """
    try:
        sync_service = _get_config_sync_service()
        success, message = sync_service.download_config(config_name, force=force)

        return ConfigSyncResponse(
            success=success,
            message=message,
            config_name=config_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download config: {e}")


@router.get("/configs/remote", response_model=RemoteConfigListResponse)
async def list_remote_configs():
    """List all training configs available in R2."""
    try:
        sync_service = _get_config_sync_service()
        remote_configs = sync_service.list_remote_configs()

        # Extract config names from the response
        config_names = [c.get("name", "") for c in remote_configs if c.get("name")]

        return RemoteConfigListResponse(configs=config_names)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list remote configs: {e}")


@router.post("/configs/sync-from-r2")
async def sync_all_configs_from_r2():
    """Sync all training configs from R2.

    Downloads any configs that exist in R2 but not locally,
    and updates local manifest with remote metadata.
    """
    try:
        sync_service = _get_config_sync_service()
        downloaded, updated = sync_service.sync_configs_from_r2()

        return {
            "success": True,
            "downloaded": downloaded,
            "updated": updated,
            "message": f"Synced {downloaded} new configs, updated {updated} existing",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync configs: {e}")


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
    logger.info(f"WebSocket log stream client connected for job {job_id}")

    job_data = _load_job(job_id)
    if not job_data:
        await websocket.send_json({"type": "error", "error": f"Job not found: {job_id}"})
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
            await websocket.send_json({"type": "error", "error": f"Realtime購読に失敗しました: {e}"})
            await websocket.close()
            return

        # Connect SSH in thread pool
        loop = asyncio.get_event_loop()
        ssh_conn = await loop.run_in_executor(
            _executor,
            lambda: _get_ssh_connection_for_job(job_data, timeout=30)
        )

        if not ssh_conn:
            await websocket.send_json({"type": "error", "error": "SSH接続に失敗しました"})
            await websocket.close()
            return

        await websocket.send_json({"type": "connected", "message": "SSH接続完了"})

        # Determine log file path
        log_file = _get_log_file_path(job_data)

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
                    await websocket.send_json({
                        "type": "status",
                        "status": "stream_ended",
                        "message": "ログストリーム終了"
                    })
                    _mark_job_completed(job_id)
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
                await websocket.send_json({
                    "type": "status",
                    "status": status,
                    "message": f"ジョブ状態: {status}"
                })
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
    job_data = _load_job(job_id)
    if not job_data:
        await websocket.send_json({"type": "error", "error": f"Job not found: {job_id}"})
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
        await websocket.send_json({"type": "error", "error": f"Realtime購読に失敗しました: {e}"})
        await websocket.close()
        return

    # Send job info immediately (no SSH needed)
    await websocket.send_json({
        "type": "job_info",
        "data": {
            "job_id": job_data.get("job_id"),
            "status": job_data.get("status"),
            "config_name": job_data.get("config_name"),
            "mode": job_data.get("mode"),
            "gpu_model": job_data.get("gpu_model"),
            "gpus_per_instance": job_data.get("gpus_per_instance"),
            "ip": job_data.get("ip"),
            "instance_id": job_data.get("instance_id"),
            "created_at": job_data.get("created_at"),
            "failure_reason": job_data.get("failure_reason"),
            "termination_reason": job_data.get("termination_reason"),
            "cleanup_status": job_data.get("cleanup_status"),
            "deleted_at": job_data.get("deleted_at"),
        }
    })

    ssh_conn: Optional[SSHConnection] = None
    log_channel = None
    is_streaming_logs = False

    try:
        # Check if job has IP (needed for SSH)
        ip = job_data.get("ip")
        if not ip:
            await websocket.send_json({
                "type": "ssh_error",
                "error": "Job has no IP address (instance may not be ready)"
            })
            # Continue without SSH - user can still see local info
            await _run_session_loop_no_ssh(websocket, status_queue)
            return

        # Start SSH connection
        await websocket.send_json({"type": "ssh_connecting"})

        # Connect SSH in thread pool
        loop = asyncio.get_event_loop()
        ssh_conn = await loop.run_in_executor(
            _executor,
            lambda: _get_ssh_connection_for_job(job_data, timeout=30)
        )

        if not ssh_conn:
            await websocket.send_json({"type": "ssh_error", "error": "SSH接続に失敗しました"})
            await _run_session_loop_no_ssh(websocket, status_queue)
            return

        await websocket.send_json({"type": "ssh_connected"})

        # Get initial remote status and progress (pass raw paramiko client to helper functions)
        await _send_remote_status(websocket, ssh_conn.client)
        await _send_progress(websocket, ssh_conn.client, job_data)

        # Determine log file path for later use
        log_file = _get_log_file_path(job_data)

        last_heartbeat = asyncio.get_event_loop().time()
        last_progress_update = asyncio.get_event_loop().time()

        while True:
            now = asyncio.get_event_loop().time()

            # Handle incoming client messages (non-blocking)
            try:
                # Use wait_for with short timeout to check for messages
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1
                )
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
                    await _send_progress(websocket, ssh_conn.client, job_data)

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
                                    await websocket.send_json({"type": "log", "line": line})

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
                await _send_progress(websocket, ssh_conn.client, job_data)
                last_progress_update = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES:
                await websocket.send_json({
                    "type": "job_status_changed",
                    "status": status
                })
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
) -> None:
    """Run session loop without SSH connection (local data only)."""
    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while True:
            now = asyncio.get_event_loop().time()

            # Handle incoming client messages
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1
                )
                action = message.get("action")

                if action == "start_logs":
                    await websocket.send_json({
                        "type": "ssh_error",
                        "error": "SSH接続がないためログを取得できません"
                    })

            except asyncio.TimeoutError:
                pass

            # Send heartbeat every 5 seconds
            if now - last_heartbeat > 5:
                await websocket.send_json({"type": "heartbeat"})
                last_heartbeat = now

            status = _drain_latest_status(status_queue) if status_queue else None
            if status and status not in RUNNING_STATUSES_WITH_PENDING:
                await websocket.send_json({
                    "type": "job_status_changed",
                    "status": status
                })
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
            lambda: _exec_ssh_command(ssh_client, f"tmux has-session -t {TMUX_SESSION_NAME} 2>/dev/null && echo 'running' || echo 'stopped'")
        )
        await websocket.send_json({
            "type": "remote_status",
            "status": status.strip() if status else "unknown"
        })
    except Exception as e:
        logger.debug(f"Failed to get remote status: {e}")
        await websocket.send_json({"type": "remote_status", "status": "error"})


async def _send_progress(websocket: WebSocket, ssh_client, job_data: dict) -> None:
    """Send training progress via existing SSH connection."""
    try:
        log_file = _get_log_file_path(job_data)

        loop = asyncio.get_event_loop()

        # Get step info
        step_cmd = f"grep -oE 'step:[0-9]+|Step [0-9]+|optimization_step=[0-9]+' {log_file} 2>/dev/null | tail -1 || true"
        step_line = await loop.run_in_executor(
            _executor,
            lambda: _exec_ssh_command(ssh_client, step_cmd)
        )

        # Get loss info
        loss_cmd = f"grep -oE 'loss[^=]*=[0-9.]+|Loss: [0-9.]+' {log_file} 2>/dev/null | tail -1 || true"
        loss_line = await loop.run_in_executor(
            _executor,
            lambda: _exec_ssh_command(ssh_client, loss_cmd)
        )

        await websocket.send_json({
            "type": "progress",
            "step": step_line.strip() if step_line else "N/A",
            "loss": loss_line.strip() if loss_line else "N/A"
        })
    except Exception as e:
        logger.debug(f"Failed to get progress: {e}")


def _exec_ssh_command(ssh_client, command: str) -> Optional[str]:
    """Execute SSH command and return stdout."""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(command, timeout=10)
        return stdout.read().decode()
    except Exception:
        return None
