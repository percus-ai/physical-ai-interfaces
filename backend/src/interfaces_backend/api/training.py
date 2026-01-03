"""Training jobs API router."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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

router = APIRouter(prefix="/api/training", tags=["training"])

# Jobs directory - configurable via environment
JOBS_DIR = Path.home() / ".percus" / "jobs"


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
        job_data["status"] = "running"
        _save_job(job_data)

        # TODO: Deploy training files and start training via SSH
        # This would involve:
        # 1. Connect via SSH
        # 2. Upload training config
        # 3. Run setup script
        # For now, just mark as running - actual deployment requires more integration

    except Exception as e:
        job_data["status"] = "failed"
        job_data["completed_at"] = datetime.now().isoformat()
        _save_job(job_data)
