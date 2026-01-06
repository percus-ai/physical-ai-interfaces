"""Training jobs API router."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

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
)
from percus_ai.storage import get_jobs_dir, get_configs_dir, get_project_root

router = APIRouter(prefix="/api/training", tags=["training"])

# Jobs directory
JOBS_DIR = get_jobs_dir()

# Remote scripts directory - contains setup_env.sh, train_lerobot_entry.py, etc.
# These scripts are deployed to remote instances for training
REMOTE_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "archive" / "verda_cloud" / "remote"


# --- SSH utilities for remote deployment ---


def _connect_ssh(ip: str, user: str, private_key_path: str, timeout: int = 30) -> "paramiko.SSHClient":
    """Create an SSH client connected to the remote host.

    This is a strict version that raises exceptions on failure, for use in deployment.
    Supports RSA, Ed25519, and ECDSA keys.
    """
    import paramiko

    # Expand ~ in private key path
    key_path = Path(private_key_path).expanduser()
    if not key_path.exists():
        raise FileNotFoundError(f"SSH private key not found: {key_path}")

    # Try different key types
    pkey = None
    for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            pkey = key_cls.from_private_key_file(str(key_path))
            break
        except Exception:
            continue

    if not pkey:
        raise ValueError(f"Could not load SSH key from {key_path}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ip,
        username=user,
        pkey=pkey,
        timeout=timeout,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def _upload_file_via_sftp(
    ssh_client: "paramiko.SSHClient",
    local_path: Path,
    remote_path: str,
) -> None:
    """Upload a file via SFTP."""
    sftp = ssh_client.open_sftp()
    try:
        sftp.put(str(local_path), remote_path)
    finally:
        sftp.close()


def _upload_content_via_sftp(
    ssh_client: "paramiko.SSHClient",
    content: str,
    remote_path: str,
) -> None:
    """Upload string content as a file via SFTP."""
    sftp = ssh_client.open_sftp()
    try:
        with sftp.file(remote_path, "w") as f:
            f.write(content)
    finally:
        sftp.close()


def _run_ssh_command(
    ssh_client: "paramiko.SSHClient",
    command: str,
    timeout: Optional[int] = None,
) -> tuple[int, str, str]:
    """Run a command via SSH and return (exit_code, stdout, stderr)."""
    stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode(), stderr.read().decode()


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


def _get_verda_client():
    """Get Verda/DataCrunch client (if available)."""
    client_id = os.environ.get("DATACRUNCH_CLIENT_ID")
    client_secret = os.environ.get("DATACRUNCH_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    try:
        from datacrunch import DataCrunchClient

        return DataCrunchClient(client_id, client_secret)
    except ImportError:
        return None


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


def _get_job_file(job_id: str) -> Path:
    """Get job file path."""
    return JOBS_DIR / f"{job_id}.json"


def _load_job(job_id: str) -> Optional[dict]:
    """Load job from file."""
    job_file = _get_job_file(job_id)
    if not job_file.exists():
        return None
    with open(job_file, encoding="utf-8") as f:
        return json.load(f)


def _save_job(job_data: dict) -> None:
    """Save job to file."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_data["updated_at"] = datetime.now().isoformat()
    with open(_get_job_file(job_data["job_id"]), "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=2, ensure_ascii=False)


def _list_jobs(days: int = 7) -> list[dict]:
    """List jobs from files.

    Args:
        days: Return jobs from past N days.
              Running/starting jobs are always included.
    """
    if not JOBS_DIR.exists():
        return []

    jobs = []
    cutoff_date = datetime.now() - timedelta(days=days)

    for job_file in JOBS_DIR.glob("*.json"):
        try:
            with open(job_file, encoding="utf-8") as f:
                data = json.load(f)

            # Always include running/starting jobs
            if data.get("status") in ("running", "starting"):
                jobs.append(data)
                continue

            # Filter by date for others
            created_at = data.get("created_at")
            if created_at:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created.tzinfo:
                    created = created.replace(tzinfo=None)
                if created >= cutoff_date:
                    jobs.append(data)
        except Exception:
            continue

    # Sort by created_at descending
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs


# --- SSH utilities (optional, requires paramiko) ---


def _get_ssh_client(job_data: dict, timeout: int = 30):
    """Get SSH client for job instance."""
    try:
        import paramiko
    except ImportError:
        return None

    ip = job_data.get("ip")
    if not ip:
        return None

    try:
        # Load private key
        key_path = Path(job_data.get("ssh_private_key", "~/.ssh/id_rsa")).expanduser()
        pkey = None
        for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = key_cls.from_private_key_file(str(key_path))
                break
            except Exception:
                continue

        if not pkey:
            return None

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=ip,
            username=job_data.get("ssh_user", "root"),
            pkey=pkey,
            timeout=timeout,
        )
        return client
    except Exception:
        return None


def _check_remote_status(job_data: dict) -> str:
    """Check remote process status via SSH."""
    ssh = _get_ssh_client(job_data)
    if not ssh:
        return "unreachable"

    try:
        cmd = "tmux has-session -t lerobot_train 2>/dev/null && echo 'running' || echo 'stopped'"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        return stdout.read().decode().strip()
    except Exception:
        return "error"
    finally:
        ssh.close()


def _get_remote_logs(job_data: dict, lines: int = 100) -> Optional[str]:
    """Get remote logs via SSH."""
    ssh = _get_ssh_client(job_data)
    if not ssh:
        return None

    try:
        mode = job_data.get("mode", "train")
        remote_dir = job_data.get("remote_base_dir", "/root")
        log_file = f"{remote_dir}/setup_env_{mode}.log"
        cmd = f"tail -n {lines} {log_file} 2>/dev/null || echo '[Log file not found]'"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        return stdout.read().decode()
    except Exception:
        return None
    finally:
        ssh.close()


def _get_remote_progress(job_data: dict) -> Optional[dict]:
    """Get training progress via SSH."""
    ssh = _get_ssh_client(job_data)
    if not ssh:
        return None

    try:
        mode = job_data.get("mode", "train")
        remote_dir = job_data.get("remote_base_dir", "/root")
        log_file = f"{remote_dir}/setup_env_{mode}.log"

        # Get step info
        cmd = f"grep -oE 'step:[0-9]+|Step [0-9]+|optimization_step=[0-9]+' {log_file} 2>/dev/null | tail -1 || true"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        step_line = stdout.read().decode().strip()

        # Get loss info
        cmd = f"grep -oE 'loss[^=]*=[0-9.]+|Loss: [0-9.]+' {log_file} 2>/dev/null | tail -1 || true"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        loss_line = stdout.read().decode().strip()

        return {
            "step": step_line or "N/A",
            "loss": loss_line or "N/A",
        }
    except Exception:
        return None
    finally:
        ssh.close()


def _stop_remote_job(job_data: dict) -> bool:
    """Stop remote training job via SSH."""
    ssh = _get_ssh_client(job_data)
    if not ssh:
        return False

    try:
        cmd = "tmux kill-session -t lerobot_train 2>/dev/null || true"
        ssh.exec_command(cmd)
        return True
    except Exception:
        return False
    finally:
        ssh.close()


# --- API Endpoints ---


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
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)

    return JobActionResponse(
        job_id=job_id,
        success=success,
        message="Job stopped" if success else "Failed to stop job",
    )


@router.delete("/jobs/{job_id}", response_model=JobActionResponse)
async def delete_job(job_id: str):
    """Delete a job record."""
    job_file = _get_job_file(job_id)
    if not job_file.exists():
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    job_file.unlink()
    return JobActionResponse(
        job_id=job_id,
        success=True,
        message="Job record deleted",
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
            job_data["status"] = "completed"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
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
    # Check if Verda credentials are available
    client = _get_verda_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Verda/DataCrunch credentials not configured. "
            "Set DATACRUNCH_CLIENT_ID and DATACRUNCH_CLIENT_SECRET.",
        )

    job_id = request.name
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
            hostname=f"train-{job_id[:16]}",
        )

        # Save job info (status: starting)
        job_data = {
            "job_id": job_id,
            "instance_id": instance_id,
            "ip": None,
            "status": "starting",
            "config_name": job_id,
            "mode": "train",
            "ssh_user": "root",
            "ssh_private_key": ssh_private_key,
            "remote_base_dir": "/root",
            "checkpoint_repo_id": request.checkpoint_repo_id,
            "created_at": now,
            "updated_at": now,
            "gpu_model": request.cloud.gpu_model,
            "gpus_per_instance": request.cloud.gpus_per_instance,
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
        # Extract GPU count
        digits = []
        for ch in itype:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            continue

        try:
            count = int("".join(digits))
        except ValueError:
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
            detail=f"Location '{preferred}' not available for {instance_type}",
        )

    # Find any available location
    for loc in known_locations:
        try:
            if client.instances.is_available(
                instance_type=instance_type,
                is_spot=is_spot,
                location_code=loc,
            ):
                return loc
        except Exception:
            continue

    raise HTTPException(
        status_code=503,
        detail=f"No location available for {instance_type}",
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
    import time

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


async def _deploy_and_start_training(job_id: str, request: JobCreateRequest) -> None:
    """Background task to deploy and start training.

    This waits for the instance IP, uploads files, and starts training.
    """
    import time

    job_data = _load_job(job_id)
    if not job_data:
        return

    client = _get_verda_client()
    if not client:
        job_data["status"] = "failed"
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)
        return

    instance_id = job_data["instance_id"]

    try:
        # Wait for IP (up to 15 minutes)
        ip = None
        deadline = time.time() + 900
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
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            return

        # Update job with IP
        job_data["ip"] = ip
        job_data["status"] = "deploying"
        _save_job(job_data)

        # SSH deployment
        ssh_user = job_data.get("ssh_user", "root")
        ssh_private_key = job_data.get("ssh_private_key", "~/.ssh/id_rsa")
        remote_base_dir = job_data.get("remote_base_dir", "/root")
        remote_run_dir = f"{remote_base_dir}/lerobot_run"

        # Wait for SSH to be ready (up to 5 minutes)
        ssh_client = None
        ssh_deadline = time.time() + 300
        while time.time() < ssh_deadline:
            try:
                ssh_client = _connect_ssh(ip, ssh_user, ssh_private_key)
                break
            except Exception:
                time.sleep(10)

        if not ssh_client:
            job_data["status"] = "failed"
            job_data["error_message"] = "SSH connection failed"
            job_data["completed_at"] = datetime.now().isoformat()
            _save_job(job_data)
            return

        try:
            # Create remote directory
            _run_ssh_command(ssh_client, f"mkdir -p {remote_run_dir}")

            # Upload remote scripts
            setup_env_path = REMOTE_SCRIPTS_DIR / "setup_env.sh"
            read_config_path = REMOTE_SCRIPTS_DIR / "read_train_config.py"
            train_entry_path = REMOTE_SCRIPTS_DIR / "train_lerobot_entry.py"

            if setup_env_path.exists():
                _upload_file_via_sftp(ssh_client, setup_env_path, f"{remote_run_dir}/setup_env.sh")
            if read_config_path.exists():
                _upload_file_via_sftp(ssh_client, read_config_path, f"{remote_run_dir}/read_train_config.py")
            if train_entry_path.exists():
                _upload_file_via_sftp(ssh_client, train_entry_path, f"{remote_run_dir}/train_lerobot_entry.py")

            # Generate and upload training config YAML
            config_yaml = _generate_training_config_yaml(request, job_id)
            _upload_content_via_sftp(ssh_client, config_yaml, f"{remote_run_dir}/train.remote.yaml")

            # Generate and upload .env file
            instance_id = job_data["instance_id"]
            env_content = _generate_env_file(job_id, instance_id)
            _upload_content_via_sftp(ssh_client, env_content, f"{remote_run_dir}/.env")

            # Generate and upload instance_info.env
            instance_info = _generate_instance_info_env(job_id, instance_id, auto_delete=True)
            _upload_content_via_sftp(ssh_client, instance_info, f"{remote_run_dir}/instance_info.env")

            # Make setup script executable
            _run_ssh_command(ssh_client, f"chmod +x {remote_run_dir}/setup_env.sh")

            # Start training in background with nohup
            # The script will handle its own logging to setup_env_train.log
            start_cmd = (
                f"cd {remote_run_dir} && "
                f"nohup bash setup_env.sh train > /dev/null 2>&1 &"
            )
            _run_ssh_command(ssh_client, start_cmd)

            # Update status to running
            job_data["status"] = "running"
            job_data["updated_at"] = datetime.now().isoformat()
            _save_job(job_data)

        finally:
            ssh_client.close()

    except Exception as e:
        job_data["status"] = "failed"
        job_data["error_message"] = str(e)
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)


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
    try:
        import yaml
    except ImportError:
        return []

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
    try:
        import yaml
    except ImportError:
        return None

    config_file = _get_config_file(config_id)
    if not config_file.exists():
        return None

    with open(config_file, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config(config_id: str, config_data: dict) -> Path:
    """Save config to file."""
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="PyYAML not installed")

    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    config_file = _get_config_file(config_id)

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
            "train_lerobot_entry.py",
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
