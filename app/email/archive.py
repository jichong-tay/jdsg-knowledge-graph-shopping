"""Crash-safe storage of exact source email bytes."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MAX_EMAIL_BYTES = 20 * 1024 * 1024
ArchiveNamespace = Literal["manual", "gmail"]
_ARCHIVE_NAMESPACES = frozenset({"manual", "gmail"})


@dataclass(frozen=True, slots=True)
class ArchivedSource:
    sha256: str
    path: Path


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _ensure_synced_directory(path: Path, parent: Path) -> None:
    """Create path if missing and fsync it and its parent so the new entry survives a crash."""
    existed = path.exists()
    path.mkdir(mode=0o700, exist_ok=True)
    if not existed:
        path.chmod(0o700)
        _fsync_directory(path)
        _fsync_directory(parent)


def archive_raw_email(
    raw: bytes,
    root: Path,
    namespace: ArchiveNamespace = "manual",
) -> ArchivedSource:
    if not raw:
        raise ValueError("email is empty")
    if len(raw) > MAX_EMAIL_BYTES:
        raise ValueError(f"email exceeds the {MAX_EMAIL_BYTES}-byte limit")
    if namespace not in _ARCHIVE_NAMESPACES:
        raise ValueError("archive namespace must be 'manual' or 'gmail'")

    digest = hashlib.sha256(raw).hexdigest()
    namespace_dir = root / namespace
    directory = namespace_dir / digest[:2]
    _ensure_synced_directory(namespace_dir, root)
    _ensure_synced_directory(directory, namespace_dir)
    target = directory / f"{digest}.eml"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"archive hash mismatch for existing path: {target}")
        target.chmod(0o600)
        return ArchivedSource(digest, target)

    temporary = directory / f".{digest}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as file:
            os.chmod(temporary, 0o600)
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        _fsync_directory(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return ArchivedSource(digest, target)
