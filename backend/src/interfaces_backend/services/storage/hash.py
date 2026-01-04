"""Hash calculation utilities for storage integrity checking."""

import hashlib
from pathlib import Path
from typing import Optional


def compute_file_hash(path: Path, use_content: bool = False) -> str:
    """Compute hash for a single file.

    Args:
        path: Path to the file
        use_content: If True, hash file content. If False, use name+size (faster).

    Returns:
        Hash string in format "sha256:xxxx" (16 char truncated)
    """
    hasher = hashlib.sha256()

    if use_content:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    else:
        hasher.update(path.name.encode())
        hasher.update(str(path.stat().st_size).encode())

    return f"sha256:{hasher.hexdigest()[:16]}"


def compute_directory_hash(path: Path, use_content: bool = False) -> str:
    """Compute hash for entire directory.

    Uses filename + size for fast hashing by default.
    Set use_content=True for content-based hashing (slower but more accurate).

    Args:
        path: Path to the directory
        use_content: If True, hash file contents. If False, use name+size.

    Returns:
        Hash string in format "sha256:xxxx" (16 char truncated)
    """
    hasher = hashlib.sha256()

    if not path.exists():
        return "sha256:0000000000000000"

    files = sorted(path.rglob("*"))
    for file in files:
        if file.is_file() and not file.name.startswith("."):
            hasher.update(file.relative_to(path).as_posix().encode())
            hasher.update(str(file.stat().st_size).encode())

            if use_content:
                with open(file, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        hasher.update(chunk)

    return f"sha256:{hasher.hexdigest()[:16]}"


def compute_directory_size(path: Path) -> int:
    """Calculate total size of directory in bytes.

    Args:
        path: Path to the directory

    Returns:
        Total size in bytes
    """
    if not path.exists():
        return 0

    total = 0
    for file in path.rglob("*"):
        if file.is_file():
            total += file.stat().st_size
    return total


def verify_hash(path: Path, expected_hash: str, use_content: bool = False) -> bool:
    """Verify that path matches expected hash.

    Args:
        path: Path to file or directory
        expected_hash: Expected hash string
        use_content: Use content-based hashing

    Returns:
        True if hash matches
    """
    if path.is_file():
        actual = compute_file_hash(path, use_content)
    else:
        actual = compute_directory_hash(path, use_content)

    return actual == expected_hash
