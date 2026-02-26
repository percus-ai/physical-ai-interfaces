"""Torch info utilities using subprocess to avoid numpy conflicts.

This module provides functions to get PyTorch/CUDA information without
directly importing torch, which prevents numpy version conflicts with
bundled-torch (compiled with numpy 1.x).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Cache for torch info
_torch_info_cache: Optional[Dict[str, Any]] = None


def get_torch_info(use_cache: bool = True) -> Dict[str, Any]:
    """Get PyTorch/CUDA information via subprocess.

    Args:
        use_cache: Whether to use cached result.

    Returns:
        Dictionary with torch_version, cuda_available, cuda_version,
        gpu_name, gpu_count, mps_available, cuda_memory_total,
        cuda_memory_free, error.
    """
    global _torch_info_cache
    if use_cache and _torch_info_cache is not None:
        return _torch_info_cache

    info: Dict[str, Any] = {
        "torch_version": None,
        "cuda_available": False,
        "cuda_version": None,
        "cuda_supported_arches": None,
        "gpu_capability": None,
        "cuda_compatible": None,
        "gpu_name": None,
        "gpu_count": 0,
        "mps_available": False,
        "cuda_memory_total": None,
        "cuda_memory_free": None,
        "error": None,
    }

    # Build PYTHONPATH with bundled-torch if it exists
    bundled_torch = Path.home() / ".cache" / "daihen-physical-ai" / "bundled-torch"
    env = os.environ.copy()
    if (bundled_torch / "pytorch").is_dir():
        pytorch_path = str(bundled_torch / "pytorch")
        torchvision_path = str(bundled_torch / "torchvision")
        env["PYTHONPATH"] = f"{pytorch_path}:{torchvision_path}:{env.get('PYTHONPATH', '')}"

    # Python code to run in subprocess
    torch_check_code = '''
import json
import torch
info = {
    "torch_version": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_version": None,
    "gpu_name": None,
    "gpu_count": 0,
    "mps_available": False,
    "cuda_memory_total": None,
    "cuda_memory_free": None,
    "error": None,
}
if info["cuda_available"]:
    info["cuda_version"] = torch.version.cuda or "N/A"
    info["gpu_count"] = torch.cuda.device_count()
    if info["gpu_count"] > 0:
        info["gpu_name"] = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        info["gpu_capability"] = f"sm_{props.major}{props.minor}"
        info["cuda_memory_total"] = props.total_memory / (1024 * 1024)  # MB
        info["cuda_memory_free"] = (
            props.total_memory - torch.cuda.memory_allocated(0)
        ) / (1024 * 1024)  # MB
        if hasattr(torch.cuda, "get_arch_list"):
            info["cuda_supported_arches"] = torch.cuda.get_arch_list()
            if info["cuda_supported_arches"]:
                info["cuda_compatible"] = info["gpu_capability"] in info["cuda_supported_arches"]
            else:
                info["cuda_compatible"] = True
        else:
            info["cuda_supported_arches"] = None
            info["cuda_compatible"] = True
else:
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        info["mps_available"] = True
print(json.dumps(info))
'''

    try:
        result = subprocess.run(
            [sys.executable, "-c", torch_check_code],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            info = json.loads(result.stdout.strip())
        else:
            info["error"] = "Failed to get PyTorch info"
    except subprocess.TimeoutExpired:
        info["error"] = "Timeout checking PyTorch"
    except Exception as e:
        info["error"] = str(e)

    if use_cache:
        _torch_info_cache = info
    return info


def clear_cache() -> None:
    """Clear the torch info cache."""
    global _torch_info_cache
    _torch_info_cache = None
